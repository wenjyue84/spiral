"""Integration test for lib/cost_forecast.py (US-650).

Mocks results.tsv with 10 iterations and asserts the forecast is within
±20% of the synthetic ground truth.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from cost_forecast import compute_velocity, forecast

RESULTS_HEADER = [
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


def _make_row(
    spiral_iter: int,
    story_id: str,
    status: str = "keep",
    cache_read_tokens: int = 5000,
    cache_creation_tokens: int = 3000,
    review_tokens: int = 2000,
) -> dict[str, str]:
    return {
        "timestamp": "2026-03-21T10:00:00Z",
        "spiral_iter": str(spiral_iter),
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Story {story_id}",
        "status": status,
        "duration_sec": "300",
        "model": "sonnet",
        "retry_num": "0",
        "commit_sha": "abc123",
        "run_id": "",
        "cache_hit": "false",
        "cache_read_tokens": str(cache_read_tokens),
        "cache_creation_tokens": str(cache_creation_tokens),
        "review_tokens": str(review_tokens),
        "wall_seconds": "300",
        "user_cpu_s": "0",
        "sys_cpu_s": "0",
        "peak_rss_kb": "0",
        "batch_id": "",
    }


def _write_results(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestComputeVelocity:
    def test_empty_results(self) -> None:
        result = compute_velocity([])
        assert result["velocity"] == 0.0
        assert result["cost_velocity"] == 0.0
        assert result["completed_iterations"] == 0.0

    def test_single_iteration_two_passes(self) -> None:
        rows = [
            _make_row(1, "US-001", status="keep"),
            _make_row(1, "US-002", status="keep"),
        ]
        result = compute_velocity(rows, last_n_iterations=5)
        # 2 stories pass, 10000 tokens total (5000+3000+2000 per story)
        assert result["velocity"] == 2.0
        assert result["cost_velocity"] == 20000.0
        assert result["completed_iterations"] == 1.0

    def test_last_n_window_trims_oldest(self) -> None:
        """With 10 iterations and last_n=5, only the last 5 count."""
        rows: list[dict[str, str]] = []
        for i in range(1, 11):
            rows.append(_make_row(i, f"US-{i:03d}a", status="keep"))
            rows.append(_make_row(i, f"US-{i:03d}b", status="keep"))
        result = compute_velocity(rows, last_n_iterations=5)
        assert result["velocity"] == 2.0
        assert result["cost_velocity"] == 20000.0
        assert result["completed_iterations"] == 5.0

    def test_reject_rows_not_counted_in_velocity(self) -> None:
        rows = [
            _make_row(1, "US-001", status="reject"),
            _make_row(1, "US-002", status="keep"),
        ]
        result = compute_velocity(rows, last_n_iterations=5)
        assert result["velocity"] == 1.0

    def test_reject_tokens_still_counted(self) -> None:
        """Rejected stories still consume tokens — include them in cost_velocity."""
        rows = [
            _make_row(
                1, "US-001", status="reject", cache_read_tokens=5000, cache_creation_tokens=3000, review_tokens=2000
            ),
            _make_row(
                1, "US-002", status="keep", cache_read_tokens=5000, cache_creation_tokens=3000, review_tokens=2000
            ),
        ]
        result = compute_velocity(rows, last_n_iterations=5)
        assert result["cost_velocity"] == 20000.0


class TestForecast:
    def test_basic_10_iteration_forecast(self, tmp_path: Path) -> None:
        """10 synthetic iterations → forecast within ±20% of ground truth."""
        results_path = tmp_path / "results.tsv"
        prd_path = tmp_path / "prd.json"

        # 10 iterations × 2 passes × 10000 tokens each
        rows: list[dict[str, str]] = []
        for i in range(1, 11):
            rows.append(_make_row(i, f"US-{i:03d}a", status="keep"))
            rows.append(_make_row(i, f"US-{i:03d}b", status="keep"))
        _write_results(results_path, rows)

        # 20 remaining stories
        prd_data = {
            "userStories": [{"id": f"US-{100 + i}", "title": f"Pending {i}", "passes": False} for i in range(20)]
        }
        prd_path.write_text(json.dumps(prd_data), encoding="utf-8")

        result = forecast(prd_path=prd_path, results_path=results_path, last_n=5)

        # Ground truth: velocity=2.0, cost_velocity=20000, iterations_needed=10, projected_cost=200000
        expected_iterations = 10.0
        expected_cost = 200000.0

        assert result["remaining_stories"] == 20
        assert abs(result["iterations_needed"] - expected_iterations) / expected_iterations <= 0.20
        assert abs(result["projected_cost"] - expected_cost) / expected_cost <= 0.20
        assert result["confidence_pct"] == 100.0

    def test_output_has_required_keys(self, tmp_path: Path) -> None:
        prd_path = tmp_path / "prd.json"
        results_path = tmp_path / "results.tsv"
        prd_path.write_text(json.dumps({"userStories": []}), encoding="utf-8")
        _write_results(results_path, [])

        result = forecast(prd_path=prd_path, results_path=results_path)
        assert {"remaining_stories", "iterations_needed", "projected_cost", "confidence_pct"}.issubset(result.keys())

    def test_no_results_gives_zero_confidence(self, tmp_path: Path) -> None:
        prd_path = tmp_path / "prd.json"
        results_path = tmp_path / "results.tsv"
        prd_path.write_text(
            json.dumps({"userStories": [{"id": "US-001", "title": "T", "passes": False}]}),
            encoding="utf-8",
        )
        _write_results(results_path, [])

        result = forecast(prd_path=prd_path, results_path=results_path)
        assert result["confidence_pct"] == 0.0
        assert result["remaining_stories"] == 1

    def test_partial_data_scales_confidence(self, tmp_path: Path) -> None:
        """3 iterations with last_n=5 → 60% confidence."""
        results_path = tmp_path / "results.tsv"
        prd_path = tmp_path / "prd.json"

        rows = [_make_row(i, f"US-{i:03d}", status="keep") for i in range(1, 4)]
        _write_results(results_path, rows)
        prd_path.write_text(json.dumps({"userStories": []}), encoding="utf-8")

        result = forecast(prd_path=prd_path, results_path=results_path, last_n=5)
        assert result["confidence_pct"] == pytest.approx(60.0, abs=1.0)

    def test_zero_remaining_stories(self, tmp_path: Path) -> None:
        """If all stories pass, iterations_needed and projected_cost are 0."""
        results_path = tmp_path / "results.tsv"
        prd_path = tmp_path / "prd.json"

        rows = [_make_row(1, "US-001", status="keep")]
        _write_results(results_path, rows)
        prd_path.write_text(
            json.dumps({"userStories": [{"id": "US-001", "passes": True}]}),
            encoding="utf-8",
        )

        result = forecast(prd_path=prd_path, results_path=results_path)
        assert result["remaining_stories"] == 0
        assert result["iterations_needed"] == 0.0
        assert result["projected_cost"] == 0.0
