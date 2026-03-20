"""Tests for lib/extract_failed_stories.py (US-613)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from extract_failed_stories import (
    extract_failed_stories,
    format_markdown,
)

HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\t"
    "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id"
)


def _row(
    story_id: str,
    title: str,
    status: str,
    model: str,
    retry_num: int,
    read_tokens: int = 100000,
    creation_tokens: int = 50000,
) -> str:
    return (
        f"2026-03-20T00:00:00Z\t1\t1\t{story_id}\t{title}\t{status}\t"
        f"120\t{model}\t{retry_num}\tabc123\trun1\ttrue\t"
        f"{read_tokens}\t{creation_tokens}\t0\t0\t0\t0\t0\t"
    )


def _write_tsv(tmp_path: Path, rows: list[str]) -> Path:
    tsv = tmp_path / "results.tsv"
    tsv.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return tsv


def test_three_story_integration(tmp_path: Path) -> None:
    """AC3: mock results.tsv with 3 stories: 0-retry haiku-pass,
    2-retry sonnet-fail, 4-retry opus-fail. Verify CLI identifies
    high-retry stories and suggests 'decompose' for the 4-retry case."""
    rows = [
        # Story A: 0 retries, passes with haiku
        _row("US-001", "Simple feature", "accept", "haiku", 0),
        # Story B: 2 retries, fails with sonnet
        _row("US-002", "Medium feature", "reject", "haiku", 0),
        _row("US-002", "Medium feature", "reject", "sonnet", 1),
        _row("US-002", "Medium feature", "accept", "sonnet", 2, 200000, 100000),
        # Story C: 4 retries, fails with opus (exponential token growth)
        _row("US-003", "Complex feature", "reject", "haiku", 0, 100000, 50000),
        _row("US-003", "Complex feature", "reject", "sonnet", 1, 200000, 100000),
        _row("US-003", "Complex feature", "reject", "sonnet", 2, 400000, 200000),
        _row("US-003", "Complex feature", "reject", "opus", 3, 800000, 400000),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)

    assert report["summary"]["stories_with_failures"] >= 2

    # Find stories by ID
    stories_by_id = {s["story_id"]: s for s in report["stories"]}

    # US-001 should NOT appear (0 rejections)
    assert "US-001" not in stories_by_id

    # US-003 should be first (highest retry count)
    assert report["stories"][0]["story_id"] == "US-003"
    assert report["stories"][0]["retry_count"] == 4
    assert report["stories"][0]["suggestion"] == "decompose"

    # US-002 should have 2 retries
    assert "US-002" in stories_by_id
    assert stories_by_id["US-002"]["retry_count"] == 2


def test_empty_results(tmp_path: Path) -> None:
    """Empty results.tsv returns empty report."""
    tsv = tmp_path / "results.tsv"
    tsv.write_text(HEADER + "\n", encoding="utf-8")

    report = extract_failed_stories(tsv)
    assert report["stories"] == []
    assert report["summary"]["stories_with_failures"] == 0


def test_missing_file(tmp_path: Path) -> None:
    """Missing results.tsv returns empty report."""
    report = extract_failed_stories(tmp_path / "nonexistent.tsv")
    assert report["stories"] == []


def test_model_escalation_pattern(tmp_path: Path) -> None:
    """Model escalation is tracked as ordered unique models."""
    rows = [
        _row("US-010", "Escalated", "reject", "haiku", 0),
        _row("US-010", "Escalated", "reject", "sonnet", 1),
        _row("US-010", "Escalated", "reject", "opus", 2),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    entry = report["stories"][0]
    assert entry["model_escalation"] == "haiku -> sonnet -> opus"


def test_token_burns_per_attempt(tmp_path: Path) -> None:
    """Each attempt has token burn details."""
    rows = [
        _row("US-020", "Tokeny", "reject", "haiku", 0, 100000, 50000),
        _row("US-020", "Tokeny", "reject", "sonnet", 1, 200000, 100000),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    burns = report["stories"][0]["token_burns"]
    assert len(burns) == 2
    assert burns[0]["tokens"] == 150000
    assert burns[1]["tokens"] == 300000


def test_scope_suggestion_for_drift(tmp_path: Path) -> None:
    """Stories with monotonically increasing tokens get 'scope' suggestion."""
    rows = [
        _row("US-030", "Drifty", "reject", "sonnet", 0, 100000, 50000),
        _row("US-030", "Drifty", "reject", "sonnet", 1, 150000, 75000),
        _row("US-030", "Drifty", "reject", "sonnet", 2, 200000, 100000),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    assert report["stories"][0]["suggestion"] == "scope"


def test_research_suggestion_for_test_fix(tmp_path: Path) -> None:
    """UT-prefixed stories with persistent failures get 'research'."""
    rows = [
        _row("UT-040", "Test fix", "reject", "haiku", 0),
        _row("UT-040", "Test fix", "reject", "sonnet", 1),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    assert report["stories"][0]["suggestion"] == "research"


def test_markdown_output(tmp_path: Path) -> None:
    """Markdown formatting produces readable output."""
    rows = [
        _row("US-050", "Report test", "reject", "haiku", 0),
        _row("US-050", "Report test", "reject", "sonnet", 1),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    md = format_markdown(report)

    assert "# Failed Stories Triage Report" in md
    assert "US-050" in md
    assert "Report test" in md
    assert "| Retry |" in md


def test_min_retries_filter(tmp_path: Path) -> None:
    """min_retries filters out stories with fewer retries."""
    rows = [
        _row("US-060", "Low retry", "reject", "haiku", 0),
        _row("US-070", "High retry", "reject", "haiku", 0),
        _row("US-070", "High retry", "reject", "sonnet", 1),
        _row("US-070", "High retry", "reject", "opus", 2),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=3)
    assert len(report["stories"]) == 1
    assert report["stories"][0]["story_id"] == "US-070"


def test_sorted_by_retry_count_desc(tmp_path: Path) -> None:
    """Stories are sorted by retry count descending."""
    rows = [
        _row("US-080", "Two retries", "reject", "haiku", 0),
        _row("US-080", "Two retries", "reject", "sonnet", 1),
        _row("US-090", "Four retries", "reject", "haiku", 0),
        _row("US-090", "Four retries", "reject", "sonnet", 1),
        _row("US-090", "Four retries", "reject", "sonnet", 2),
        _row("US-090", "Four retries", "reject", "opus", 3),
    ]
    tsv = _write_tsv(tmp_path, rows)

    report = extract_failed_stories(tsv, min_retries=1)
    assert report["stories"][0]["story_id"] == "US-090"
    assert report["stories"][1]["story_id"] == "US-080"
