"""Tests for worker heartbeat monitoring and stall detection (US-1342).

Tests the HeartbeatSender and HeartbeatMonitor classes to verify:
- Heartbeats are emitted to JSON log
- Stalls are detected after timeout
- Crash log records are written correctly
- Worker process termination is triggered
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

# Add lib/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from worker_heartbeat_monitor import HeartbeatMonitor, HeartbeatSender


class TestHeartbeatSender:
    """Test HeartbeatSender.emit() method."""

    def test_emit_writes_json_to_log(self, tmp_path: Path) -> None:
        """Test that emit() writes JSON entry to heartbeat log."""
        hb_file = tmp_path / "heartbeats.jsonl"
        sender = HeartbeatSender("US-TEST-1", str(hb_file))

        sender.emit({"tokens": 0})

        assert hb_file.exists()
        with open(hb_file, encoding="utf-8") as f:
            line = f.readline()
            assert line.strip()
            entry = json.loads(line)
            assert entry["story_id"] == "US-TEST-1"
            assert entry["worker_pid"] == os.getpid()
            assert "timestamp" in entry
            assert entry["tokens"] == 0

    def test_emit_creates_directory(self, tmp_path: Path) -> None:
        """Test that emit() creates parent directory if missing."""
        hb_file = tmp_path / "subdir" / "heartbeats.jsonl"
        sender = HeartbeatSender("US-TEST-2", str(hb_file))

        sender.emit({"tokens": 100})

        assert hb_file.exists()
        assert hb_file.parent.exists()

    def test_emit_appends_multiple_entries(self, tmp_path: Path) -> None:
        """Test that multiple emit() calls append to log."""
        hb_file = tmp_path / "heartbeats.jsonl"
        sender = HeartbeatSender("US-TEST-3", str(hb_file))

        sender.emit({"tokens": 0})
        sender.emit({"tokens": 50})
        sender.emit({"tokens": 100})

        entries = []
        with open(hb_file, encoding="utf-8") as f:
            for line in f:
                entries.append(json.loads(line))

        assert len(entries) == 3
        assert entries[0]["tokens"] == 0
        assert entries[1]["tokens"] == 50
        assert entries[2]["tokens"] == 100


class TestHeartbeatMonitor:
    """Test HeartbeatMonitor.check_all() stall detection."""

    def test_stall_detection_and_redirect(self, tmp_path: Path) -> None:
        """Test that stalled workers (>60s without heartbeat) are detected.

        This is the primary acceptance criterion for US-1342.
        """
        hb_file = tmp_path / "heartbeats.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        # Create a stale heartbeat (more than 60s old)
        stale_entry = {
            "timestamp": "2020-01-01T00:00:00+00:00",  # 4+ years old
            "story_id": "US-STALE",
            "worker_pid": 9999,
            "tokens": 0,
        }
        with open(hb_file, "w", encoding="utf-8") as f:
            json.dump(stale_entry, f)
            f.write("\n")

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)

        # Mock os.kill to avoid actually killing a process
        with mock.patch("os.kill") as mock_kill:
            stalled = monitor.check_all()

        # Verify stall was detected
        assert len(stalled) == 1
        assert stalled[0]["story_id"] == "US-STALE"
        assert stalled[0]["worker_pid"] == 9999
        assert "No heartbeat" in stalled[0]["reason"]

        # Verify worker termination was attempted
        mock_kill.assert_called_once_with(9999, 15)  # 15 = SIGTERM

        # Verify crash log was written
        assert crash_log.exists()
        with open(crash_log, encoding="utf-8") as f:
            crash_entry = json.loads(f.readline())
            assert crash_entry["story_id"] == "US-STALE"
            assert crash_entry["worker_pid"] == 9999

    def test_recent_heartbeat_not_stalled(self, tmp_path: Path) -> None:
        """Test that recent heartbeats are not marked as stalled."""
        hb_file = tmp_path / "heartbeats.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        # Create a recent heartbeat
        recent_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            "story_id": "US-RECENT",
            "worker_pid": 8888,
            "tokens": 100,
        }
        with open(hb_file, "w", encoding="utf-8") as f:
            json.dump(recent_entry, f)
            f.write("\n")

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)

        stalled = monitor.check_all()

        # Should not be detected as stalled
        assert len(stalled) == 0
        # Crash log should not exist (nothing logged)
        assert not crash_log.exists()

    def test_crash_log_contains_required_fields(self, tmp_path: Path) -> None:
        """Test that crash log entries have all required fields."""
        hb_file = tmp_path / "heartbeats.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        stale_entry = {
            "timestamp": "2020-01-01T00:00:00+00:00",
            "story_id": "US-CRASH-TEST",
            "worker_pid": 7777,
            "tokens": 0,
        }
        with open(hb_file, "w", encoding="utf-8") as f:
            json.dump(stale_entry, f)
            f.write("\n")

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)
        with mock.patch("os.kill"):
            monitor.check_all()

        # Read crash log and verify fields
        with open(crash_log, encoding="utf-8") as f:
            crash = json.loads(f.readline())
            required_fields = {"timestamp", "story_id", "worker_pid", "reason"}
            assert required_fields.issubset(crash.keys())

    def test_empty_heartbeat_file(self, tmp_path: Path) -> None:
        """Test that monitor handles empty heartbeat file gracefully."""
        hb_file = tmp_path / "heartbeats.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        # Create empty file
        hb_file.touch()

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)
        stalled = monitor.check_all()

        assert stalled == []

    def test_missing_heartbeat_file(self, tmp_path: Path) -> None:
        """Test that monitor handles missing heartbeat file gracefully."""
        hb_file = tmp_path / "nonexistent.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)
        stalled = monitor.check_all()

        assert stalled == []

    def test_malformed_heartbeat_entries(self, tmp_path: Path) -> None:
        """Test that monitor handles malformed JSON gracefully."""
        hb_file = tmp_path / "heartbeats.jsonl"
        crash_log = tmp_path / "crashes.jsonl"

        # Write mix of valid and malformed entries
        with open(hb_file, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write('{"timestamp": "2020-01-01T00:00:00+00:00", "worker_pid": 6666}\n')
            f.write("another bad line\n")

        monitor = HeartbeatMonitor(str(hb_file), str(crash_log), timeout_seconds=60)
        with mock.patch("os.kill"):
            stalled = monitor.check_all()

        # Should detect the valid but stale entry
        assert len(stalled) == 1
        assert stalled[0]["worker_pid"] == 6666
