"""Tests for worker pool API (US-481).

Tests cover:
- Worker status endpoint response format
- Timeout detection for stale workers (>5 minutes)
- Graceful handling of no workers
- Elapsed time calculation
"""

import json
import os

# Import from lib (parent directory)
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from worker_api import WorkerPoolAPI


@pytest.fixture
def temp_workers_dir():
    """Create a temporary directory for worker heartbeat files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_worker_api_empty_directory(temp_workers_dir):
    """Test that API gracefully handles missing or empty workers directory."""
    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()
    assert workers == []


def test_worker_api_nonexistent_directory():
    """Test that API gracefully handles non-existent heartbeat directory."""
    api = WorkerPoolAPI("/nonexistent/path/workers")
    workers = api.get_workers()
    assert workers == []


def test_worker_api_single_alive_worker(temp_workers_dir):
    """Test API returns correct response format for a fresh (alive) worker."""
    # Create worker-1 subdirectory
    worker_dir = Path(temp_workers_dir) / "worker-1"
    worker_dir.mkdir()

    # Write heartbeat file (current timestamp)
    now = time.time()
    hb_data = {
        "pid": 1234,
        "storyId": "US-123",
        "ts": now,
        "completed": 5,
        "phase": "I",
        "memMb": 128,
    }
    hb_file = worker_dir / ".heartbeat"
    with open(hb_file, "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 1
    assert workers[0]["worker_id"] == "worker-1"
    assert workers[0]["current_story"] == "US-123"
    assert workers[0]["elapsed_time_sec"] >= 0
    assert workers[0]["state"] == "alive"


def test_worker_api_timeout_detection(temp_workers_dir):
    """Test that workers with stale heartbeat >5 minutes are marked timeout."""
    worker_dir = Path(temp_workers_dir) / "worker-2"
    worker_dir.mkdir()

    # Write heartbeat with old timestamp (6 minutes ago)
    old_ts = time.time() - 360  # 6 minutes ago
    hb_data = {
        "pid": 5678,
        "storyId": "US-456",
        "ts": old_ts,
        "completed": 10,
        "phase": "V",
        "memMb": 256,
    }
    hb_file = worker_dir / ".heartbeat"
    with open(hb_file, "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 1
    assert workers[0]["worker_id"] == "worker-2"
    assert workers[0]["current_story"] == "US-456"
    assert workers[0]["elapsed_time_sec"] >= 360
    assert workers[0]["state"] == "timeout"


def test_worker_api_multiple_workers(temp_workers_dir):
    """Test API with multiple workers (alive and timeout mixed)."""
    now = time.time()

    # Worker 1: alive (fresh heartbeat)
    w1_dir = Path(temp_workers_dir) / "worker-1"
    w1_dir.mkdir()
    with open(w1_dir / ".heartbeat", "w") as f:
        json.dump({"storyId": "US-001", "ts": now}, f)

    # Worker 2: timeout (6 minutes old)
    w2_dir = Path(temp_workers_dir) / "worker-2"
    w2_dir.mkdir()
    with open(w2_dir / ".heartbeat", "w") as f:
        json.dump({"storyId": "US-002", "ts": now - 360}, f)

    # Worker 3: alive (2 minutes old)
    w3_dir = Path(temp_workers_dir) / "worker-3"
    w3_dir.mkdir()
    with open(w3_dir / ".heartbeat", "w") as f:
        json.dump({"storyId": "US-003", "ts": now - 120}, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 3

    # Check worker states
    states = {w["worker_id"]: w["state"] for w in workers}
    assert states["worker-1"] == "alive"
    assert states["worker-2"] == "timeout"
    assert states["worker-3"] == "alive"

    # Verify elapsed times
    elapsed_times = {w["worker_id"]: w["elapsed_time_sec"] for w in workers}
    assert elapsed_times["worker-1"] < 2
    assert 358 <= elapsed_times["worker-2"] <= 362
    assert 118 <= elapsed_times["worker-3"] <= 122


def test_worker_api_malformed_heartbeat(temp_workers_dir):
    """Test that API gracefully skips malformed heartbeat files."""
    worker_dir = Path(temp_workers_dir) / "worker-bad"
    worker_dir.mkdir()

    # Write invalid JSON
    hb_file = worker_dir / ".heartbeat"
    with open(hb_file, "w") as f:
        f.write("{ invalid json")

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    # Should gracefully skip the bad file and return empty list
    assert workers == []


def test_worker_api_missing_story_id(temp_workers_dir):
    """Test that missing storyId defaults to 'unknown'."""
    worker_dir = Path(temp_workers_dir) / "worker-nostory"
    worker_dir.mkdir()

    # Heartbeat without storyId field
    hb_data = {"pid": 9999, "ts": time.time(), "phase": "R"}
    with open(worker_dir / ".heartbeat", "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 1
    assert workers[0]["current_story"] == "unknown"


def test_worker_api_missing_timestamp(temp_workers_dir):
    """Test that heartbeat without timestamp is skipped."""
    worker_dir = Path(temp_workers_dir) / "worker-nots"
    worker_dir.mkdir()

    # Heartbeat without ts field
    hb_data = {"pid": 1111, "storyId": "US-999"}
    with open(worker_dir / ".heartbeat", "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    # Should skip this worker since it has no timestamp
    assert workers == []


def test_worker_api_sorting(temp_workers_dir):
    """Test that workers are returned in sorted order by worker_id."""
    now = time.time()

    for i in [3, 1, 2]:
        worker_dir = Path(temp_workers_dir) / f"worker-{i}"
        worker_dir.mkdir()
        with open(worker_dir / ".heartbeat", "w") as f:
            json.dump({"storyId": f"US-{i:03d}", "ts": now}, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    # Should be sorted by worker_id
    worker_ids = [w["worker_id"] for w in workers]
    assert worker_ids == ["worker-1", "worker-2", "worker-3"]


def test_worker_api_timeout_boundary(temp_workers_dir):
    """Test timeout detection at exact 5-minute boundary."""
    worker_dir = Path(temp_workers_dir) / "worker-boundary"
    worker_dir.mkdir()

    # Exactly 300 seconds ago (boundary)
    boundary_ts = time.time() - 300
    hb_data = {"storyId": "US-BND", "ts": boundary_ts}
    with open(worker_dir / ".heartbeat", "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 1
    # At exactly 300 seconds, should still be 'alive' (timeout only if > 300)
    assert workers[0]["state"] == "alive"

    # 301 seconds old should be timeout
    boundary_ts_plus = time.time() - 301
    hb_data["ts"] = boundary_ts_plus
    with open(worker_dir / ".heartbeat", "w") as f:
        json.dump(hb_data, f)

    api = WorkerPoolAPI(temp_workers_dir)
    workers = api.get_workers()

    assert len(workers) == 1
    assert workers[0]["state"] == "timeout"
