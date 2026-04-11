"""tests/test_explain_retry_us728.py — Regression tests for US-728.

US-728: spiral explain-retry <story_id> — Analyze retry sequence and suggest decomposition
- Reads results.tsv for a given story_id
- Shows full retry sequence (model escalations, durations, error messages)
- Analyzes error patterns and suggests atomic sub-story decomposition
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from commands.explain_retry import explain_retry_sequence, suggest_decomposition
from results_tsv import HEADER


def _make_results_tsv(records: list[dict[str, Any]]) -> Path:
    """Create a temporary results.tsv file with the given records."""
    tsv_file = Path(tempfile.mktemp(suffix=".tsv"))
    with open(tsv_file, "w") as f:
        f.write("\t".join(HEADER) + "\n")
        for record in records:
            values = [str(record.get(field, "")) for field in HEADER]
            f.write("\t".join(values) + "\n")
    return tsv_file


class TestUS728ExplainRetrySequence:
    """Verify explain_retry_sequence() extracts full retry sequence from results.tsv."""

    def test_us_728_sequence_returns_empty_when_story_not_found(self) -> None:
        """Should return empty list when story_id not in results.tsv."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-100",
                    "story_title": "Test Story",
                    "status": "pass",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                }
            ]
        )
        result = explain_retry_sequence("US-999", tsv_file)
        assert result == []
        tsv_file.unlink()

    def test_us_728_sequence_returns_single_attempt(self) -> None:
        """Should return single-element list for story with one attempt."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-123",
                    "story_title": "Test Story",
                    "status": "pass",
                    "duration_sec": "10.5",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "cache_read_tokens": "100",
                    "cache_creation_tokens": "200",
                    "review_tokens": "50",
                }
            ]
        )
        result = explain_retry_sequence("US-123", tsv_file)
        assert len(result) == 1
        assert result[0]["attempt"] == 1
        assert result[0]["model"] == "haiku"
        assert result[0]["tokens"] == 350
        assert result[0]["duration_sec"] == 10.5
        assert result[0]["status"] == "pass"
        tsv_file.unlink()

    def test_us_728_sequence_with_model_escalation(self) -> None:
        """Should show retry sequence: haiku -> sonnet -> opus."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-200",
                    "story_title": "Complex Story",
                    "status": "failed",
                    "duration_sec": "15.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failure_root_cause": "token limit exceeded",
                },
                {
                    "timestamp": "2026-04-11T10:01:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "2",
                    "story_id": "US-200",
                    "story_title": "Complex Story",
                    "status": "failed",
                    "duration_sec": "20.0",
                    "model": "sonnet",
                    "retry_num": "1",
                    "commit_sha": "def456",
                    "run_id": "run-1",
                    "failure_root_cause": "type error",
                },
                {
                    "timestamp": "2026-04-11T10:02:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "3",
                    "story_id": "US-200",
                    "story_title": "Complex Story",
                    "status": "pass",
                    "duration_sec": "25.0",
                    "model": "opus",
                    "retry_num": "2",
                    "commit_sha": "ghi789",
                    "run_id": "run-1",
                },
            ]
        )
        result = explain_retry_sequence("US-200", tsv_file)
        assert len(result) == 3
        assert result[0]["model"] == "haiku"
        assert result[1]["model"] == "sonnet"
        assert result[2]["model"] == "opus"
        assert result[0]["status"] == "failed"
        assert result[2]["status"] == "pass"
        tsv_file.unlink()

    def test_us_728_sequence_sorts_by_retry_num(self) -> None:
        """Should sort deterministically by retry_num, not insertion order."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:02:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "3",
                    "story_id": "US-300",
                    "story_title": "Test",
                    "status": "pass",
                    "duration_sec": "5.0",
                    "model": "opus",
                    "retry_num": "2",
                    "commit_sha": "ghi789",
                    "run_id": "run-1",
                },
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-300",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                },
            ]
        )
        result = explain_retry_sequence("US-300", tsv_file)
        assert result[0]["model"] == "haiku"
        assert result[1]["model"] == "opus"
        tsv_file.unlink()

    def test_us_728_sequence_includes_error_category(self) -> None:
        """Should classify errors into categories."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-400",
                    "story_title": "Large Story",
                    "status": "failed",
                    "duration_sec": "350.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failure_root_cause": "scope overrun: too many files",
                }
            ]
        )
        result = explain_retry_sequence("US-400", tsv_file)
        assert len(result) == 1
        assert result[0]["error_category"] == "scope_overrun"
        tsv_file.unlink()


