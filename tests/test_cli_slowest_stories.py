#!/usr/bin/env python3
"""
tests/test_cli_slowest_stories.py — Tests for show-slowest-stories CLI command (US-712).

Validates:
1. Command reads results.tsv and sums duration_sec per story_id across all phases
2. Outputs sorted table: story_id, total_duration_sec, phase_breakdown (iteration with longest duration)
3. Test validates top 5 slowest stories are correctly ranked and includes Phase I as expected bottleneck
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib/commands to path for importing show_slowest_stories
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "commands"))
from show_slowest_stories import (
    StoryDuration,
    aggregate_by_story,
    compute_slowest_stories,
    format_slowest_stories,
    load_results_tsv,
    show_slowest_stories,
)


class TestLoadResultsTsv:
    """Tests for load_results_tsv()."""

    def test_load_empty_file(self) -> None:
        """Test loading an empty TSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("timestamp\tspiral_iter\tstory_id\tduration_sec\n")
            path = f.name

        try:
            rows = load_results_tsv(path)
            assert rows == []
        finally:
            Path(path).unlink()

    def test_load_single_row(self) -> None:
        """Test loading a single row."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("timestamp\tspiral_iter\tstory_id\tduration_sec\n")
            f.write("2026-03-20T00:00:00Z\t1\tUS-001\t100\n")
            path = f.name

        try:
            rows = load_results_tsv(path)
            assert len(rows) == 1
            assert rows[0]["story_id"] == "US-001"
            assert rows[0]["duration_sec"] == "100"
        finally:
            Path(path).unlink()

    def test_load_nonexistent_file(self) -> None:
        """Test loading a file that doesn't exist."""
        rows = load_results_tsv("/nonexistent/path/results.tsv")
        assert rows == []

    def test_load_multiple_rows(self) -> None:
        """Test loading multiple rows."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("timestamp\tspiral_iter\tstory_id\tduration_sec\n")
            f.write("2026-03-20T00:00:00Z\t1\tUS-001\t100\n")
            f.write("2026-03-20T00:01:00Z\t1\tUS-002\t200\n")
            f.write("2026-03-20T00:02:00Z\t2\tUS-001\t150\n")
            path = f.name

        try:
            rows = load_results_tsv(path)
            assert len(rows) == 3
            assert rows[0]["story_id"] == "US-001"
            assert rows[1]["story_id"] == "US-002"
            assert rows[2]["story_id"] == "US-001"
        finally:
            Path(path).unlink()


class TestAggregateByStory:
    """Tests for aggregate_by_story()."""

    def test_aggregate_empty_list(self) -> None:
        """Test aggregating an empty list."""
        result = aggregate_by_story([])
        assert result == {}

    def test_aggregate_single_story_single_iteration(self) -> None:
        """Test aggregating a single story with one iteration."""
        rows = [
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "100",
            }
        ]
        result = aggregate_by_story(rows)

        assert "US-001" in result
        assert result["US-001"]["total_duration_sec"] == 100.0
        assert result["US-001"]["story_title"] == "Test Story"
        assert result["US-001"]["durations"] == [100.0]

    def test_aggregate_single_story_multiple_iterations(self) -> None:
        """Test aggregating a single story across multiple iterations."""
        rows = [
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "100",
            },
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "200",
            },
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "150",
            },
        ]
        result = aggregate_by_story(rows)

        assert "US-001" in result
        assert result["US-001"]["total_duration_sec"] == 450.0
        assert result["US-001"]["durations"] == [100.0, 200.0, 150.0]

    def test_aggregate_multiple_stories(self) -> None:
        """Test aggregating multiple stories."""
        rows = [
            {
                "story_id": "US-001",
                "story_title": "Story 1",
                "duration_sec": "100",
            },
            {
                "story_id": "US-002",
                "story_title": "Story 2",
                "duration_sec": "200",
            },
            {
                "story_id": "US-001",
                "story_title": "Story 1",
                "duration_sec": "50",
            },
        ]
        result = aggregate_by_story(rows)

        assert len(result) == 2
        assert result["US-001"]["total_duration_sec"] == 150.0
        assert result["US-002"]["total_duration_sec"] == 200.0

    def test_aggregate_ignores_invalid_duration(self) -> None:
        """Test that invalid duration values default to 0."""
        rows = [
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "invalid",
            },
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "100",
            },
        ]
        result = aggregate_by_story(rows)

        assert result["US-001"]["total_duration_sec"] == 100.0
        assert result["US-001"]["durations"] == [0.0, 100.0]

    def test_aggregate_handles_missing_fields(self) -> None:
        """Test that missing duration_sec defaults to 0."""
        rows = [
            {"story_id": "US-001", "story_title": "Test Story"},
            {
                "story_id": "US-001",
                "story_title": "Test Story",
                "duration_sec": "100",
            },
        ]
        result = aggregate_by_story(rows)

        assert result["US-001"]["total_duration_sec"] == 100.0


class TestComputeSlowestStories:
    """Tests for compute_slowest_stories()."""

    def test_compute_empty_aggregation(self) -> None:
        """Test computing from empty aggregation."""
        result = compute_slowest_stories({})
        assert result == []

    def test_compute_single_story(self) -> None:
        """Test computing with a single story."""
        aggregated = {
            "US-001": {
                "story_title": "Test Story",
                "total_duration_sec": 100.0,
                "durations": [100.0],
            }
        }
        result = compute_slowest_stories(aggregated)

        assert len(result) == 1
        assert result[0].story_id == "US-001"
        assert result[0].total_duration_sec == 100.0
        assert result[0].max_iteration_duration == 100.0
        assert result[0].max_duration_iteration == 1

    def test_compute_sorts_by_total_duration_descending(self) -> None:
        """Test that stories are sorted by total duration descending."""
        aggregated = {
            "US-001": {
                "story_title": "Story 1",
                "total_duration_sec": 300.0,
                "durations": [300.0],
            },
            "US-002": {
                "story_title": "Story 2",
                "total_duration_sec": 100.0,
                "durations": [100.0],
            },
            "US-003": {
                "story_title": "Story 3",
                "total_duration_sec": 200.0,
                "durations": [200.0],
            },
        }
        result = compute_slowest_stories(aggregated)

        assert len(result) == 3
        assert result[0].story_id == "US-001"
        assert result[0].total_duration_sec == 300.0
        assert result[1].story_id == "US-003"
        assert result[2].story_id == "US-002"

    def test_compute_max_iteration_tracking(self) -> None:
        """Test that max iteration duration is correctly tracked."""
        aggregated = {
            "US-001": {
                "story_title": "Test Story",
                "total_duration_sec": 450.0,
                "durations": [100.0, 200.0, 150.0],
            }
        }
        result = compute_slowest_stories(aggregated)

        assert result[0].max_duration_iteration == 2  # Index 1 + 1
        assert result[0].max_iteration_duration == 200.0

    def test_compute_handles_zero_durations(self) -> None:
        """Test handling of zero durations."""
        aggregated = {
            "US-001": {
                "story_title": "Test Story",
                "total_duration_sec": 0.0,
                "durations": [0.0],
            }
        }
        result = compute_slowest_stories(aggregated)

        assert len(result) == 1
        assert result[0].max_iteration_duration == 0.0


class TestFormatSlowestStories:
    """Tests for format_slowest_stories()."""

    def test_format_empty_list(self) -> None:
        """Test formatting an empty list."""
        result = format_slowest_stories([])
        assert "Story ID" in result
        assert "-" in result

    def test_format_single_story(self) -> None:
        """Test formatting a single story."""
        stories = [
            StoryDuration(
                story_id="US-001",
                story_title="Test Story",
                total_duration_sec=100.0,
                max_duration_iteration=1,
                max_iteration_duration=100.0,
            )
        ]
        result = format_slowest_stories(stories)

        assert "US-001" in result
        assert "100.0s" in result

    def test_format_respects_limit(self) -> None:
        """Test that format respects the limit parameter."""
        stories = [
            StoryDuration(
                story_id=f"US-{i:03d}",
                story_title=f"Story {i}",
                total_duration_sec=float(500 - i * 50),
                max_duration_iteration=1,
                max_iteration_duration=float(500 - i * 50),
            )
            for i in range(10)
        ]
        result = format_slowest_stories(stories, limit=5)

        assert "US-000" in result
        assert "US-004" in result
        assert "US-005" not in result or result.count("Story") <= 6  # header + 5 rows

    def test_format_includes_header(self) -> None:
        """Test that format includes the header row."""
        stories = [
            StoryDuration(
                story_id="US-001",
                story_title="Test",
                total_duration_sec=100.0,
                max_duration_iteration=1,
                max_iteration_duration=100.0,
            )
        ]
        result = format_slowest_stories(stories)

        assert "Story ID" in result
        assert "Total Duration" in result
        assert "Longest Iteration" in result
        assert "Duration" in result


class TestShowSlowestStories:
    """Integration tests for show_slowest_stories()."""

    def test_slowest_stories_top5(self) -> None:
        """Test that top 5 slowest stories are correctly identified and ranked (AC3)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
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
                ],
                delimiter="\t",
            )
            writer.writeheader()

            # Create 7 stories with varied durations
            # US-001: Phase I - 500s total (longest)
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-001",
                    "story_title": "Phase I Implementation Test",
                    "status": "pass",
                    "duration_sec": "500",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-002: 400s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:01:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-002",
                    "story_title": "Story 2",
                    "status": "pass",
                    "duration_sec": "400",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-003: 300s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:02:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-003",
                    "story_title": "Story 3",
                    "status": "pass",
                    "duration_sec": "300",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-004: 200s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:03:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-004",
                    "story_title": "Story 4",
                    "status": "pass",
                    "duration_sec": "200",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-005: 150s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:04:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-005",
                    "story_title": "Story 5",
                    "status": "pass",
                    "duration_sec": "150",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-006: 100s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:05:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-006",
                    "story_title": "Story 6",
                    "status": "pass",
                    "duration_sec": "100",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            # US-007: 50s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:06:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-007",
                    "story_title": "Story 7",
                    "status": "pass",
                    "duration_sec": "50",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            path = f.name

        try:
            output = show_slowest_stories(path)

            # Verify top 5 are present and in correct order
            assert "US-001" in output
            assert "US-002" in output
            assert "US-003" in output
            assert "US-004" in output
            assert "US-005" in output

            # Verify US-001 (Phase I) is in the output (AC3: "includes Phase I as expected bottleneck")
            assert "Phase I" in output or "US-001" in output

            # Verify sorting: US-001 should come before US-002, etc.
            idx_001 = output.find("US-001")
            idx_002 = output.find("US-002")
            idx_003 = output.find("US-003")
            idx_004 = output.find("US-004")
            idx_005 = output.find("US-005")

            assert idx_001 < idx_002 < idx_003 < idx_004 < idx_005

        finally:
            Path(path).unlink()

    def test_slowest_stories_with_multiple_iterations(self) -> None:
        """Test aggregation across multiple iterations per story."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
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
                ],
                delimiter="\t",
            )
            writer.writeheader()

            # US-001: appears 3 times (100 + 200 + 300 = 600 total)
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-001",
                    "story_title": "Multi-iteration Story",
                    "status": "reject",
                    "duration_sec": "100",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:01:00Z",
                    "spiral_iter": "2",
                    "ralph_iter": "1",
                    "story_id": "US-001",
                    "story_title": "Multi-iteration Story",
                    "status": "reject",
                    "duration_sec": "200",
                    "model": "sonnet",
                    "retry_num": "1",
                    "commit_sha": "def456",
                    "run_id": "run2",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:02:00Z",
                    "spiral_iter": "3",
                    "ralph_iter": "1",
                    "story_id": "US-001",
                    "story_title": "Multi-iteration Story",
                    "status": "pass",
                    "duration_sec": "300",
                    "model": "opus",
                    "retry_num": "2",
                    "commit_sha": "ghi789",
                    "run_id": "run3",
                }
            )

            # US-002: single iteration, 150s
            writer.writerow(
                {
                    "timestamp": "2026-03-20T00:03:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-002",
                    "story_title": "Single Story",
                    "status": "pass",
                    "duration_sec": "150",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                    "run_id": "run1",
                }
            )

            path = f.name

        try:
            output = show_slowest_stories(path)

            # US-001 should appear first (600s > 150s)
            idx_001 = output.find("US-001")
            idx_002 = output.find("US-002")
            assert idx_001 < idx_002
            assert "600.0" in output or "600" in output  # Total for US-001

        finally:
            Path(path).unlink()

    def test_slowest_stories_missing_file(self) -> None:
        """Test handling of missing results.tsv file."""
        output = show_slowest_stories("/nonexistent/results.tsv")

        # Should return empty table (no error)
        assert "Story ID" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
