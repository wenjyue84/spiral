#!/usr/bin/env python3
"""Tests for dashboard throughput aggregation API (US-1254)."""

import json
import tempfile
import time
from pathlib import Path

import pytest

from lib.dashboard import throughput as throughput_module
from lib.dashboard.throughput import aggregate as aggregate_throughput
from lib.results_tsv import ResultsRecord, write_results_tsv


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Clear throughput cache before each test."""
    throughput_module._THROUGHPUT_CACHE.clear()
    throughput_module._CACHE_TIMESTAMP = 0.0
    yield


@pytest.fixture
def temp_results_tsv() -> tuple[str, str]:
    """Create temporary results.tsv and checkpoint files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        results_path = str(Path(tmpdir) / "results.tsv")
        checkpoint_path = str(Path(tmpdir) / "checkpoint.json")
        yield results_path, checkpoint_path


def test_hourly_aggregation(temp_results_tsv: tuple[str, str]) -> None:
    """Test basic hourly aggregation of passed stories."""
    results_path, checkpoint_path = temp_results_tsv

    # Create checkpoint for iteration 5
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    # Create results with stories at different hours
    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:10:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-100",
            story_title="Test 1",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:25:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="Test 2",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:55:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-102",
            story_title="Test 3",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T15:10:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-103",
            story_title="Test 4",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    # Aggregate
    result = aggregate_throughput(results_path, checkpoint_path)

    # Verify results
    assert len(result) == 2, f"Expected 2 hours, got {len(result)}"
    assert result[0]["hour"] == "2026-04-05T14:00"
    assert result[0]["count"] == 3
    assert set(result[0]["stories"]) == {"US-100", "US-101", "US-102"}
    assert result[1]["hour"] == "2026-04-05T15:00"
    assert result[1]["count"] == 1
    assert result[1]["stories"] == ["US-103"]


def test_filters_by_iteration(temp_results_tsv: tuple[str, str]) -> None:
    """Test that aggregation filters to current iteration only."""
    results_path, checkpoint_path = temp_results_tsv

    # Create checkpoint for iteration 5
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    # Create results from iterations 4 and 5
    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="4",
            ralph_iter="1",
            story_id="US-100",
            story_title="Old",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:10:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="New",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    result = aggregate_throughput(results_path, checkpoint_path)

    # Should only include iteration 5
    assert len(result) == 1
    assert result[0]["count"] == 1
    assert result[0]["stories"] == ["US-101"]


def test_filters_by_status(temp_results_tsv: tuple[str, str]) -> None:
    """Test that only 'passed' status stories are included."""
    results_path, checkpoint_path = temp_results_tsv

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-100",
            story_title="Passed",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:10:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="Failed",
            status="failed",
            duration_sec="60",
            model="haiku",
            retry_num="1",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:20:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-102",
            story_title="Rejected",
            status="reject",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    result = aggregate_throughput(results_path, checkpoint_path)

    # Should only include US-100 (passed status)
    assert len(result) == 1
    assert result[0]["count"] == 1
    assert result[0]["stories"] == ["US-100"]


def test_caching_behavior(temp_results_tsv: tuple[str, str]) -> None:
    """Test that caching works for 5 seconds."""
    results_path, checkpoint_path = temp_results_tsv

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    # Create initial record
    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-100",
            story_title="Test",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    # First call
    result1 = aggregate_throughput(results_path, checkpoint_path)
    assert len(result1) == 1
    assert result1[0]["count"] == 1

    # Clear the file and try again immediately (should be cached)
    with open(results_path, "w", encoding="utf-8") as f:
        f.write(
            "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\n"
        )

    result2 = aggregate_throughput(results_path, checkpoint_path)
    assert result2 == result1, "Cache should return same result"

    # Wait 5 seconds and try again (cache expired)
    time.sleep(5.1)

    result3 = aggregate_throughput(results_path, checkpoint_path)
    assert len(result3) == 0, "Cache expired, should return empty results"


def test_malformed_timestamps_ignored(temp_results_tsv: tuple[str, str]) -> None:
    """Test that malformed timestamps are skipped without raising."""
    results_path, checkpoint_path = temp_results_tsv

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-100",
            story_title="Valid",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="invalid-timestamp",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="Invalid",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    result = aggregate_throughput(results_path, checkpoint_path)

    # Should only include valid timestamp
    assert len(result) == 1
    assert result[0]["count"] == 1
    assert result[0]["stories"] == ["US-100"]


def test_missing_files_returns_empty(temp_results_tsv: tuple[str, str]) -> None:
    """Test that missing results.tsv returns empty result."""
    _, checkpoint_path = temp_results_tsv

    # Don't create results.tsv
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    result = aggregate_throughput("/nonexistent/results.tsv", checkpoint_path)

    assert result == []


def test_no_checkpoint_filters_all_iterations(temp_results_tsv: tuple[str, str]) -> None:
    """Test that missing checkpoint includes all iterations."""
    results_path, checkpoint_path = temp_results_tsv

    # Don't create checkpoint file
    Path(results_path).parent.mkdir(parents=True, exist_ok=True)

    records = [
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="4",
            ralph_iter="1",
            story_id="US-100",
            story_title="Iter4",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:10:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="Iter5",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    result = aggregate_throughput(results_path, checkpoint_path)

    # Should include both iterations
    assert len(result) == 1
    assert result[0]["count"] == 2
    assert set(result[0]["stories"]) == {"US-100", "US-101"}


def test_sorted_by_hour(temp_results_tsv: tuple[str, str]) -> None:
    """Test that results are sorted by hour ascending."""
    results_path, checkpoint_path = temp_results_tsv

    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({"iter": 5}, f)

    # Create records out of order
    records = [
        ResultsRecord(
            timestamp="2026-04-05T16:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-103",
            story_title="Hour16",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T14:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-100",
            story_title="Hour14",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
        ResultsRecord(
            timestamp="2026-04-05T15:00:00Z",
            spiral_iter="5",
            ralph_iter="1",
            story_id="US-101",
            story_title="Hour15",
            status="passed",
            duration_sec="60",
            model="haiku",
            retry_num="0",
            commit_sha="abc",
            run_id="run1",
        ),
    ]
    write_results_tsv(results_path, records)

    result = aggregate_throughput(results_path, checkpoint_path)

    # Verify hours are in ascending order
    assert len(result) == 3
    assert result[0]["hour"] == "2026-04-05T14:00"
    assert result[1]["hour"] == "2026-04-05T15:00"
    assert result[2]["hour"] == "2026-04-05T16:00"
