#!/usr/bin/env python3
"""
tests/test_stuck_story_analyzer.py — Unit tests for lib/stuck_story_analyzer.py

Tests verify:
- analyze_exhaustion() filters stories with 3+ attempts
- Escalation chain is built correctly from model column
- Token counts are extracted properly
- Results are sorted by attempt count descending
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from lib.stuck_story_analyzer import StuckStory, analyze_exhaustion


class TestAnalyzeExhaustion:
    """Test analyze_exhaustion() function."""

    def test_single_attempt_story_excluded(self) -> None:
        """Stories with <3 attempts should not be included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-001\tTest Story\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert len(stuck) == 0

    def test_three_attempt_story_included(self) -> None:
        """Stories with exactly 3 attempts should be included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-001\tTest Story\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-001\tTest Story\tfailed\t10\tsonnet\t1\t"
                "def456\tid2\t1000\t100\t5000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-001\tTest Story\tfailed\t10\topus\t2\t"
                "ghi789\tid3\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert len(stuck) == 1
            assert stuck[0].story_id == "US-001"
            assert stuck[0].attempt_count == 3

    def test_escalation_chain_built_correctly(self) -> None:
        """Escalation chain should be 'haiku→sonnet→opus' for 3 attempts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-005\tTest\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-005\tTest\tfailed\t10\tsonnet\t1\t"
                "def456\tid2\t1000\t100\t5000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-005\tTest\tfailed\t10\topus\t2\t"
                "ghi789\tid3\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert stuck[0].escalation_chain == "haiku→sonnet→opus"
            assert stuck[0].last_model_tried == "opus"

    def test_last_model_tried_is_correct(self) -> None:
        """last_model_tried should be the model from the last attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-010\tTest\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-010\tTest\tfailed\t10\topus\t1\t"
                "def456\tid2\t1000\t100\t5000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-010\tTest\tfailed\t10\topus\t2\t"
                "ghi789\tid3\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert stuck[0].last_model_tried == "opus"

    def test_token_count_extracted(self) -> None:
        """original_token_count should be sum of cache_read_tokens and review_tokens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-020\tTest\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-020\tTest\tfailed\t10\tsonnet\t1\t"
                "def456\tid2\t1000\t100\t5000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-020\tTest\tfailed\t10\topus\t2\t"
                "ghi789\tid3\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            # First record: 1000 + 5000 = 6000
            assert stuck[0].original_token_count == 6000

    def test_five_retry_fixture_story(self) -> None:
        """Test with 5-retry fixture story as per AC3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-999\t5-Retry Story\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t2000\t200\t8000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-999\t5-Retry Story\tfailed\t10\thaiku\t1\t"
                "def456\tid2\t2000\t200\t8000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-999\t5-Retry Story\tfailed\t10\tsonnet\t2\t"
                "ghi789\tid3\t2000\t200\t8000\n"
                "2026-01-01T00:30:00Z\t1\t4\tUS-999\t5-Retry Story\tfailed\t10\tsonnet\t3\t"
                "jkl012\tid4\t2000\t200\t8000\n"
                "2026-01-01T00:40:00Z\t1\t5\tUS-999\t5-Retry Story\tfailed\t10\topus\t4\t"
                "mno345\tid5\t2000\t200\t8000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert len(stuck) == 1
            assert stuck[0].story_id == "US-999"
            assert stuck[0].attempt_count == 5
            assert stuck[0].escalation_chain == "haiku→haiku→sonnet→sonnet→opus"
            assert stuck[0].last_model_tried == "opus"
            assert stuck[0].original_token_count == 10000

    def test_multiple_stuck_stories_sorted_by_attempts(self) -> None:
        """Multiple stuck stories should be sorted by attempt_count descending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
                "2026-01-01T00:00:00Z\t1\t1\tUS-111\tStory 1\tfailed\t10\thaiku\t0\t"
                "abc123\tid1\t1000\t100\t5000\n"
                "2026-01-01T00:10:00Z\t1\t2\tUS-111\tStory 1\tfailed\t10\tsonnet\t1\t"
                "def456\tid2\t1000\t100\t5000\n"
                "2026-01-01T00:20:00Z\t1\t3\tUS-111\tStory 1\tfailed\t10\topus\t2\t"
                "ghi789\tid3\t1000\t100\t5000\n"
                "2026-01-01T00:30:00Z\t1\t1\tUS-222\tStory 2\tfailed\t10\thaiku\t0\t"
                "abc123\tid4\t1000\t100\t5000\n"
                "2026-01-01T00:40:00Z\t1\t2\tUS-222\tStory 2\tfailed\t10\tsonnet\t1\t"
                "def456\tid5\t1000\t100\t5000\n"
                "2026-01-01T00:50:00Z\t1\t3\tUS-222\tStory 2\tfailed\t10\topus\t2\t"
                "ghi789\tid6\t1000\t100\t5000\n"
                "2026-01-01T01:00:00Z\t1\t1\tUS-333\tStory 3\tfailed\t10\thaiku\t0\t"
                "abc123\tid7\t1000\t100\t5000\n"
                "2026-01-01T01:10:00Z\t1\t2\tUS-333\tStory 3\tfailed\t10\tsonnet\t1\t"
                "def456\tid8\t1000\t100\t5000\n"
                "2026-01-01T01:20:00Z\t1\t3\tUS-333\tStory 3\tfailed\t10\topus\t2\t"
                "ghi789\tid9\t1000\t100\t5000\n"
                "2026-01-01T01:30:00Z\t1\t4\tUS-333\tStory 3\tfailed\t10\topus\t3\t"
                "mno345\tid10\t1000\t100\t5000\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert len(stuck) == 3
            # US-333 should be first (4 attempts)
            assert stuck[0].story_id == "US-333"
            assert stuck[0].attempt_count == 4
            # US-111 and US-222 should be next (3 attempts each, order may vary)
            assert all(s.attempt_count == 3 for s in stuck[1:])

    def test_nonexistent_results_file(self) -> None:
        """Should return empty list if results.tsv doesn't exist."""
        stuck = analyze_exhaustion("/nonexistent/path/results.tsv")
        assert stuck == []

    def test_empty_results_file(self) -> None:
        """Should handle empty results.tsv gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text("")

            stuck = analyze_exhaustion(str(results_path))
            assert stuck == []

    def test_results_file_with_header_only(self) -> None:
        """Should handle results.tsv with only header, no data rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = Path(tmpdir) / "results.tsv"
            results_path.write_text(
                "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
                "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_read_tokens\t"
                "cache_creation_tokens\treview_tokens\n"
            )

            stuck = analyze_exhaustion(str(results_path))
            assert stuck == []

    def test_stuck_story_dataclass_fields(self) -> None:
        """StuckStory dataclass should have all required fields."""
        stuck_story = StuckStory(
            story_id="US-TEST",
            attempt_count=3,
            last_model_tried="opus",
            escalation_chain="haiku→sonnet→opus",
            original_token_count=10000,
        )

        assert stuck_story.story_id == "US-TEST"
        assert stuck_story.attempt_count == 3
        assert stuck_story.last_model_tried == "opus"
        assert stuck_story.escalation_chain == "haiku→sonnet→opus"
        assert stuck_story.original_token_count == 10000
