#!/usr/bin/env python3
"""worker_api.py — Worker pool status API for real-time monitoring.

Provides WorkerPoolAPI class to query worker heartbeats and return live status
for dashboard consumption. Used by GET /api/workers endpoint.

Features:
- Reads .spiral-workers/worker-N/.heartbeat files (JSON format)
- Calculates elapsed time since last heartbeat
- Detects timeout state when heartbeat is stale beyond SPIRAL_WORKER_TIMEOUT (default 300s)
- Timeout threshold can be overridden via SPIRAL_WORKER_TIMEOUT env var or constructor param
- Gracefully handles missing workers or heartbeat directory
- Returns structured response: {worker_id, current_story, elapsed_time_sec, state}
"""

import glob
import json
import os
import time
from typing import Any


class WorkerPoolAPI:
    """Query and format worker pool status from heartbeat files."""

    def __init__(self, heartbeat_dir: str = ".spiral-workers", timeout_seconds: int | None = None):
        """Initialize with heartbeat directory path.

        Args:
            heartbeat_dir: Base directory containing worker-N subdirs with .heartbeat files
            timeout_seconds: Timeout threshold in seconds. Defaults to SPIRAL_WORKER_TIMEOUT env var,
                           or 300 if not set.
        """
        self.heartbeat_dir = heartbeat_dir

        # Allow timeout to be overridden via parameter, env var, or default
        if timeout_seconds is not None:
            self.timeout_threshold = timeout_seconds
        else:
            env_timeout = os.environ.get("SPIRAL_WORKER_TIMEOUT", "300")
            self.timeout_threshold = int(env_timeout) if env_timeout else 300

    def get_workers(self) -> list[dict[str, Any]]:
        """Return list of worker status dicts from heartbeat files.

        Returns:
            List of dicts with keys:
                - worker_id (str): e.g. "worker-1", "worker-2", "worker-3"
                - current_story (str): e.g. "US-123" or "unknown"
                - elapsed_time_sec (int): seconds since last heartbeat update
                - state (str): "alive", "timeout", or "idle"

        Handles missing directory gracefully by returning empty list.
        Workers are marked "timeout" if stale beyond the timeout threshold
        (SPIRAL_WORKER_TIMEOUT env var, default 300 seconds).
        """
        workers: list[dict[str, Any]] = []

        # Check if heartbeat directory exists
        if not os.path.isdir(self.heartbeat_dir):
            return workers

        now = time.time()

        # Scan for .spiral-workers/worker-N/.heartbeat files
        pattern = os.path.join(self.heartbeat_dir, "worker-*", ".heartbeat")
        for hb_file in sorted(glob.glob(pattern)):
            try:
                # Extract worker_id from path: .spiral-workers/worker-N/.heartbeat → worker-N
                worker_dir = os.path.dirname(hb_file)  # .spiral-workers/worker-N
                worker_id = os.path.basename(worker_dir)  # worker-N (keep full name)

                # Read heartbeat JSON
                with open(hb_file, encoding="utf-8") as f:
                    hb_data = json.load(f)

                # Extract timestamp; skip if missing (invalid heartbeat)
                ts = hb_data.get("ts")
                if ts is None:
                    continue

                # Extract fields with sensible defaults
                current_story = str(hb_data.get("storyId", "unknown"))
                elapsed_time_sec = int(now - ts)

                # Determine state based on elapsed time
                if elapsed_time_sec > self.timeout_threshold:
                    state = "timeout"
                else:
                    state = "alive"

                workers.append(
                    {
                        "worker_id": worker_id,
                        "current_story": current_story,
                        "elapsed_time_sec": elapsed_time_sec,
                        "state": state,
                    }
                )

            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                # Skip malformed heartbeat files
                pass

        return workers
