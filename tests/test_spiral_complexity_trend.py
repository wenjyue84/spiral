"""
tests/test_spiral_complexity_trend.py — Integration tests for complexity_trend.py.

Covers:
- Mock results.tsv with 10 stories (3 with 3+ retries)
- CSV output format
- JSON output format with phase_avg_retries
- Escalation count accuracy
- p50 duration calculation
- Missing TSV graceful handling
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib/ to path for direct imports
LIB_DIR = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from complexity_trend import (  # noqa: E402
    _p50,
    build_phase_report,
    compute_story_metrics,
    load_results,
    run_trend,
    write_csv,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

TSV_HEADER = [
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
]


def _make_row(
    story_id: str,
    retry_num: int,
    model: str = "haiku",
    duration_sec: float = 60.0,
    status: str = "pass",
) -> dict[str, str]:
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "spiral_iter": "1",
        "ralph_iter": str(retry_num),
        "story_id": story_id,
        "story_title": f"Story {story_id}",
        "status": status,
        "duration_sec": str(duration_sec),
        "model": model,
        "retry_num": str(retry_num),
        "commit_sha": "abc1234",
    }


def _write_tsv(path: str, rows: list[dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TSV_HEADER, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture()
def mock_tsv(tmp_path: Path) -> str:
    """10 stories, 3 of which have 3+ retries with model escalations."""
    rows: list[dict[str, str]] = []

    # 7 simple stories — 1 retry each (haiku only)
    for i in range(1, 8):
        rows.append(_make_row(f"US-{100 + i}", retry_num=0, model="haiku", duration_sec=30.0))

    # 3 escalation stories — 3 retries each: haiku → sonnet → opus
    for i in range(8, 11):
        rows.append(_make_row(f"US-{100 + i}", retry_num=0, model="haiku", duration_sec=60.0))
        rows.append(_make_row(f"US-{100 + i}", retry_num=1, model="sonnet", duration_sec=90.0))
        rows.append(_make_row(f"US-{100 + i}", retry_num=2, model="opus", duration_sec=120.0))

    tsv_path = str(tmp_path / "results.tsv")
    _write_tsv(tsv_path, rows)
    return tsv_path


# ── Unit tests ────────────────────────────────────────────────────────────────


def test_p50_odd() -> None:
    assert _p50([1.0, 2.0, 3.0]) == 2.0


def test_p50_even() -> None:
    assert _p50([1.0, 3.0]) == 2.0


def test_p50_empty() -> None:
    assert _p50([]) == 0.0


def test_load_results_missing_file() -> None:
    rows = load_results("/nonexistent/results.tsv")
    assert rows == []


def test_load_results_reads_rows(mock_tsv: str) -> None:
    rows = load_results(mock_tsv)
    # 7 simple + 3*3 escalation = 16 rows
    assert len(rows) == 16


def test_compute_story_metrics_count(mock_tsv: str) -> None:
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    assert len(metrics) == 10


def test_simple_story_has_one_retry(mock_tsv: str) -> None:
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    simple = [m for m in metrics if m["avg_retries"] == 1]
    assert len(simple) == 7


def test_escalation_stories_have_three_retries(mock_tsv: str) -> None:
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    escalated = [m for m in metrics if m["avg_retries"] == 3]
    assert len(escalated) == 3


def test_escalation_count_per_story(mock_tsv: str) -> None:
    """Each 3-retry story (haiku→sonnet→opus) should have 2 escalations."""
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    escalated = [m for m in metrics if m["avg_retries"] == 3]
    for m in escalated:
        assert m["model_escalations"] == 2, (
            f"Expected 2 escalations for {m['id']}, got {m['model_escalations']}"
        )


def test_no_escalations_for_simple_stories(mock_tsv: str) -> None:
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    simple = [m for m in metrics if m["avg_retries"] == 1]
    for m in simple:
        assert m["model_escalations"] == 0


def test_p50_duration_escalation_story(mock_tsv: str) -> None:
    """Escalation stories have durations [60, 90, 120] → p50=90."""
    rows = load_results(mock_tsv)
    metrics = compute_story_metrics(rows, phase_filter="I")
    escalated = [m for m in metrics if m["avg_retries"] == 3]
    for m in escalated:
        assert m["p50_duration_seconds"] == pytest.approx(90.0)


# ── Integration: run_trend function ───────────────────────────────────────────


def test_run_trend_json_format(mock_tsv: str) -> None:
    report = run_trend(tsv_path=mock_tsv, phase="I", fmt="json")
    assert report["phase"] == "I"
    assert "stories" in report
    assert len(report["stories"]) == 10
    assert "phase_avg_retries" in report
    assert isinstance(report["phase_avg_retries"], float)


def test_run_trend_json_phase_avg_retries(mock_tsv: str) -> None:
    """7 stories × 1 retry + 3 stories × 3 retries = 16 / 10 = 1.6"""
    report = run_trend(tsv_path=mock_tsv, phase="I", fmt="json")
    assert report["phase_avg_retries"] == pytest.approx(1.6)


def test_run_trend_json_total_escalations(mock_tsv: str) -> None:
    """3 stories × 2 escalations = 6 total"""
    report = run_trend(tsv_path=mock_tsv, phase="I", fmt="json")
    assert report["total_escalations"] == 6


def test_run_trend_json_story_structure(mock_tsv: str) -> None:
    report = run_trend(tsv_path=mock_tsv, phase="I", fmt="json")
    for story in report["stories"]:
        assert "id" in story
        assert "retries" in story
        assert isinstance(story["retries"], list)
        assert "duration_seconds" in story
        assert "escalations" in story


def test_run_trend_csv_output_file(mock_tsv: str, tmp_path: Path) -> None:
    out_path = str(tmp_path / "trend-report.csv")
    run_trend(tsv_path=mock_tsv, phase="I", output_path=out_path, fmt="csv")
    assert os.path.exists(out_path)
    with open(out_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 10
    assert "story_id" in rows[0]
    assert "avg_retries" in rows[0]
    assert "p50_duration_seconds" in rows[0]
    assert "model_escalations" in rows[0]
    assert "tokens_per_retry" in rows[0]


def test_run_trend_csv_escalation_values(mock_tsv: str, tmp_path: Path) -> None:
    out_path = str(tmp_path / "trend-report.csv")
    run_trend(tsv_path=mock_tsv, phase="I", output_path=out_path, fmt="csv")
    with open(out_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    escalated = [r for r in rows if r["model_escalations"] == "2"]
    assert len(escalated) == 3, f"Expected 3 rows with 2 escalations, got {len(escalated)}"


def test_run_trend_empty_tsv(tmp_path: Path) -> None:
    tsv_path = str(tmp_path / "empty.tsv")
    _write_tsv(tsv_path, [])
    report = run_trend(tsv_path=tsv_path, phase="I", fmt="json")
    assert report["stories"] == []
    assert report["phase_avg_retries"] == 0.0


def test_run_trend_missing_tsv(tmp_path: Path) -> None:
    report = run_trend(tsv_path=str(tmp_path / "no.tsv"), phase="I", fmt="json")
    assert report["stories"] == []


# ── Integration: CLI subprocess ───────────────────────────────────────────────


def test_cli_json_output(mock_tsv: str) -> None:
    """Run CLI via subprocess and parse stdout JSON."""
    result = subprocess.run(
        [sys.executable, str(LIB_DIR / "complexity_trend.py"),
         "--phase", "I", "--history", mock_tsv, "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["phase"] == "I"
    assert len(data["stories"]) == 10


def test_cli_csv_output_file(mock_tsv: str, tmp_path: Path) -> None:
    out = str(tmp_path / "out.csv")
    result = subprocess.run(
        [sys.executable, str(LIB_DIR / "complexity_trend.py"),
         "--phase", "I", "--history", mock_tsv, "--output", out],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 10
