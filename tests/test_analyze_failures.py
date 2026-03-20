"""Tests for lib/analyze_failures.py — Story Failure Root-Cause Analyzer (US-547)."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from analyze_failures import FailureAnalyzer, categorize_text, main

RESULTS_HEADER = [
    "timestamp",
    "story_id",
    "story_title",
    "status",
    "failure_root_cause",
]


# -- Helpers -----------------------------------------------------------------


def _make_row(
    story_id: str = "US-001",
    story_title: str = "Test story",
    status: str = "fail",
    failure_root_cause: str = "",
) -> dict[str, str]:
    return {
        "timestamp": "2026-03-20T10:00:00Z",
        "story_id": story_id,
        "story_title": story_title,
        "status": status,
        "failure_root_cause": failure_root_cause,
    }


def _write_results(path: Path, rows: list[dict[str, str]]) -> None:
    with open(str(path), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=RESULTS_HEADER, delimiter="\t", extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


# -- categorize_text ----------------------------------------------------------


def test_categorize_scope_exceeded() -> None:
    """Lines mentioning token limits are classified as scope_exceeded."""
    assert categorize_text("exceeds max_tokens limit") == "scope_exceeded"
    assert categorize_text("context_length is too long") == "scope_exceeded"
    assert categorize_text("token limit reached") == "scope_exceeded"


def test_categorize_rate_limit() -> None:
    """Lines mentioning rate limits are classified as api_rate_limit."""
    assert categorize_text("rate_limit hit, please retry") == "api_rate_limit"
    assert categorize_text("HTTP 429 too many requests") == "api_rate_limit"
    assert categorize_text("quota exceeded for billing") == "api_rate_limit"


def test_categorize_type_error() -> None:
    """TypeError / NameError / ImportError lines → type_error."""
    assert categorize_text("TypeError: unsupported operand type") == "type_error"
    assert categorize_text("NameError: name 'foo' is not defined") == "type_error"
    assert categorize_text("ImportError: cannot import name foo") == "type_error"


def test_categorize_validation_timeout() -> None:
    """Timeout-related lines → validation_timeout."""
    assert categorize_text("timed out after 60s") == "validation_timeout"
    assert categorize_text("TimeoutError: deadline exceeded") == "validation_timeout"


def test_categorize_model_capability_gap() -> None:
    """Model capability issues → model_capability_gap."""
    assert categorize_text("model is not capable of this task") == "model_capability_gap"
    assert categorize_text("unsupported model feature requested") == "model_capability_gap"


def test_categorize_unknown() -> None:
    """Lines matching no pattern return 'unknown'."""
    assert categorize_text("something went wrong") == "unknown"
    assert categorize_text("") == "unknown"


# -- FailureAnalyzer ----------------------------------------------------------


def test_empty_results_returns_empty(tmp_path: Path) -> None:
    """When results.tsv is missing and no logs exist, analysis returns empty dicts."""
    fa = FailureAnalyzer(
        repo_root=tmp_path,
        results_tsv=tmp_path / "nonexistent.tsv",
        logs_dir=tmp_path / "nonexistent_logs",
    )
    result = fa.analyze()

    assert result["by_category"] == {}
    assert result["by_phase"] == {}
    assert "No failures found" in result["recommendation"]


def test_analyzer_categorizes_from_results_tsv(tmp_path: Path) -> None:
    """Analyzer reads results.tsv and counts by failure_root_cause column."""
    tsv = tmp_path / "results.tsv"
    _write_results(
        tsv,
        [
            _make_row("US-001", "Story A", "fail", "scope_exceeded"),
            _make_row("US-002", "Story B", "fail", "api_rate_limit"),
            _make_row("US-003", "Story C", "retry", "scope_exceeded"),
            _make_row("US-004", "Story D", "keep"),  # not a failure — skipped
        ],
    )

    fa = FailureAnalyzer(
        repo_root=tmp_path,
        results_tsv=tsv,
        logs_dir=tmp_path / "no_logs",
    )
    result = fa.analyze()

    assert result["by_category"]["scope_exceeded"] == 2
    assert result["by_category"]["api_rate_limit"] == 1
    assert result["by_phase"]["fail"] == 2
    assert result["by_phase"]["retry"] == 1


def test_recommendation_when_scope_exceeded_over_30_pct(tmp_path: Path) -> None:
    """When >30% of failures are scope_exceeded, recommend SPIRAL_DECOMPOSE_THRESHOLD."""
    tsv = tmp_path / "results.tsv"
    # 4 out of 5 = 80% scope_exceeded
    _write_results(
        tsv,
        [
            _make_row("US-001", "A", "fail", "scope_exceeded"),
            _make_row("US-002", "B", "fail", "scope_exceeded"),
            _make_row("US-003", "C", "fail", "scope_exceeded"),
            _make_row("US-004", "D", "fail", "scope_exceeded"),
            _make_row("US-005", "E", "fail", "api_rate_limit"),
        ],
    )

    fa = FailureAnalyzer(
        repo_root=tmp_path,
        results_tsv=tsv,
        logs_dir=tmp_path / "no_logs",
    )
    result = fa.analyze()

    assert "SPIRAL_DECOMPOSE_THRESHOLD" in result["recommendation"]


def test_recommendation_healthy_when_evenly_distributed(tmp_path: Path) -> None:
    """When no category exceeds 30%, recommendation says distribution is healthy."""
    tsv = tmp_path / "results.tsv"
    _write_results(
        tsv,
        [
            _make_row("US-001", "A", "fail", "scope_exceeded"),
            _make_row("US-002", "B", "fail", "api_rate_limit"),
            _make_row("US-003", "C", "fail", "type_error"),
            _make_row("US-004", "D", "fail", "validation_timeout"),
        ],
    )

    fa = FailureAnalyzer(
        repo_root=tmp_path,
        results_tsv=tsv,
        logs_dir=tmp_path / "no_logs",
    )
    result = fa.analyze()

    assert "healthy" in result["recommendation"].lower() or "Dominant" in result["recommendation"]


def test_analyzer_reads_log_files(tmp_path: Path) -> None:
    """Analyzer parses phase-i-*.log files for failure categories."""
    logs_dir = tmp_path / ".spiral" / "logs"
    logs_dir.mkdir(parents=True)

    log_file = logs_dir / "phase-i-1.log"
    log_file.write_text(
        "[2026-01-01T00:00:00Z] FAILURE_ROOT_CAUSE: api_rate_limit\n"
        "  story_id=US-99 retry=1 reason=rate_limit\n",
        encoding="utf-8",
    )

    fa = FailureAnalyzer(
        repo_root=tmp_path,
        results_tsv=tmp_path / "nonexistent.tsv",
        logs_dir=logs_dir,
    )
    result = fa.analyze()

    assert result["by_category"].get("api_rate_limit", 0) >= 1


def test_json_serializable(tmp_path: Path) -> None:
    """analyze() output is JSON-serializable."""
    fa = FailureAnalyzer(repo_root=tmp_path)
    result = fa.analyze()
    json.dumps(result)  # should not raise


# -- CLI output format --------------------------------------------------------


def test_cli_output_format(tmp_path: Path) -> None:
    """CLI --format json outputs valid JSON with by_category, by_phase, recommendation."""
    tsv = tmp_path / "results.tsv"
    _write_results(
        tsv,
        [
            _make_row("US-001", "Story A", "fail", "scope_exceeded"),
            _make_row("US-002", "Story B", "fail", "api_rate_limit"),
        ],
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--format", "json", "--repo", str(tmp_path)])

    output = json.loads(buf.getvalue())

    assert "by_category" in output
    assert "by_phase" in output
    assert "recommendation" in output
    assert isinstance(output["by_category"], dict)
    assert isinstance(output["by_phase"], dict)
    assert isinstance(output["recommendation"], str)


def test_cli_text_format(tmp_path: Path) -> None:
    """CLI --format text outputs human-readable lines."""
    tsv = tmp_path / "results.tsv"
    _write_results(tsv, [_make_row("US-001", "A", "fail", "type_error")])

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--format", "text", "--repo", str(tmp_path)])

    text = buf.getvalue()
    assert "By category:" in text
    assert "By phase:" in text
    assert "Recommendation:" in text
