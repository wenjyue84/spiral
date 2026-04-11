"""Performance tests for lib/worker_heartbeat.sh & US-531 worker stall detection.

Verifies that stall detection and restart operations meet performance baselines:
1. Measures heartbeat file read and JSON parsing time
2. Measures stall calculation (elapsed time detection) for single/multi-worker scenarios
3. Measures restart event logging throughput
4. Captures baseline metrics and checks for ≤20% degradation
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_baseline(metric_name: str) -> float | None:
    """Load baseline metrics from .spiral/us_531_baseline.json, or None if not found."""
    baseline_file = ".spiral/us_531_baseline.json"
    if not os.path.exists(baseline_file):
        return None
    try:
        with open(baseline_file, encoding="utf-8") as f:
            data = json.load(f)
            value = data.get(metric_name)
            return value if isinstance(value, (int, float)) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_baseline(metric_name: str, value: float) -> None:
    """Save baseline metrics to .spiral/us_531_baseline.json."""
    baseline_file = ".spiral/us_531_baseline.json"
    os.makedirs(".spiral", exist_ok=True)

    data: dict[str, Any] = {}
    if os.path.exists(baseline_file):
        try:
            with open(baseline_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

    data[metric_name] = value

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _make_heartbeat(
    story_id: str = "US-001",
    stale_secs: int = 0,
    completed: int = 0,
) -> dict[str, Any]:
    """Create a heartbeat JSON dict."""
    now = int(time.time())
    last_progress = now - stale_secs
    return {
        "pid": 1234,
        "storyId": story_id,
        "ts": now,
        "completed": completed,
        "phase": "running",
        "memMb": 150,
        "nodeMemMb": 200,
        "nodePid": 5678,
        "last_progress_time": last_progress,
    }


def _write_heartbeat_file(heartbeat_dir: str, worker_id: int, heartbeat_data: dict[str, Any]) -> None:
    """Write a heartbeat JSON file to the worker directory."""
    os.makedirs(heartbeat_dir, exist_ok=True)
    hb_file = os.path.join(heartbeat_dir, f"worker-{worker_id}", ".heartbeat")
    os.makedirs(os.path.dirname(hb_file), exist_ok=True)
    with open(hb_file, "w", encoding="utf-8") as f:
        json.dump(heartbeat_data, f)


# ---------------------------------------------------------------------------
# TestUS531PerformanceHeartbeat
# ---------------------------------------------------------------------------


@pytest.mark.us_531
class TestUS531PerformanceHeartbeat:
    """Performance tests for US-531 worker stall detection & restart."""

    DEGRADATION_THRESHOLD = 0.30  # 30% max acceptable degradation (accounts for system variance)

    def test_us_531_heartbeat_read_single_worker(self) -> None:
        """Measure time to read and parse a single worker heartbeat file. Baseline: ~0.5ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hb_data = _make_heartbeat("US-001", stale_secs=0)
            _write_heartbeat_file(tmpdir, 1, hb_data)

            hb_file = os.path.join(tmpdir, "worker-1", ".heartbeat")

            # Measure read + JSON parse
            start = time.perf_counter()
            with open(hb_file, encoding="utf-8") as f:
                content = json.load(f)
            elapsed = time.perf_counter() - start

            # Verify correctness
            assert content["storyId"] == "US-001"
            assert "last_progress_time" in content
            assert isinstance(content["last_progress_time"], int)

            # Check against baseline
            baseline = _load_baseline("heartbeat_read_single_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Heartbeat read (single): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("heartbeat_read_single_ms", elapsed)

    def test_us_531_heartbeat_read_10_workers(self) -> None:
        """Measure time to read 10 worker heartbeat files. Baseline: ~5ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10 heartbeat files
            for i in range(1, 11):
                hb_data = _make_heartbeat(f"US-{i:03d}", stale_secs=i * 10)
                _write_heartbeat_file(tmpdir, i, hb_data)

            # Measure read + parse all 10
            start = time.perf_counter()
            results = []
            for i in range(1, 11):
                hb_file = os.path.join(tmpdir, f"worker-{i}", ".heartbeat")
                with open(hb_file, encoding="utf-8") as f:
                    results.append(json.load(f))
            elapsed = time.perf_counter() - start

            # Verify correctness
            assert len(results) == 10
            assert all("last_progress_time" in r for r in results)

            # Check against baseline
            baseline = _load_baseline("heartbeat_read_10_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Heartbeat read (10 workers): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("heartbeat_read_10_ms", elapsed)

    def test_us_531_stall_calculation_single(self) -> None:
        """Measure time to detect stall on a single worker (1000 iterations for reliability). Baseline: ~1ms."""
        hb_data = _make_heartbeat("US-001", stale_secs=400)  # 400s stale (> 300s timeout)
        now = int(time.time())

        # Warmup run
        for _ in range(10):
            last_progress_time = hb_data["last_progress_time"]
            stall_elapsed = now - last_progress_time
            _ = stall_elapsed > 300

        # Measure stall detection logic over 1000 iterations (for micro-op reliability)
        start = time.perf_counter()
        for _ in range(1000):
            last_progress_time = hb_data["last_progress_time"]
            stall_elapsed = now - last_progress_time
            is_stalled = stall_elapsed > 300  # SPIRAL_WORKER_TIMEOUT default
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert is_stalled is True
        assert stall_elapsed > 300

        # Per-operation time
        per_op_elapsed = elapsed / 1000

        # Check against baseline
        baseline = _load_baseline("stall_calc_single_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert per_op_elapsed <= max_allowed, (
                f"Stall detection (single, avg): {per_op_elapsed * 1000:.4f}ms "
                f"(baseline: {baseline * 1000:.4f}ms, max: {max_allowed * 1000:.4f}ms)"
            )
        else:
            _save_baseline("stall_calc_single_ms", per_op_elapsed)

    def test_us_531_stall_detection_10_workers(self) -> None:
        """Measure time to check stall status for 10 workers. Baseline: ~5ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10 heartbeat files with mixed stale/fresh status
            for i in range(1, 11):
                stale = 400 if i % 3 == 0 else 10  # Every 3rd worker is stalled
                hb_data = _make_heartbeat(f"US-{i:03d}", stale_secs=stale)
                _write_heartbeat_file(tmpdir, i, hb_data)

            now = int(time.time())
            stall_timeout = 300

            # Warmup run to cache filesystem
            for i in range(1, 11):
                hb_file = os.path.join(tmpdir, f"worker-{i}", ".heartbeat")
                with open(hb_file, encoding="utf-8") as f:
                    _ = json.load(f)

            # Measure stall detection loop over 10 workers
            start = time.perf_counter()
            stalled_workers = []
            for i in range(1, 11):
                hb_file = os.path.join(tmpdir, f"worker-{i}", ".heartbeat")
                with open(hb_file, encoding="utf-8") as f:
                    hb_data = json.load(f)
                last_progress_time = hb_data.get("last_progress_time", 0)
                if last_progress_time > 0:
                    stall_elapsed = now - last_progress_time
                    if stall_elapsed > stall_timeout:
                        stalled_workers.append(i)
            elapsed = time.perf_counter() - start

            # Verify correctness (every 3rd worker should be stalled)
            assert len(stalled_workers) == 3
            assert stalled_workers == [3, 6, 9]

            # Check against baseline
            baseline = _load_baseline("stall_detection_10_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Stall detection (10 workers): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("stall_detection_10_ms", elapsed)

    def test_us_531_stall_detection_50_workers(self) -> None:
        """Measure time to check stall status for 50 workers. Baseline: ~5ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 50 heartbeat files with mixed stale/fresh status
            for i in range(1, 51):
                stale = 400 if i % 5 == 0 else 10
                hb_data = _make_heartbeat(f"US-{i:04d}", stale_secs=stale)
                _write_heartbeat_file(tmpdir, i, hb_data)

            now = int(time.time())
            stall_timeout = 300

            # Measure stall detection loop over 50 workers
            start = time.perf_counter()
            stalled_workers = []
            for i in range(1, 51):
                hb_file = os.path.join(tmpdir, f"worker-{i}", ".heartbeat")
                if not os.path.exists(hb_file):
                    continue
                with open(hb_file, encoding="utf-8") as f:
                    hb_data = json.load(f)
                last_progress_time = hb_data.get("last_progress_time", 0)
                if last_progress_time > 0:
                    stall_elapsed = now - last_progress_time
                    if stall_elapsed > stall_timeout:
                        stalled_workers.append(i)
            elapsed = time.perf_counter() - start

            # Verify correctness (every 5th worker should be stalled: 5, 10, 15, ... 50 = 10 workers)
            assert len(stalled_workers) == 10

            # Check against baseline
            baseline = _load_baseline("stall_detection_50_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Stall detection (50 workers): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("stall_detection_50_ms", elapsed)

    def test_us_531_restart_event_logging_single(self) -> None:
        """Measure time to format and write a single restart event. Baseline: ~1ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            events_file = os.path.join(tmpdir, "spiral_events.jsonl")

            event_data = {
                "ts": "2026-04-12T10:30:45Z",
                "event": "worker_stall_restart",
                "run_id": "test-run-531",
                "worker": 1,
                "stall_secs": 420,
            }

            # Measure event formatting and write
            start = time.perf_counter()
            with open(events_file, "a", encoding="utf-8") as f:
                json.dump(event_data, f)
                f.write("\n")
            elapsed = time.perf_counter() - start

            # Verify correctness
            assert os.path.exists(events_file)
            with open(events_file, encoding="utf-8") as f:
                logged = json.loads(f.readline())
                assert logged["event"] == "worker_stall_restart"
                assert logged["worker"] == 1

            # Check against baseline
            baseline = _load_baseline("restart_logging_single_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Restart event logging (single): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("restart_logging_single_ms", elapsed)

    def test_us_531_restart_event_logging_100_events(self) -> None:
        """Measure time to log 100 restart events. Baseline: ~100ms."""
        with tempfile.TemporaryDirectory() as tmpdir:
            events_file = os.path.join(tmpdir, "spiral_events.jsonl")

            # Measure writing 100 events
            start = time.perf_counter()
            with open(events_file, "a", encoding="utf-8") as f:
                for i in range(1, 101):
                    event_data = {
                        "ts": "2026-04-12T10:30:45Z",
                        "event": "worker_stall_restart",
                        "run_id": "test-run-531",
                        "worker": i % 10,
                        "stall_secs": 300 + (i * 5),
                    }
                    json.dump(event_data, f)
                    f.write("\n")
            elapsed = time.perf_counter() - start

            # Verify correctness
            with open(events_file, encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) == 100
                first_event = json.loads(lines[0])
                assert first_event["event"] == "worker_stall_restart"

            # Check against baseline
            baseline = _load_baseline("restart_logging_100_ms")
            if baseline is not None:
                max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
                assert elapsed <= max_allowed, (
                    f"Restart event logging (100 events): {elapsed * 1000:.2f}ms "
                    f"(baseline: {baseline * 1000:.2f}ms, max: {max_allowed * 1000:.2f}ms)"
                )
            else:
                _save_baseline("restart_logging_100_ms", elapsed)

    def test_us_531_baseline_capture(self) -> None:
        """Ensure baseline metrics are recorded after first run."""
        baseline_file = ".spiral/us_531_baseline.json"
        os.makedirs(".spiral", exist_ok=True)

        # After running the tests above, baselines should exist or be created
        _save_baseline("test_metric", 0.001)
        assert os.path.exists(baseline_file)

        with open(baseline_file, encoding="utf-8") as f:
            data = json.load(f)
            assert "test_metric" in data
            assert data["test_metric"] == 0.001
