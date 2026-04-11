"""
tests/test_explain_retry.py — Integration tests for explain-retry CLI (US-728).

Tests spiral explain-retry US-123:
  1. Retry sequence JSON output with correct fields for haiku→sonnet→opus escalation.
  2. Decomposition suggestion accuracy from failed_files column.
  3. Edge cases: missing story, empty failed_files, single-attempt story.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add lib/ to path so imports work without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from commands.explain_retry import (
    explain_retry_sequence,
    suggest_decomposition,
)

# ── TSV helper ────────────────────────────────────────────────────────────────

_HEADER = [
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
    "votes_accept",
    "votes_reject",
    "conflict_files",
    "failure_root_cause",
    "sub_project",
    "failed_files",
]


def _write_tsv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a minimal results.tsv with given rows and return its path."""
    tsv_path = tmp_path / "results.tsv"
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("\t".join(_HEADER) + "\n")
        for row in rows:
            f.write("\t".join(row.get(h, "") for h in _HEADER) + "\n")
    return tsv_path


# ── Tests for explain_retry_sequence() ────────────────────────────────────────


class TestExplainRetrySequence:
    def test_three_attempt_haiku_sonnet_opus(self, tmp_path: Path) -> None:
        """3-attempt haiku→sonnet→opus escalation produces correct retry sequence."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T01:00:00Z",
                    "story_id": "US-123",
                    "story_title": "Big Feature",
                    "status": "failed",
                    "duration_sec": "320",
                    "model": "haiku",
                    "retry_num": "1",
                    "cache_read_tokens": "4000",
                    "cache_creation_tokens": "800",
                    "review_tokens": "200",
                    "failure_root_cause": "diff guard exceeded 400 lines",
                },
                {
                    "timestamp": "2026-03-22T01:10:00Z",
                    "story_id": "US-123",
                    "story_title": "Big Feature",
                    "status": "failed",
                    "duration_sec": "410",
                    "model": "sonnet",
                    "retry_num": "2",
                    "cache_read_tokens": "9000",
                    "cache_creation_tokens": "1000",
                    "review_tokens": "500",
                    "failure_root_cause": "timed out after 420s",
                },
                {
                    "timestamp": "2026-03-22T01:25:00Z",
                    "story_id": "US-123",
                    "story_title": "Big Feature",
                    "status": "reject",
                    "duration_sec": "560",
                    "model": "opus",
                    "retry_num": "3",
                    "cache_read_tokens": "18000",
                    "cache_creation_tokens": "2000",
                    "review_tokens": "1000",
                    "failure_root_cause": "",
                },
            ],
        )

        result = explain_retry_sequence("US-123", tsv)

        assert len(result) == 3, f"Expected 3 attempts, got {len(result)}"

        # Attempt 1 — haiku, scope_overrun (diff guard pattern)
        a1 = result[0]
        assert a1["attempt"] == 1
        assert a1["model"] == "haiku"
        assert a1["tokens"] == 5000  # 4000 + 800 + 200
        assert a1["duration_sec"] == 320.0
        assert a1["status"] == "failed"
        assert a1["error_category"] == "scope_overrun"

        # Attempt 2 — sonnet, timeout
        a2 = result[1]
        assert a2["attempt"] == 2
        assert a2["model"] == "sonnet"
        assert a2["tokens"] == 10500  # 9000 + 1000 + 500
        assert a2["duration_sec"] == 410.0
        assert a2["status"] == "failed"
        assert a2["error_category"] == "timeout"

        # Attempt 3 — opus, other (no root cause text)
        a3 = result[2]
        assert a3["attempt"] == 3
        assert a3["model"] == "opus"
        assert a3["tokens"] == 21000  # 18000 + 2000 + 1000
        assert a3["duration_sec"] == 560.0
        assert a3["status"] == "reject"

    def test_required_fields_present(self, tmp_path: Path) -> None:
        """Every attempt dict contains all 6 required fields."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T02:00:00Z",
                    "story_id": "US-200",
                    "story_title": "Sample",
                    "status": "failed",
                    "duration_sec": "100",
                    "model": "haiku",
                    "retry_num": "1",
                },
            ],
        )
        result = explain_retry_sequence("US-200", tsv)
        assert len(result) == 1
        record = result[0]
        for field in ("attempt", "model", "tokens", "duration_sec", "status", "error_category"):
            assert field in record, f"Missing required field: {field}"

    def test_missing_story_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when story_id is not found."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T03:00:00Z",
                    "story_id": "US-999",
                    "story_title": "Other Story",
                    "status": "pass",
                    "duration_sec": "120",
                    "model": "haiku",
                    "retry_num": "1",
                },
            ],
        )
        result = explain_retry_sequence("US-123", tsv)
        assert result == []

    def test_scope_overrun_heuristic_haiku_high_duration(self, tmp_path: Path) -> None:
        """Haiku attempt with >300s duration and no root cause text → scope_overrun."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T04:00:00Z",
                    "story_id": "US-500",
                    "story_title": "Large refactor",
                    "status": "reject",
                    "duration_sec": "350",
                    "model": "haiku",
                    "retry_num": "1",
                    "failure_root_cause": "",
                },
            ],
        )
        result = explain_retry_sequence("US-500", tsv)
        assert len(result) == 1
        assert result[0]["error_category"] == "scope_overrun"


# ── Tests for suggest_decomposition() ─────────────────────────────────────────


class TestSuggestDecomposition:
    def test_decomposition_from_distinct_directories(self, tmp_path: Path) -> None:
        """Files from 2 distinct top-level dirs → US-NNNA / US-NNNB suggestion."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T05:00:00Z",
                    "story_id": "US-300",
                    "story_title": "Big Story",
                    "status": "failed",
                    "duration_sec": "350",
                    "model": "haiku",
                    "retry_num": "1",
                    "failed_files": json.dumps(["lib/a.py", "lib/b.py"]),
                },
                {
                    "timestamp": "2026-03-22T05:10:00Z",
                    "story_id": "US-300",
                    "story_title": "Big Story",
                    "status": "reject",
                    "duration_sec": "420",
                    "model": "sonnet",
                    "retry_num": "2",
                    "failed_files": json.dumps(["tests/test_c.py", "tests/test_d.py"]),
                },
            ],
        )
        suggestion = suggest_decomposition("US-300", tsv)
        assert suggestion is not None, "Expected a decomposition suggestion"
        assert "US-300A" in suggestion
        assert "US-300B" in suggestion
        # Must reference the two directories
        assert "lib" in suggestion
        assert "tests" in suggestion

    def test_decomposition_suggestion_format(self, tmp_path: Path) -> None:
        """Suggestion format: 'Split into 2 stories: <id>A (...) and <id>B (...)'."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T06:00:00Z",
                    "story_id": "US-400",
                    "story_title": "Story",
                    "status": "failed",
                    "duration_sec": "300",
                    "model": "haiku",
                    "retry_num": "1",
                    "failed_files": json.dumps(["src/core.py", "src/utils.py"]),
                },
                {
                    "timestamp": "2026-03-22T06:10:00Z",
                    "story_id": "US-400",
                    "story_title": "Story",
                    "status": "reject",
                    "duration_sec": "400",
                    "model": "sonnet",
                    "retry_num": "2",
                    "failed_files": json.dumps(["docs/api.md", "docs/guide.md"]),
                },
            ],
        )
        suggestion = suggest_decomposition("US-400", tsv)
        assert suggestion is not None
        assert suggestion.startswith("Split into 2 stories:")
        assert "US-400A" in suggestion
        assert "US-400B" in suggestion

    def test_no_suggestion_when_failed_files_empty(self, tmp_path: Path) -> None:
        """Returns None when all failed_files columns are empty."""
        tsv = _write_tsv(
            tmp_path,
            [
                {
                    "timestamp": "2026-03-22T07:00:00Z",
                    "story_id": "US-500",
                    "story_title": "Clean Story",
                    "status": "failed",
                    "duration_sec": "120",
                    "model": "haiku",
                    "retry_num": "1",
                    "failed_files": "",
                },
            ],
        )
        result = suggest_decomposition("US-500", tsv)
        assert result is None

    def test_no_suggestion_for_missing_story(self, tmp_path: Path) -> None:
        """Returns None when story_id not in results.tsv."""
        tsv = _write_tsv(tmp_path, [])
        result = suggest_decomposition("US-999", tsv)
        assert result is None


# ── Regression test for US-728 (CLI command) ──────────────────────────────────


def test_us_728_regression(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Regression test for US-728: CLI command spiral explain-retry <story_id>.

    Verifies core observable behavior:
      1. JSON retry sequence output with correct fields
      2. Decomposition suggestion when failed_files data exists
      3. Exit code behavior
      4. Error message when story not found

    This test would fail if the US-728 feature were removed or broken.
    """
    import argparse

    # Import cmd_explain_retry from main.py (where it's actually defined)
    spiral_root = Path(__file__).parent.parent
    sys.path.insert(0, str(spiral_root))
    import main

    cmd_explain_retry = main.cmd_explain_retry

    # Setup: Create a realistic results.tsv with a multi-attempt story
    tsv = _write_tsv(
        tmp_path,
        [
            {
                "timestamp": "2026-04-10T10:00:00Z",
                "story_id": "US-728",
                "story_title": "Add explain-retry command",
                "status": "failed",
                "duration_sec": "350",
                "model": "haiku",
                "retry_num": "1",
                "cache_read_tokens": "5000",
                "cache_creation_tokens": "1000",
                "review_tokens": "300",
                "failure_root_cause": "diff guard exceeded 400 lines",
                "failed_files": json.dumps(["lib/commands/explain_retry.py", "lib/failure_categorizer.py"]),
            },
            {
                "timestamp": "2026-04-10T10:15:00Z",
                "story_id": "US-728",
                "story_title": "Add explain-retry command",
                "status": "pass",
                "duration_sec": "280",
                "model": "sonnet",
                "retry_num": "2",
                "cache_read_tokens": "12000",
                "cache_creation_tokens": "2000",
                "review_tokens": "500",
                "failed_files": json.dumps(["tests/test_explain_retry.py"]),
            },
        ],
    )

    # Test 1: Command with decomposition (default)
    args = argparse.Namespace(
        story_id="US-728",
        results=str(tsv),
        no_decompose=False,
        command="explain-retry",
    )

    try:
        cmd_explain_retry(args)
    except SystemExit as e:
        # Expect sys.exit(0) on success
        assert e.code == 0, f"Expected exit code 0, got {e.code}"

    captured = capsys.readouterr()

    # Extract JSON from output
    # The JSON is the first part (before any non-JSON text like "Decomposition:")
    output = captured.out.strip()

    # Find the JSON portion by looking for [ ... ]
    json_start = output.find("[")
    json_end = output.rfind("]") + 1

    assert json_start != -1, f"No JSON array found in output: {output}"

    json_text = output[json_start:json_end]
    sequence = json.loads(json_text)

    # Verify retry sequence structure
    assert isinstance(sequence, list), "Output should be a JSON array"
    assert len(sequence) == 2, f"Expected 2 attempts, got {len(sequence)}"

    # Verify first attempt (haiku, scope_overrun)
    attempt1 = sequence[0]
    assert attempt1["attempt"] == 1
    assert attempt1["model"] == "haiku"
    assert attempt1["tokens"] == 6300  # 5000 + 1000 + 300
    assert attempt1["duration_sec"] == 350.0
    assert attempt1["status"] == "failed"
    assert attempt1["error_category"] == "scope_overrun"

    # Verify second attempt (sonnet, pass)
    attempt2 = sequence[1]
    assert attempt2["attempt"] == 2
    assert attempt2["model"] == "sonnet"
    assert attempt2["tokens"] == 14500  # 12000 + 2000 + 500
    assert attempt2["duration_sec"] == 280.0
    assert attempt2["status"] == "pass"

    # Verify decomposition suggestion is printed
    assert "Decomposition:" in captured.out, "Decomposition suggestion should be present"
    assert "US-728A" in captured.out and "US-728B" in captured.out, "Suggestion should contain US-728A and US-728B"

    # Test 2: Command with --no-decompose flag
    args_no_decompose = argparse.Namespace(
        story_id="US-728",
        results=str(tsv),
        no_decompose=True,
        command="explain-retry",
    )

    # Capture output with no decomposition
    capsys.readouterr()  # Clear previous capture
    try:
        cmd_explain_retry(args_no_decompose)
    except SystemExit as e:
        assert e.code == 0

    captured_no_decomp = capsys.readouterr()

    # JSON should be present
    assert "[" in captured_no_decomp.out and "]" in captured_no_decomp.out, (
        "JSON output should be present even with --no-decompose"
    )

    # Decomposition should NOT be in output
    assert "Decomposition:" not in captured_no_decomp.out, "Decomposition should not appear with --no-decompose flag"

    # Test 3: Error case — story not found
    args_missing = argparse.Namespace(
        story_id="US-999",
        results=str(tsv),
        no_decompose=False,
        command="explain-retry",
    )

    capsys.readouterr()  # Clear previous capture
    try:
        cmd_explain_retry(args_missing)
    except SystemExit as e:
        # Expect sys.exit(1) on missing story
        assert e.code == 1, f"Expected exit code 1 for missing story, got {e.code}"

    captured_error = capsys.readouterr()
    # Error message should be on stderr
    assert "No retry records found" in captured_error.err, "Error message should indicate story not found"
