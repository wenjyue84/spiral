"""Integration tests for US-1113: per-attempt failure messages in retry history.

Tests verify that results.tsv failure_root_cause is accessible per-attempt for
the retry history drill-down feature in FailureRetryDashboard / StoryDetailPanel.
Run: uv run pytest tests/ -k us_1113 -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from extract_failed_stories import extract_failed_stories  # noqa: E402
from results_tsv import HEADER, ResultsRecord, parse_results_tsv, write_results_tsv  # noqa: E402

_BASE: dict[str, str] = {k: "" for k in HEADER}


def _rec(
    story_id: str,
    status: str,
    model: str,
    retry_num: int,
    failure_root_cause: str = "",
) -> ResultsRecord:
    return ResultsRecord(
        **{
            **_BASE,
            "timestamp": "2026-04-07T10:00:00Z",
            "spiral_iter": "1",
            "ralph_iter": "1",
            "story_id": story_id,
            "story_title": f"Story {story_id}",
            "status": status,
            "duration_sec": "120",
            "model": model,
            "retry_num": str(retry_num),
            "commit_sha": "abc123",
            "run_id": "run1",
            "failure_root_cause": failure_root_cause,
        }
    )


class TestRetryHistoryUS1113:
    """Integration tests for per-attempt failure messages (US-1113)."""

    def test_us_1113_happy_path_per_attempt_failure_messages(self, tmp_path: Path) -> None:
        """Happy path: multi-retry story preserves failure_root_cause per attempt."""
        records = [
            _rec("US-500", "reject", "haiku", 0, "syntax_error: unexpected indent"),
            _rec("US-500", "reject", "sonnet", 1, "test_assertion: expected 200 got 404"),
            _rec("US-500", "keep", "opus", 2, ""),
        ]
        tsv_path = tmp_path / "results.tsv"
        write_results_tsv(str(tsv_path), records)

        parsed = parse_results_tsv(str(tsv_path))
        us500 = [r for r in parsed if r.story_id == "US-500"]

        assert len(us500) == 3, "All 3 attempts should be parsed"
        assert us500[0].failure_root_cause == "syntax_error: unexpected indent"
        assert us500[1].failure_root_cause == "test_assertion: expected 200 got 404"
        assert us500[2].failure_root_cause == "", "Passed attempt has no failure message"

    def test_us_1113_failure_reasons_collected_from_attempts(self, tmp_path: Path) -> None:
        """extract_failed_stories collects failure messages across retry attempts."""
        records = [
            _rec("US-600", "reject", "haiku", 0, "scope_overrun: diff too large"),
            _rec("US-600", "reject", "sonnet", 1, "type_error: NoneType has no attribute"),
        ]
        tsv_path = tmp_path / "results.tsv"
        write_results_tsv(str(tsv_path), records)

        report = extract_failed_stories(str(tsv_path), min_retries=1)
        story = next(s for s in report["stories"] if s["story_id"] == "US-600")

        assert len(story["failure_reasons"]) == 2
        assert any("scope_overrun" in r for r in story["failure_reasons"])
        assert any("type_error" in r for r in story["failure_reasons"])

    def test_us_1113_empty_failure_root_cause_no_crash(self, tmp_path: Path) -> None:
        """Edge case: empty failure_root_cause values don't crash the pipeline."""
        records = [
            _rec("US-700", "reject", "haiku", 0, ""),
            _rec("US-700", "reject", "sonnet", 1, ""),
        ]
        tsv_path = tmp_path / "results.tsv"
        write_results_tsv(str(tsv_path), records)

        report = extract_failed_stories(str(tsv_path), min_retries=1)
        story = next(s for s in report["stories"] if s["story_id"] == "US-700")

        assert story["retry_count"] == 2
        assert story["failure_reasons"] == [], "Empty failure messages produce empty list"
