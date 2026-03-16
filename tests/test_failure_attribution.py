"""Tests for lib/failure_attribution.py — multi-agent failure attribution (US-233).

Tests cascade detection, resource contention tracking, and causal chain diagnosis.
Includes scenario with intentional worker conflict to verify cascade attribution.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from failure_attribution import (
    FailureAttributor,
    WorkerFailure,
    WorkerResources,
)


class TestFailureAttributor:
    """Test FailureAttributor class directly."""

    def test_register_worker_resources(self, tmp_path: Path) -> None:
        """Workers can register their allocated resources."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        attr.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="spiral-worker-1",
            port=8001,
        )

        assert 1 in attr.resources
        assert attr.resources[1].port_allocated == 8001
        assert attr.resources[1].branch_name == "spiral-worker-1"

    def test_record_local_failure(self, tmp_path: Path) -> None:
        """First worker failure is recorded as local."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        failure = attr.record_failure(
            worker_id=1,
            story_id="US-001",
            error_message="Build failed",
        )

        assert failure.failure_type == "local"
        assert failure.worker_id == 1
        assert failure.story_id == "US-001"
        assert failure.root_cause_worker_id is None

    def test_cascade_detection_shared_worktree(self, tmp_path: Path) -> None:
        """Worker failure is cascade if another worker failed recently with shared resource."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        # Register two workers with same worktree parent
        attr.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="spiral-worker-1",
        )
        attr.register_worker_resources(
            worker_id=2,
            worktree_path="/repo/.spiral-workers/worker-2",
            branch_name="spiral-worker-2",
        )

        # Worker 1 fails (local)
        failure1 = attr.record_failure(
            worker_id=1,
            story_id="US-001",
            error_message="Worker 1 failed",
        )
        assert failure1.failure_type == "local"

        # Worker 2 fails within 30s (should be cascade)
        failure2 = attr.record_failure(
            worker_id=2,
            story_id="US-002",
            error_message="Worker 2 failed",
        )

        assert failure2.failure_type == "cascade"
        assert failure2.root_cause_worker_id == 1
        assert failure2.contended_resource == "worktree"

    def test_cascade_detection_shared_port(self, tmp_path: Path) -> None:
        """Port conflict triggers cascade detection."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        # Register two workers on same port
        attr.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="spiral-worker-1",
            port=8001,
        )
        attr.register_worker_resources(
            worker_id=2,
            worktree_path="/repo/.spiral-workers/worker-2",
            branch_name="spiral-worker-2",
            port=8001,
        )

        failure1 = attr.record_failure(
            worker_id=1,
            story_id="US-001",
            error_message="Bind failed",
        )
        failure2 = attr.record_failure(
            worker_id=2,
            story_id="US-002",
            error_message="Port already in use",
        )

        assert failure2.failure_type == "cascade"
        assert failure2.contended_resource == "port:8001"

    def test_no_cascade_outside_window(self, tmp_path: Path) -> None:
        """Failures outside 30s window are not cascades."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        attr.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="spiral-worker-1",
        )
        attr.register_worker_resources(
            worker_id=2,
            worktree_path="/repo/.spiral-workers/worker-2",
            branch_name="spiral-worker-2",
        )

        # Record first failure with old timestamp (>30s ago)
        old_time = (datetime.utcnow() - timedelta(seconds=35)).isoformat() + "Z"
        failure1 = WorkerFailure(
            worker_id=1,
            story_id="US-001",
            failure_type="local",
            timestamp=old_time,
            error_message="Old failure",
        )
        attr.failures.append(failure1)

        # New failure should be local (not cascade) despite shared resource
        failure2 = attr.record_failure(
            worker_id=2,
            story_id="US-002",
            error_message="New failure",
        )

        assert failure2.failure_type == "local"
        assert failure2.root_cause_worker_id is None

    def test_save_and_load_checkpoint(self, tmp_path: Path) -> None:
        """Failures are persisted to checkpoint and reloaded."""
        checkpoint = tmp_path / "checkpoint.json"

        # Create and save
        attr1 = FailureAttributor(str(checkpoint))
        attr1.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="spiral-worker-1",
        )
        attr1.record_failure(
            worker_id=1,
            story_id="US-001",
            error_message="Test failure",
        )
        attr1.save_checkpoint()

        # Reload
        attr2 = FailureAttributor(str(checkpoint))
        assert len(attr2.failures) == 1
        assert attr2.failures[0].worker_id == 1
        assert attr2.failures[0].story_id == "US-001"
        assert 1 in attr2.resources

    def test_causal_chain_generation(self, tmp_path: Path) -> None:
        """Causal chain correctly groups root failures and cascades."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        attr.register_worker_resources(1, "/repo/.spiral-workers/worker-1", "branch-1")
        attr.register_worker_resources(2, "/repo/.spiral-workers/worker-2", "branch-2")
        attr.register_worker_resources(3, "/repo/.spiral-workers/worker-3", "branch-3")

        # Root failure
        f1 = attr.record_failure(1, "US-001", "Root cause")

        # Two cascades from same root
        f2 = attr.record_failure(2, "US-002", "Cascade from 1")
        f3 = attr.record_failure(3, "US-003", "Another cascade from 1")

        chain = attr.get_causal_chain()
        assert chain["total_failures"] == 3
        assert chain["local_failures"] == 1
        assert chain["cascade_failures"] == 2
        assert len(chain["chains"]) == 1  # Single root causes single chain
        assert len(chain["chains"][0]["failures"]) == 3

    def test_intentional_worker_conflict_scenario(self, tmp_path: Path) -> None:
        """Integration test: realistic scenario with multiple workers competing for resource."""
        checkpoint = tmp_path / "checkpoint.json"
        attr = FailureAttributor(str(checkpoint))

        # Scenario: 3 workers, 2 try to use same port
        attr.register_worker_resources(
            worker_id=1,
            worktree_path="/repo/.spiral-workers/worker-1",
            branch_name="feature-branch-1",
            port=3000,
        )
        attr.register_worker_resources(
            worker_id=2,
            worktree_path="/repo/.spiral-workers/worker-2",
            branch_name="feature-branch-2",
            port=3000,  # Same port!
        )
        attr.register_worker_resources(
            worker_id=3,
            worktree_path="/repo/.spiral-workers/worker-3",
            branch_name="feature-branch-3",
            port=3001,  # Different port
        )

        # Worker 1 starts service on port 3000, succeeds briefly
        # Worker 2 tries to bind same port, fails
        f1 = attr.record_failure(
            worker_id=1,
            story_id="US-100",
            error_message="Service crashed on port 3000",
        )
        assert f1.failure_type == "local"

        # Worker 2 fails trying to bind same port (cascade from 1)
        f2 = attr.record_failure(
            worker_id=2,
            story_id="US-101",
            error_message="Address already in use: port 3000",
        )
        assert f2.failure_type == "cascade"
        assert f2.root_cause_worker_id == 1
        assert f2.contended_resource == "port:3000"

        # Worker 3 uses different port, succeeds (no cascade)
        assert len(attr.failures) == 2  # Only 2 failures recorded

        # Save and verify structure
        attr.save_checkpoint()
        with open(checkpoint) as f:
            ckpt = json.load(f)

        assert "failures" in ckpt
        assert len(ckpt["failures"]) == 2
        assert ckpt["failures"][0]["failure_type"] == "local"
        assert ckpt["failures"][1]["failure_type"] == "cascade"
        assert ckpt["failures"][1]["root_cause_worker_id"] == 1


class TestFailureAttributorCLI:
    """Test CLI interface via subprocess."""

    def test_cli_record_failure(self, tmp_path: Path) -> None:
        """CLI record-failure command works."""
        checkpoint = tmp_path / "checkpoint.json"
        result = subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "record-failure",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--story-id",
                "US-001",
                "--error",
                "Test failure",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "US-001" in result.stdout

    def test_cli_register_worker(self, tmp_path: Path) -> None:
        """CLI register-worker command works."""
        checkpoint = tmp_path / "checkpoint.json"
        result = subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "register-worker",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--worktree",
                "/repo/.spiral-workers/worker-1",
                "--branch",
                "spiral-worker-1",
                "--port",
                "8001",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_cli_diagnose_text(self, tmp_path: Path) -> None:
        """CLI diagnose --format text works."""
        checkpoint = tmp_path / "checkpoint.json"

        # Setup failures
        subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "register-worker",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--worktree",
                "/repo/.spiral-workers/worker-1",
                "--branch",
                "branch-1",
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "record-failure",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--story-id",
                "US-001",
                "--error",
                "Test",
            ],
            check=True,
        )

        # Diagnose
        result = subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "diagnose",
                "--checkpoint",
                str(checkpoint),
                "--format",
                "text",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Total failures: 1" in result.stdout
        assert "LOCAL" in result.stdout

    def test_cli_diagnose_json(self, tmp_path: Path) -> None:
        """CLI diagnose --format json works."""
        checkpoint = tmp_path / "checkpoint.json"

        # Setup
        subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "register-worker",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--worktree",
                "/repo/.spiral-workers/worker-1",
                "--branch",
                "branch-1",
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "record-failure",
                "--checkpoint",
                str(checkpoint),
                "--worker-id",
                "1",
                "--story-id",
                "US-001",
                "--error",
                "Test",
            ],
            check=True,
        )

        # Diagnose as JSON
        result = subprocess.run(
            [
                sys.executable,
                "lib/failure_attribution.py",
                "diagnose",
                "--checkpoint",
                str(checkpoint),
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        assert data["total_failures"] == 1
        assert data["local_failures"] == 1
        assert data["cascade_failures"] == 0
        assert len(data["chains"]) == 1
