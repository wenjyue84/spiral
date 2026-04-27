#!/usr/bin/env python3
"""worker_heartbeat_monitor.py — Worker heartbeat emission and stall detection.

Components:
  HeartbeatSender  — Worker-side: emit periodic heartbeats to .spiral/worker_heartbeats.jsonl
  HeartbeatMonitor — Parent-side: detect stalled workers, log crashes, handle via strategy
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HeartbeatSender:
    """Worker-side: emit heartbeats to a JSON log file."""

    def __init__(self, story_id: str, heartbeat_file: str | None = None) -> None:
        """Initialize heartbeat sender.

        Args:
            story_id: Story ID being worked on by this worker
            heartbeat_file: Path to heartbeats log (default: .spiral/worker_heartbeats.jsonl)
        """
        self.story_id = story_id
        self.heartbeat_file = Path(heartbeat_file or ".spiral/worker_heartbeats.jsonl")
        self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, metadata: dict[str, Any]) -> None:
        """Emit a heartbeat entry to the log.

        Args:
            metadata: Additional metadata (tokens, status, etc.) to include in heartbeat
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "story_id": self.story_id,
            "worker_pid": os.getpid(),
            **metadata,
        }

        try:
            with open(self.heartbeat_file, "a", encoding="utf-8") as f:
                json.dump(entry, f)
                f.write("\n")
        except (IOError, OSError) as e:
            sys.stderr.write(f"[heartbeat] Error writing heartbeat: {e}\n")
            sys.exit(1)


class HeartbeatMonitor:
    """Parent-side: monitor worker heartbeats and detect stalls."""

    def __init__(
        self,
        heartbeat_file: str | None = None,
        crash_log: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        """Initialize heartbeat monitor.

        Args:
            heartbeat_file: Path to heartbeats log (default: .spiral/worker_heartbeats.jsonl)
            crash_log: Path to crash log (default: .spiral/worker_crashes.jsonl)
            timeout_seconds: Time without heartbeat before marking stalled (default: 60)
        """
        self.heartbeat_file = Path(heartbeat_file or ".spiral/worker_heartbeats.jsonl")
        self.crash_log = Path(crash_log or ".spiral/worker_crashes.jsonl")
        self.timeout_seconds = timeout_seconds
        self.crash_log.parent.mkdir(parents=True, exist_ok=True)

    def check_all(self) -> list[dict[str, Any]]:
        """Check all heartbeats and detect stalled workers.

        Returns:
            List of stalled worker records {timestamp, story_id, worker_pid, reason}
        """
        if not self.heartbeat_file.exists():
            return []

        stalled_workers: list[dict[str, Any]] = []
        current_time = time.time()

        # Read all heartbeats and group by worker_pid
        worker_heartbeats: dict[int, dict[str, Any]] = {}
        try:
            with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        pid = entry.get("worker_pid")
                        if pid:
                            worker_heartbeats[pid] = entry
                    except json.JSONDecodeError:
                        continue
        except (IOError, OSError):
            return []

        # Check each worker for staleness
        for pid, last_hb in worker_heartbeats.items():
            try:
                # Parse ISO8601 timestamp
                ts_str = last_hb.get("timestamp", "")
                if ts_str:
                    hb_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                else:
                    continue

                elapsed = current_time - hb_time
                if elapsed > self.timeout_seconds:
                    stalled_worker = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "story_id": last_hb.get("story_id", "unknown"),
                        "worker_pid": pid,
                        "reason": f"No heartbeat for {int(elapsed)}s (timeout: {self.timeout_seconds}s)",
                    }
                    stalled_workers.append(stalled_worker)
                    self._log_crash(stalled_worker)
                    self._terminate_worker(pid)
            except (ValueError, KeyError):
                continue

        return stalled_workers

    def _terminate_worker(self, pid: int) -> None:
        """Terminate a worker process.

        Args:
            pid: Process ID to terminate
        """
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def _log_crash(self, crash_record: dict[str, Any]) -> None:
        """Log a worker crash to the crash log.

        Args:
            crash_record: Crash information to log
        """
        try:
            with open(self.crash_log, "a", encoding="utf-8") as f:
                json.dump(crash_record, f)
                f.write("\n")
        except (IOError, OSError):
            pass


if __name__ == "__main__":
    # CLI for heartbeat monitoring and emission
    if len(sys.argv) < 2:
        print("Usage: worker_heartbeat_monitor.py --emit <story_id> | --monitor", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "--emit":
        if len(sys.argv) < 3:
            print("Usage: worker_heartbeat_monitor.py --emit <story_id>", file=sys.stderr)
            sys.exit(1)
        story_id = sys.argv[2]
        sender = HeartbeatSender(story_id)
        sender.emit({"tokens": 0})
        sys.exit(0)
    elif mode == "--monitor":
        monitor = HeartbeatMonitor()
        stalled = monitor.check_all()
        # Output JSON for each stalled worker (parseable by shell)
        for worker in stalled:
            print(json.dumps(worker))
        sys.exit(0 if not stalled else 1)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
