"""tests/test_extract_failed_stories.py — Integration tests for US-613.

Tests extract_failed_stories CLI and library with mock results.tsv data.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Add lib/ to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from extract_failed_stories import (  # noqa: E402
    extract_failed_stories,
    format_markdown,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

TSV_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
    "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id"
)


def _make_row(
    story_id: str,
    title: str,
    status: str,
    model: str,
    retry_num: int,
    cache_read: int = 100000,
    cache_create: int = 50000,
    duration: int = 120,
) -> str:
    return (
        f"2026-03-20T10:00:00Z\t1\t1\t{story_id}\t{title}\t{status}\t"
        f"{duration}\t{model}\t{retry_num}\tabc123\trun1\ttrue\t"
        f"{cache_read}\t{cache_create}\t0\t0\t0\t0\t0\t"
    )


@pytest.fixture()
def mock_results_tsv(tmp_path: Path) -> Path:
    """Create a mock results.tsv with 3 stories matching AC3 spec.

    Story 1: US-100 — 0 retries, haiku pass (1 attempt, status=accept)
    Story 2: US-200 — 2 retries, sonnet fail (2 rejects + 1 accept attempt)
    Story 3: US-300 — 4 retries, opus fail (4 rejects, exponential token growth)
    """
    rows = [
        TSV_HEADER,
        # US-100: haiku pass, 0 retries
        _make_row("US-100", "Easy Story", "accept", "haiku", 0),
        # US-200: 2 retries with sonnet, then fail
        _make_row("US-200", "Medium Story", "reject", "haiku", 0, cache_read=100000, cache_create=50000),
        _make_row("US-200", "Medium Story", "reject", "sonnet", 1, cache_read=120000, cache_create=60000),
        # US-300: 4 retries with escalation, exponential token growth
        _make_row("US-300", "Hard Story", "reject", "haiku", 0, cache_read=100000, cache_create=50000),
        _make_row("US-300", "Hard Story", "reject", "sonnet", 1, cache_read=200000, cache_create=100000),
        _make_row("US-300", "Hard Story", "reject", "sonnet", 2, cache_read=400000, cache_create=200000),
        _make_row("US-300", "Hard Story", "reject", "opus", 3, cache_read=800000, cache_create=400000),
    ]
    tsv_path = tmp_path / "results.tsv"
    tsv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return tsv_path


# ── Unit Tests ───────────────────────────────────────────────────────────────


def test_extract_returns_dict(mock_results_tsv: Path) -> None:
    """extract_failed_stories returns a dict with 'stories' and 'summary'."""
    report = extract_failed_stories(mock_results_tsv)
    assert "stories" in report
    assert "summary" in report


def test_stories_sorted_by_retry_count(mock_results_tsv: Path) -> None:
    """Stories are sorted by retry count descending."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    stories = report["stories"]
    retry_counts = [s["retry_count"] for s in stories]
    assert retry_counts == sorted(retry_counts, reverse=True)


def test_min_retries_filter(mock_results_tsv: Path) -> None:
    """--min-retries filters out stories below the threshold."""
    report = extract_failed_stories(mock_results_tsv, min_retries=3)
    # Only US-300 (4 retries) should appear
    assert len(report["stories"]) == 1
    assert report["stories"][0]["story_id"] == "US-300"


def test_min_retries_zero_includes_all(mock_results_tsv: Path) -> None:
    """min_retries=0 includes all stories including those with 0 retries."""
    report = extract_failed_stories(mock_results_tsv, min_retries=0)
    story_ids = {s["story_id"] for s in report["stories"]}
    # US-100 has 0 retries but 1 accept, so it appears only if min_retries=0
    assert "US-200" in story_ids
    assert "US-300" in story_ids


def test_model_escalation_pattern(mock_results_tsv: Path) -> None:
    """Model escalation is correctly detected for US-300."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    us300 = next(s for s in report["stories"] if s["story_id"] == "US-300")
    # Should show haiku -> sonnet -> opus escalation
    assert "haiku" in us300["model_escalation"]
    assert "opus" in us300["model_escalation"]


def test_token_burn_per_attempt(mock_results_tsv: Path) -> None:
    """Token burn is computed per attempt."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    us300 = next(s for s in report["stories"] if s["story_id"] == "US-300")
    assert len(us300["token_burns"]) == 4
    # First attempt: 100000 + 50000 = 150000
    assert us300["token_burns"][0]["tokens"] == 150000


def test_decompose_suggestion_for_high_retry(mock_results_tsv: Path) -> None:
    """US-300 (4 retries, exponential growth) should get 'decompose' suggestion."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    us300 = next(s for s in report["stories"] if s["story_id"] == "US-300")
    assert us300["suggestion"] == "decompose"


def test_empty_results_tsv(tmp_path: Path) -> None:
    """Empty results.tsv returns empty report."""
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + "\n", encoding="utf-8")
    report = extract_failed_stories(tsv)
    assert report["stories"] == []
    assert report["summary"]["total_stories_analyzed"] == 0


def test_missing_results_tsv(tmp_path: Path) -> None:
    """Missing results.tsv returns empty report without error."""
    report = extract_failed_stories(tmp_path / "nonexistent.tsv")
    assert report["stories"] == []


def test_format_markdown(mock_results_tsv: Path) -> None:
    """Markdown format includes story headers and table."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    md = format_markdown(report)
    assert "# Failed Stories Triage Report" in md
    assert "US-300" in md
    assert "| Retry |" in md


def test_summary_counts(mock_results_tsv: Path) -> None:
    """Summary includes correct counts."""
    report = extract_failed_stories(mock_results_tsv, min_retries=1)
    summary = report["summary"]
    assert summary["total_stories_analyzed"] == 3  # 3 unique stories
    assert summary["stories_with_failures"] >= 2  # US-200 and US-300


# ── Integration Test (AC3) ───────────────────────────────────────────────────


def test_ac3_integration(mock_results_tsv: Path) -> None:
    """AC3: Mock results.tsv with 3 stories; verify CLI output correctly
    identifies high-retry stories and suggests 'decompose' for 4-retry case.

    Stories:
      US-100: 0 retries, haiku pass
      US-200: 2 retries, sonnet fail
      US-300: 4 retries, opus fail → should suggest 'decompose'
    """
    report = extract_failed_stories(mock_results_tsv, min_retries=1)

    # US-300 should be first (highest retry count)
    stories = report["stories"]
    assert len(stories) >= 2

    us300 = next(s for s in stories if s["story_id"] == "US-300")
    assert us300["retry_count"] == 4
    assert us300["suggestion"] == "decompose"

    # US-200 should also appear
    us200 = next(s for s in stories if s["story_id"] == "US-200")
    assert us200["retry_count"] == 2

    # US-100 should NOT appear (0 retries, min_retries=1)
    us100_ids = [s["story_id"] for s in stories if s["story_id"] == "US-100"]
    assert len(us100_ids) == 0


def test_cli_json_output(mock_results_tsv: Path) -> None:
    """CLI integration: running via subprocess produces valid JSON."""
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "main.py"),
            "extract-failed-stories",
            "--results",
            str(mock_results_tsv),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    data = json.loads(result.stdout)
    assert "stories" in data
    assert "summary" in data


def test_cli_markdown_output(mock_results_tsv: Path) -> None:
    """CLI integration: --format markdown produces readable output."""
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "main.py"),
            "extract-failed-stories",
            "--results",
            str(mock_results_tsv),
            "--format",
            "markdown",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "# Failed Stories Triage Report" in result.stdout
    assert "US-300" in result.stdout
