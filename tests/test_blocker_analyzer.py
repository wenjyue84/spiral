#!/usr/bin/env python3
"""tests/test_blocker_analyzer.py — Unit tests for blocker analyzer (US-1071)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from lib.blocker_analyzer import (
    _get_passed_stories,
    _get_story_completion_times,
    analyze_blocked_stories,
)


@pytest.fixture
def temp_prd_json() -> Path:
    """Create a temporary prd.json with test stories."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        prd = {
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "dependencies": ["US-001"],
                },
                {
                    "id": "US-003",
                    "title": "Story 3",
                    "dependencies": ["US-001", "US-002"],
                },
                {
                    "id": "US-004",
                    "title": "Story 4",
                    "dependencies": ["US-999"],  # Non-existent dependency
                },
            ],
        }
        json.dump(prd, f)
        f.flush()
        return Path(f.name)


@pytest.fixture
def temp_results_tsv() -> Path:
    """Create a temporary results.tsv file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        # Write header
        f.write(
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
            "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\n"
        )
        # Write records
        f.write("2026-03-20T10:00:00Z\t1\t1\tUS-001\tStory 1\tpassed\t3600\thaiku\t0\tabc123\trun-1\n")
        f.write("2026-03-20T10:02:00Z\t1\t1\tUS-002\tStory 2\tfailed\t7200\thaiku\t0\tabc123\trun-1\n")
        f.flush()
        return Path(f.name)


def test_analyze_blocked_stories_with_unmet_deps(temp_prd_json: Path, temp_results_tsv: Path) -> None:
    """Test that stories with unmet dependencies are identified as blocked."""
    blocked = analyze_blocked_stories(prd_path=temp_prd_json, results_tsv_path=temp_results_tsv)

    # US-003 depends on US-001 (passed) and US-002 (not passed)
    # US-004 depends on US-999 (non-existent)
    assert len(blocked) == 2

    # Check US-003 is blocked
    us_003 = next((b for b in blocked if b["id"] == "US-003"), None)
    assert us_003 is not None
    assert "US-002" in us_003["blocking_story_ids"]
    assert us_003["estimated_unblock_hours"] == 1.0  # 3600 sec median

    # Check US-004 is blocked
    us_004 = next((b for b in blocked if b["id"] == "US-004"), None)
    assert us_004 is not None
    assert "US-999" in us_004["blocking_story_ids"]


def test_analyze_blocked_stories_no_dependencies(temp_prd_json: Path, temp_results_tsv: Path) -> None:
    """Test that stories without dependencies are not in blocked list."""
    blocked = analyze_blocked_stories(prd_path=temp_prd_json, results_tsv_path=temp_results_tsv)
    blocked_ids = [b["id"] for b in blocked]
    assert "US-001" not in blocked_ids


def test_analyze_blocked_stories_missing_prd() -> None:
    """Test graceful handling of missing prd.json."""
    blocked = analyze_blocked_stories(prd_path="/nonexistent/prd.json", results_tsv_path="/tmp/results.tsv")
    assert blocked == []


def test_analyze_blocked_stories_missing_tsv(temp_prd_json: Path) -> None:
    """Test graceful handling of missing results.tsv."""
    blocked = analyze_blocked_stories(prd_path=temp_prd_json, results_tsv_path="/nonexistent/results.tsv")
    # All stories with dependencies should be blocked (no passed stories)
    assert len(blocked) == 3  # US-002, US-003, US-004
    assert all(b["estimated_unblock_hours"] == 1.0 for b in blocked)


def test_get_passed_stories(temp_results_tsv: Path) -> None:
    """Test extraction of passed stories from results.tsv."""
    passed = _get_passed_stories(temp_results_tsv)
    assert passed == {"US-001"}


def test_get_passed_stories_missing_file() -> None:
    """Test graceful handling of missing results.tsv."""
    passed = _get_passed_stories(Path("/nonexistent/results.tsv"))
    assert passed == set()


def test_get_story_completion_times(temp_results_tsv: Path) -> None:
    """Test extraction of story completion times."""
    times = _get_story_completion_times(temp_results_tsv)
    # US-001 has duration_sec=3600, which is 1.0 hour
    assert times == [1.0]


def test_get_story_completion_times_missing_file() -> None:
    """Test graceful handling of missing results.tsv."""
    times = _get_story_completion_times(Path("/nonexistent/results.tsv"))
    assert times == []


def test_analyze_blocked_stories_median_calculation() -> None:
    """Test that median completion time is calculated correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        prd = {
            "userStories": [
                {"id": "US-001", "title": "Story 1", "dependencies": []},
                {"id": "US-002", "title": "Story 2", "dependencies": ["US-001"]},
                {"id": "US-003", "title": "Story 3", "dependencies": ["US-002"]},
            ]
        }
        json.dump(prd, f)
        f.flush()
        prd_path = Path(f.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        # Write header
        f.write(
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
            "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\n"
        )
        # Three passing stories with different durations (3600, 7200, 5400 seconds)
        f.write("2026-03-20T10:00:00Z\t1\t1\tUS-001\tStory 1\tpassed\t3600\thaiku\t0\tabc\trun-1\n")
        f.write("2026-03-20T10:02:00Z\t1\t1\tUS-001\tStory 1\tpassed\t7200\thaiku\t1\tabc\trun-1\n")
        f.write("2026-03-20T10:04:00Z\t1\t1\tUS-001\tStory 1\tpassed\t5400\thaiku\t2\tabc\trun-1\n")
        f.flush()
        tsv_path = Path(f.name)

    blocked = analyze_blocked_stories(prd_path=prd_path, results_tsv_path=tsv_path)

    # US-001 is passed, so US-002 is not blocked
    # US-003 depends on US-002 (which is not passed), so US-003 is blocked
    # Median of [3600, 7200, 5400] seconds = 5400 seconds = 1.5 hours
    assert len(blocked) == 1
    assert blocked[0]["id"] == "US-003"
    assert blocked[0]["estimated_unblock_hours"] == 1.5


def test_analyze_blocked_stories_response_schema(temp_prd_json: Path, temp_results_tsv: Path) -> None:
    """Test that response has correct schema."""
    blocked = analyze_blocked_stories(prd_path=temp_prd_json, results_tsv_path=temp_results_tsv)

    for item in blocked:
        assert "id" in item
        assert "reason" in item
        assert "blocking_story_ids" in item
        assert "estimated_unblock_hours" in item
        assert isinstance(item["id"], str)
        assert isinstance(item["reason"], str)
        assert isinstance(item["blocking_story_ids"], list)
        assert isinstance(item["estimated_unblock_hours"], (int, float))