class TestUS728DecompositionSuggestion:
    """Verify suggest_decomposition() generates sensible story splits."""

    def test_us_728_decompose_returns_none_when_no_failed_files(self) -> None:
        """Should return None when failed_files is empty."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-500",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": "",
                }
            ]
        )
        result = suggest_decomposition("US-500", tsv_file)
        assert result is None
        tsv_file.unlink()

    def test_us_728_decompose_groups_by_directory(self) -> None:
        """Should group failed files by top-level directory."""
        failed_files_json = json.dumps(["lib/a.py", "lib/b.py", "tests/test_x.py"])
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-600",
                    "story_title": "Multi-dir Story",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": failed_files_json,
                }
            ]
        )
        result = suggest_decomposition("US-600", tsv_file)
        assert result is not None
        assert "US-600A" in result
        assert "US-600B" in result
        assert "lib" in result
        assert "tests" in result
        tsv_file.unlink()

    def test_us_728_decompose_deduplicates_files(self) -> None:
        """Should deduplicate failed files across multiple retry attempts."""
        failed_files_a = json.dumps(["lib/a.py", "lib/b.py"])
        failed_files_b = json.dumps(["lib/a.py", "lib/c.py"])
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-700",
                    "story_title": "Retry Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": failed_files_a,
                },
                {
                    "timestamp": "2026-04-11T10:01:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "2",
                    "story_id": "US-700",
                    "story_title": "Retry Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "sonnet",
                    "retry_num": "1",
                    "commit_sha": "def456",
                    "run_id": "run-1",
                    "failed_files": failed_files_b,
                },
            ]
        )
        result = suggest_decomposition("US-700", tsv_file)
        assert result is not None
        assert "US-700A" in result
        assert "US-700B" in result
        tsv_file.unlink()

    def test_us_728_decompose_returns_none_for_single_file(self) -> None:
        """Should return None if only one file failed."""
        failed_files = json.dumps(["lib/single.py"])
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-800",
                    "story_title": "Single File",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": failed_files,
                }
            ]
        )
        result = suggest_decomposition("US-800", tsv_file)
        assert result is None
        tsv_file.unlink()


class TestUS728ErrorCategorization:
    """Verify error_category classification for common failure patterns."""

    def test_us_728_categorize_scope_overrun_regex(self) -> None:
        """Should detect scope overrun from failure message."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-900",
                    "story_title": "Scope Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failure_root_cause": "diff guard: too many files (42 > 8)",
                }
            ]
        )
        result = explain_retry_sequence("US-900", tsv_file)
        assert result[0]["error_category"] == "scope_overrun"
        tsv_file.unlink()

    def test_us_728_categorize_high_duration_heuristic(self) -> None:
        """Should infer scope_overrun from high duration + haiku + retry 1."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "2",
                    "story_id": "US-910",
                    "story_title": "Large Story",
                    "status": "failed",
                    "duration_sec": "350.0",
                    "model": "haiku",
                    "retry_num": "1",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failure_root_cause": "",
                }
            ]
        )
        result = explain_retry_sequence("US-910", tsv_file)
        assert result[0]["error_category"] == "scope_overrun"
        tsv_file.unlink()

    def test_us_728_categorize_context_overflow(self) -> None:
        """Should detect context overflow errors."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-920",
                    "story_title": "Token Test",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failure_root_cause": "context window exceeded: 150000 > 100000",
                }
            ]
        )
        result = explain_retry_sequence("US-920", tsv_file)
        assert result[0]["error_category"] == "context_overflow"
        tsv_file.unlink()


class TestUS728EdgeCases:
    """Verify robustness with malformed or missing data."""

    def test_us_728_handles_missing_tokens_gracefully(self) -> None:
        """Should default to 0 for missing token fields."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-930",
                    "story_title": "Missing Tokens",
                    "status": "pass",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "cache_read_tokens": "",
                    "cache_creation_tokens": "",
                    "review_tokens": "",
                }
            ]
        )
        result = explain_retry_sequence("US-930", tsv_file)
        assert result[0]["tokens"] == 0
        tsv_file.unlink()

    def test_us_728_handles_invalid_failed_files_json(self) -> None:
        """Should gracefully skip invalid JSON in failed_files."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-940",
                    "story_title": "Bad JSON",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": "not-valid-json",
                }
            ]
        )
        result = suggest_decomposition("US-940", tsv_file)
        assert result is None
        tsv_file.unlink()

    def test_us_728_handles_failed_files_non_list(self) -> None:
        """Should skip failed_files if it is not a JSON list."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-950",
                    "story_title": "Non-list JSON",
                    "status": "failed",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                    "failed_files": "{}",
                }
            ]
        )
        result = suggest_decomposition("US-950", tsv_file)
        assert result is None
        tsv_file.unlink()

    def test_us_728_sequence_handles_missing_story_title(self) -> None:
        """Should handle empty story_title gracefully."""
        tsv_file = _make_results_tsv(
            [
                {
                    "timestamp": "2026-04-11T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-960",
                    "story_title": "",
                    "status": "pass",
                    "duration_sec": "5.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run-1",
                }
            ]
        )
        result = explain_retry_sequence("US-960", tsv_file)
        assert len(result) == 1
        assert "error_category" in result[0]
        tsv_file.unlink()
