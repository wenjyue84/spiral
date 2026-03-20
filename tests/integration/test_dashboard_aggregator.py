"""Integration tests for US-625: Dashboard Aggregation Layer.

Verifies that aggregate_overview() correctly computes unified cross-project
metrics when 2 sub-projects have independent Phase I runs.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure lib/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from spiral.dashboard.aggregator import _read_tsv, aggregate_overview

# ── Helpers ───────────────────────────────────────────────────────────────────

_TSV_HEADERS = [
    "timestamp",
    "spiral_iter",
    "ralph_iter",
    "story_id",
    "story_title",
    "status",
    "duration_sec",
    "model",
    "retry_num",
    "commit_sha",
    "run_id",
    "cache_hit",
    "cache_read_tokens",
    "cache_creation_tokens",
    "review_tokens",
    "wall_seconds",
    "user_cpu_s",
    "sys_cpu_s",
    "peak_rss_kb",
    "batch_id",
]


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a results.tsv fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_TSV_HEADERS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_row(
    story_id: str,
    status: str = "keep",
    duration_sec: float = 10.0,
    model: str = "haiku",
    retry_num: int = 0,
    cache_read_tokens: int = 100_000,
    cache_creation_tokens: int = 10_000,
    review_tokens: int = 1_000,
) -> dict[str, Any]:
    return {
        "timestamp": "2026-03-21T00:00:00Z",
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Story {story_id}",
        "status": status,
        "duration_sec": str(duration_sec),
        "model": model,
        "retry_num": str(retry_num),
        "commit_sha": "",
        "run_id": "abc123",
        "cache_hit": "false",
        "cache_read_tokens": str(cache_read_tokens),
        "cache_creation_tokens": str(cache_creation_tokens),
        "review_tokens": str(review_tokens),
        "wall_seconds": "0",
        "user_cpu_s": "0",
        "sys_cpu_s": "0",
        "peak_rss_kb": "0",
        "batch_id": "",
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAggregateOverview:
    """Tests for aggregate_overview() with two independent sub-projects."""

    def test_stories_passed_summed_across_sub_projects(self, tmp_path: Path) -> None:
        """storiesPassed sums keep rows from both sub-projects."""
        proj_a = tmp_path / "project-a" / "results.tsv"
        proj_b = tmp_path / "project-b" / "results.tsv"

        _write_tsv(
            proj_a,
            [
                _make_row("US-001", status="keep"),
                _make_row("US-002", status="keep"),
            ],
        )
        _write_tsv(
            proj_b,
            [
                _make_row("US-003", status="keep"),
                _make_row("US-004", status="reject"),
            ],
        )

        result = aggregate_overview([proj_a, proj_b])
        assert result["storiesPassed"] == 3

    def test_blocker_count_non_keep_rows(self, tmp_path: Path) -> None:
        """blockerCount counts failed/rejected rows across both projects."""
        proj_a = tmp_path / "project-a" / "results.tsv"
        proj_b = tmp_path / "project-b" / "results.tsv"

        _write_tsv(
            proj_a,
            [
                _make_row("US-001", status="keep"),
                _make_row("US-002", status="failed"),
            ],
        )
        _write_tsv(
            proj_b,
            [
                _make_row("US-003", status="reject"),
                _make_row("US-004", status="keep"),
            ],
        )

        result = aggregate_overview([proj_a, proj_b])
        assert result["blockerCount"] == 2

    def test_slowest_sub_project_points_to_correct_project(self, tmp_path: Path) -> None:
        """slowestSubProject is the directory of the project with highest avg duration."""
        proj_a = tmp_path / "fast-project" / "results.tsv"
        proj_b = tmp_path / "slow-project" / "results.tsv"

        _write_tsv(
            proj_a,
            [
                _make_row("US-001", duration_sec=5.0),
                _make_row("US-002", duration_sec=10.0),
            ],
        )
        _write_tsv(
            proj_b,
            [
                _make_row("US-003", duration_sec=200.0),
                _make_row("US-004", duration_sec=300.0),
            ],
        )

        result = aggregate_overview([proj_a, proj_b])
        assert result["slowestSubProject"] == "slow-project"

    def test_avg_phase_time_is_mean_duration_across_all_rows(self, tmp_path: Path) -> None:
        """avgPhaseTime is mean duration_sec across all rows from both projects."""
        proj_a = tmp_path / "project-a" / "results.tsv"
        proj_b = tmp_path / "project-b" / "results.tsv"

        _write_tsv(proj_a, [_make_row("US-001", duration_sec=10.0)])
        _write_tsv(proj_b, [_make_row("US-002", duration_sec=30.0)])

        result = aggregate_overview([proj_a, proj_b])
        assert result["avgPhaseTime"] == pytest.approx(20.0)

    def test_total_cost_summed_from_tokens(self, tmp_path: Path) -> None:
        """totalCost is a non-negative float derived from token counts."""
        proj_a = tmp_path / "project-a" / "results.tsv"
        _write_tsv(
            proj_a,
            [
                _make_row(
                    "US-001", model="haiku", cache_read_tokens=1_000_000, cache_creation_tokens=0, review_tokens=0
                ),
            ],
        )
        result = aggregate_overview([proj_a])
        # haiku rate = $0.25/M tokens; 1M tokens => ~$0.25
        assert result["totalCost"] == pytest.approx(0.25, abs=0.01)

    def test_empty_paths_returns_zero_metrics(self) -> None:
        """aggregate_overview with no paths returns all-zero metrics."""
        result = aggregate_overview([])
        assert result["storiesPassed"] == 0
        assert result["blockerCount"] == 0
        assert result["avgPhaseTime"] == 0.0
        assert result["totalCost"] == 0.0
        assert result["slowestSubProject"] == ""

    def test_missing_tsv_is_skipped_gracefully(self, tmp_path: Path) -> None:
        """A path that does not exist contributes zero rows without error."""
        missing = tmp_path / "ghost" / "results.tsv"
        existing = tmp_path / "real" / "results.tsv"
        _write_tsv(existing, [_make_row("US-001", status="keep")])

        result = aggregate_overview([missing, existing])
        assert result["storiesPassed"] == 1
        assert result["subProjectCount"] == 2

    def test_escalation_pct_reflects_retry_rows(self, tmp_path: Path) -> None:
        """escalationPct is the fraction of rows with retry_num >= 1."""
        proj_a = tmp_path / "project-a" / "results.tsv"
        _write_tsv(
            proj_a,
            [
                _make_row("US-001", retry_num=0),
                _make_row("US-002", retry_num=1),
                _make_row("US-003", retry_num=2),
                _make_row("US-004", retry_num=0),
            ],
        )
        result = aggregate_overview([proj_a])
        assert result["escalationPct"] == pytest.approx(0.5)

    def test_metrics_update_when_tsv_changes(self, tmp_path: Path) -> None:
        """Calling aggregate_overview again after writing new rows returns updated metrics."""
        proj = tmp_path / "project-a" / "results.tsv"
        _write_tsv(proj, [_make_row("US-001", status="keep")])

        first = aggregate_overview([proj])
        assert first["storiesPassed"] == 1

        # Simulate Phase I completing another story
        _write_tsv(
            proj,
            [
                _make_row("US-001", status="keep"),
                _make_row("US-002", status="keep"),
            ],
        )
        second = aggregate_overview([proj])
        assert second["storiesPassed"] == 2

    def test_sub_project_count_matches_input(self, tmp_path: Path) -> None:
        """subProjectCount equals the number of paths passed."""
        paths = []
        for i in range(3):
            p = tmp_path / f"proj-{i}" / "results.tsv"
            _write_tsv(p, [_make_row(f"US-{i:03d}")])
            paths.append(p)

        result = aggregate_overview(paths)
        assert result["subProjectCount"] == 3


class TestReadTsv:
    """Unit tests for _read_tsv helper."""

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        rows = _read_tsv(tmp_path / "nonexistent.tsv")
        assert rows == []

    def test_filters_by_sub_project_column(self, tmp_path: Path) -> None:
        """When sub_project column exists, filter to matching rows."""
        path = tmp_path / "combined.tsv"
        headers = _TSV_HEADERS + ["sub_project"]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            row_a = {h: "" for h in headers}
            row_a.update({"story_id": "US-001", "status": "keep", "sub_project": "proj-a"})
            row_b = {h: "" for h in headers}
            row_b.update({"story_id": "US-002", "status": "keep", "sub_project": "proj-b"})
            writer.writerows([row_a, row_b])

        rows = _read_tsv(path, sub_project="proj-a")
        assert len(rows) == 1
        assert rows[0]["story_id"] == "US-001"
