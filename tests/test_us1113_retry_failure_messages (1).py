"""tests/test_us1113_retry_failure_messages.py — Integration tests for US-1113.

Tests that per-attempt failure_root_cause messages are correctly captured in
retry history data produced by extract_failed_stories (backing the drill-down UI).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from extract_failed_stories import extract_failed_stories  # noqa: E402

# TSV header matching the actual results.tsv schema (includes failure_root_cause)
_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
    "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\tfailure_root_cause"
)


def _row(
    story_id: str,
    status: str,
    model: str,
    retry_num: int,
    failure_root_cause: str = "",
) -> str:
    return (
        f"2026-01-01T00:00:00Z\t1\t1\t{story_id}\tTest Story\t{status}\t"
        f"60\t{model}\t{retry_num}\tabc123\trun1\ttrue\t"
        f"100000\t50000\t0\t0\t0\t0\t0\tbatch1\t{failure_root_cause}"
    )


@pytest.fixture()
def tsv_with_failure_causes(tmp_path: Path) -> Path:
    """Three-attempt retry: haiku→sonnet fail with messages, opus pass."""
    rows = [
        _HEADER,
        _row("US-400", "reject", "haiku", 0, "syntax_error: unexpected token"),
        _row("US-400", "reject", "sonnet", 1, "test_assertion: expected True got False"),
        _row("US-400", "keep", "opus", 2, ""),
    ]
    tsv = tmp_path / "results.tsv"
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return tsv


class TestUS1113PerAttemptFailureMessages:
    """Integration tests: per-attempt failure messages appear in retry history."""

    def test_us_1113_failure_messages_captured_per_attempt(self, tsv_with_failure_causes: Path) -> None:
        """Happy path: failure_root_cause from each reject is included in report."""
        report = extract_failed_stories(tsv_with_failure_causes, min_retries=1)
        assert len(report["stories"]) == 1
        entry = report["stories"][0]
        assert entry["story_id"] == "US-400"
        reasons = entry["failure_reasons"]
        assert any("syntax_error" in r for r in reasons)
        assert any("test_assertion" in r for r in reasons)

    def test_us_1113_model_sequence_matches_attempts(self, tsv_with_failure_causes: Path) -> None:
        """Happy path: model escalation haiku→sonnet→opus is captured."""
        report = extract_failed_stories(tsv_with_failure_causes, min_retries=1)
        escalation = report["stories"][0]["model_escalation"]
        assert "haiku" in escalation
        assert "sonnet" in escalation
        assert "opus" in escalation

    def test_us_1113_empty_failure_cause_excluded(self, tmp_path: Path) -> None:
        """Edge case: empty failure_root_cause strings are excluded, no crash."""
        rows = [
            _HEADER,
            _row("US-500", "reject", "haiku", 0, ""),
            _row("US-500", "reject", "sonnet", 1, ""),
        ]
        tsv = tmp_path / "results.tsv"
        tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")
        report = extract_failed_stories(tsv, min_retries=1)
        assert len(report["stories"]) == 1
        assert report["stories"][0]["failure_reasons"] == []

    def test_us_1113_missing_column_no_crash(self, tmp_path: Path) -> None:
        """Edge case: TSV without failure_root_cause column does not crash."""
        header_no_cause = (
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
            "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
            "cache_read_tokens\tcache_creation_tokens\treview_tokens\twall_seconds\t"
            "user_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id"
        )
        data_row = (
            "2026-01-01T00:00:00Z\t1\t1\tUS-600\tTest Story\treject\t"
            "60\thaiku\t0\tabc123\trun1\ttrue\t"
            "100000\t50000\t0\t0\t0\t0\t0\tbatch1"
        )
        tsv = tmp_path / "results.tsv"
        tsv.write_text(header_no_cause + "\n" + data_row + "\n", encoding="utf-8")
        report = extract_failed_stories(tsv, min_retries=1)
        assert len(report["stories"]) == 1
        assert report["stories"][0]["failure_reasons"] == []
