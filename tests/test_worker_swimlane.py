"""Tests for lib/dashboard/worker_swimlane.py (US-749)."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from lib.dashboard.worker_swimlane import estimate_phase_remaining_time, get_worker_phase_status


class TestGetWorkerPhaseStatus:
    """Tests for get_worker_phase_status()."""

    def test_get_worker_phase_status_no_checkpoint(self) -> None:
        """Return empty list if checkpoint doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_worker_phase_status(tmpdir)
            assert result == []

    def test_get_worker_phase_status_no_workers(self) -> None:
        """Return empty list if no workers are active."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create checkpoint but no workers
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint = {
                "iter": 1,
                "phase": "Phase I",
                "ts": time.time(),
                "run_id": "run-123",
                "spiralVersion": "1.0.0",
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            result = get_worker_phase_status(tmpdir)
            assert result == []

    def test_get_worker_phase_status_single_worker(self) -> None:
        """Return phase status for single active worker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create checkpoint
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint_time = time.time() - 60  # 60 seconds ago
            checkpoint = {
                "iter": 1,
                "phase": "Phase I",
                "ts": checkpoint_time,
                "run_id": "run-123",
                "spiralVersion": "1.0.0",
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            # Create worker heartbeat
            workers_dir = tmppath / ".spiral-workers"
            worker1_dir = workers_dir / "worker-1"
            worker1_dir.mkdir(parents=True)

            heartbeat = {
                "pid": 12345,
                "storyId": "US-123",
                "ts": time.time() - 30,
                "completed": 5,
                "phase": "Phase I",
                "memMb": 128,
                "nodeMemMb": 256,
                "nodePid": 12346,
                "last_progress_time": time.time() - 30,
            }
            with open(worker1_dir / ".heartbeat", "w", encoding="utf-8") as f:
                json.dump(heartbeat, f)

            result = get_worker_phase_status(tmpdir)

            assert len(result) == 1
            assert result[0]["worker_id"] == "worker-1"
            assert result[0]["current_phase"] == "Phase I"
            assert result[0]["phase_start_time"] == checkpoint_time
            assert "estimated_completion_seconds" in result[0]
            assert isinstance(result[0]["estimated_completion_seconds"], float)

    def test_get_worker_phase_status_multiple_workers(self) -> None:
        """Return phase status for multiple active workers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create checkpoint
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint_time = time.time() - 120
            checkpoint = {
                "iter": 2,
                "phase": "Phase V",
                "ts": checkpoint_time,
                "run_id": "run-456",
                "spiralVersion": "1.0.0",
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            # Create multiple worker heartbeats
            workers_dir = tmppath / ".spiral-workers"
            for i in range(1, 4):
                worker_dir = workers_dir / f"worker-{i}"
                worker_dir.mkdir(parents=True)

                heartbeat = {
                    "pid": 12345 + i,
                    "storyId": f"US-{i}00",
                    "ts": time.time() - 30 * i,
                    "completed": 5 + i,
                    "phase": "Phase V",
                    "memMb": 128 + i * 10,
                    "nodeMemMb": 256 + i * 20,
                    "nodePid": 12346 + i,
                    "last_progress_time": time.time() - 30 * i,
                }
                with open(worker_dir / ".heartbeat", "w", encoding="utf-8") as f:
                    json.dump(heartbeat, f)

            result = get_worker_phase_status(tmpdir)

            assert len(result) == 3
            worker_ids = {w["worker_id"] for w in result}
            assert worker_ids == {"worker-1", "worker-2", "worker-3"}

            for worker in result:
                assert worker["current_phase"] == "Phase V"
                assert worker["phase_start_time"] == checkpoint_time
                assert isinstance(worker["estimated_completion_seconds"], float)

    def test_get_worker_phase_status_worker_phase_override(self) -> None:
        """Worker phase from heartbeat overrides checkpoint phase."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create checkpoint with Phase I
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint_time = time.time()
            checkpoint = {
                "iter": 1,
                "phase": "Phase I",
                "ts": checkpoint_time,
                "run_id": "run-789",
                "spiralVersion": "1.0.0",
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            # Create worker with different phase
            workers_dir = tmppath / ".spiral-workers"
            worker1_dir = workers_dir / "worker-1"
            worker1_dir.mkdir(parents=True)

            heartbeat = {
                "pid": 12345,
                "storyId": "US-999",
                "ts": time.time(),
                "completed": 1,
                "phase": "Phase V",  # Different phase
                "memMb": 128,
                "nodeMemMb": 256,
                "nodePid": 12346,
                "last_progress_time": time.time(),
            }
            with open(worker1_dir / ".heartbeat", "w", encoding="utf-8") as f:
                json.dump(heartbeat, f)

            result = get_worker_phase_status(tmpdir)

            assert len(result) == 1
            assert result[0]["current_phase"] == "Phase V"  # From heartbeat, not checkpoint

    def test_get_worker_phase_status_malformed_checkpoint(self) -> None:
        """Return empty list if checkpoint is malformed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create invalid checkpoint
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                f.write("invalid json {")

            result = get_worker_phase_status(tmpdir)
            assert result == []

    def test_get_worker_phase_status_checkpoint_missing_phase(self) -> None:
        """Return empty list if checkpoint missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint = {
                "iter": 1,
                "ts": time.time(),
                # Missing 'phase' field
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            result = get_worker_phase_status(tmpdir)
            assert result == []

    def test_get_worker_phase_status_malformed_heartbeat_skipped(self) -> None:
        """Skip malformed heartbeat files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create checkpoint
            spiral_dir = tmppath / ".spiral"
            spiral_dir.mkdir()
            checkpoint_time = time.time()
            checkpoint = {
                "iter": 1,
                "phase": "Phase I",
                "ts": checkpoint_time,
                "run_id": "run-123",
                "spiralVersion": "1.0.0",
            }
            with open(spiral_dir / "_checkpoint.json", "w", encoding="utf-8") as f:
                json.dump(checkpoint, f)

            # Create one good worker and one bad
            workers_dir = tmppath / ".spiral-workers"

            # Good worker
            worker1_dir = workers_dir / "worker-1"
            worker1_dir.mkdir(parents=True)
            heartbeat_good = {
                "pid": 12345,
                "storyId": "US-123",
                "ts": time.time(),
                "completed": 5,
                "phase": "Phase I",
                "memMb": 128,
                "nodeMemMb": 256,
                "nodePid": 12346,
                "last_progress_time": time.time(),
            }
            with open(worker1_dir / ".heartbeat", "w", encoding="utf-8") as f:
                json.dump(heartbeat_good, f)

            # Bad worker with invalid JSON
            worker2_dir = workers_dir / "worker-2"
            worker2_dir.mkdir(parents=True)
            with open(worker2_dir / ".heartbeat", "w", encoding="utf-8") as f:
                f.write("invalid json {")

            result = get_worker_phase_status(tmpdir)

            # Should only return good worker
            assert len(result) == 1
            assert result[0]["worker_id"] == "worker-1"


class TestEstimatePhaseRemainingTime:
    """Tests for estimate_phase_remaining_time()."""

    def test_estimate_small_complexity_early_phase(self) -> None:
        """Estimate remaining time for small complexity early in phase."""
        # Small: 5 min typical (300 sec)
        elapsed = 60  # 1 minute
        remaining = estimate_phase_remaining_time(elapsed, "small")
        # Should be ~240 sec (300 - 60)
        assert 200 < remaining < 300

    def test_estimate_medium_complexity_early_phase(self) -> None:
        """Estimate remaining time for medium complexity early in phase."""
        # Medium: 15 min typical (900 sec)
        elapsed = 300  # 5 minutes
        remaining = estimate_phase_remaining_time(elapsed, "medium")
        # Should be ~600 sec (900 - 300)
        assert 500 < remaining < 700

    def test_estimate_large_complexity_early_phase(self) -> None:
        """Estimate remaining time for large complexity early in phase."""
        # Large: 30 min typical (1800 sec)
        elapsed = 600  # 10 minutes
        remaining = estimate_phase_remaining_time(elapsed, "large")
        # Should be ~1200 sec (1800 - 600)
        assert 1100 < remaining < 1300

    def test_estimate_critical_complexity_early_phase(self) -> None:
        """Estimate remaining time for critical complexity early in phase."""
        # Critical: 45 min typical (2700 sec)
        elapsed = 900  # 15 minutes
        remaining = estimate_phase_remaining_time(elapsed, "critical")
        # Should be ~1800 sec (2700 - 900)
        assert 1700 < remaining < 1900

    def test_estimate_past_typical_time(self) -> None:
        """Estimate remaining time when already past typical time."""
        # Small: 5 min typical (300), 8 min max (480)
        elapsed = 400  # Past typical
        remaining = estimate_phase_remaining_time(elapsed, "small")
        # Remaining = (480 - 400) * 0.2 = 16 sec
        assert 10 < remaining < 20

    def test_estimate_past_max_time(self) -> None:
        """Estimate remaining time when past max time."""
        # Medium: 15 min typical (900), 25 min max (1500)
        elapsed = 1600  # Past max
        remaining = estimate_phase_remaining_time(elapsed, "medium")
        # Should be 0 (already exceeded)
        assert remaining == 0.0

    def test_estimate_case_insensitive(self) -> None:
        """Complexity argument is case insensitive."""
        elapsed = 100
        result_lower = estimate_phase_remaining_time(elapsed, "small")
        result_upper = estimate_phase_remaining_time(elapsed, "SMALL")
        result_mixed = estimate_phase_remaining_time(elapsed, "SmAlL")
        assert result_lower == result_upper == result_mixed

    def test_estimate_unknown_complexity_defaults_to_medium(self) -> None:
        """Unknown complexity defaults to medium timing model."""
        elapsed = 300
        result_unknown = estimate_phase_remaining_time(elapsed, "unknown")
        result_medium = estimate_phase_remaining_time(elapsed, "medium")
        assert result_unknown == result_medium

    def test_estimate_zero_elapsed_time(self) -> None:
        """Estimate for zero elapsed time returns full typical duration."""
        elapsed = 0
        remaining = estimate_phase_remaining_time(elapsed, "medium")
        # Should be ~900 sec (medium typical time)
        assert 850 < remaining < 950

    def test_estimate_never_negative(self) -> None:
        """Estimate never returns negative values."""
        # Test with far-exceeded time
        remaining = estimate_phase_remaining_time(10000, "small")
        assert remaining >= 0.0
