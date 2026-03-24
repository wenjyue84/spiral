#!/usr/bin/env python3
"""debug_worker_state.py — Dump live worker state and diagnostics (US-1066).

Scans .spiral-workers/worker-N/ directories, reads .heartbeat files, and
checks git HEAD state to produce a JSON report for dashboard consumption
or manual troubleshooting during federated SPIRAL runs.

Output schema:
  {
    "workers": [
      {
        "worker_id": "worker-1",
        "pid": 1234,
        "worktree_path": "/path/to/.spiral-workers/worker-1",
        "current_story_id": "US-123",
        "phase": "I",
        "memory_mb": 256,
        "prd_slice_size": 5
      },
      ...
    ],
    "diagnostics": [
      {"worker_id": "worker-2", "issue": "detached_head", "detail": "..."},
      ...
    ]
  }
"""

import glob
import json
import os
import subprocess
from typing import Any


def _read_heartbeat(hb_path: str) -> dict[str, Any]:
    """Read a .heartbeat JSON file; return empty dict on error."""
    try:
        with open(hb_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except (OSError, json.JSONDecodeError):
        return {}


def _prd_slice_size(worktree_path: str) -> int:
    """Count pending (non-passing) stories in worker's prd.json slice."""
    prd_path = os.path.join(worktree_path, "prd.json")
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd: dict[str, Any] = json.load(f)
        stories: list[dict[str, Any]] = prd.get("userStories", [])
        return sum(1 for s in stories if not s.get("passes"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return 0


def _is_detached_head(worktree_path: str) -> tuple[bool, str]:
    """Return (is_detached, detail_message) for the worktree's HEAD state."""
    try:
        result = subprocess.run(
            ["git", "-C", worktree_path, "symbolic-ref", "--quiet", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # symbolic-ref fails when HEAD is detached
            rev = subprocess.run(
                ["git", "-C", worktree_path, "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            sha = rev.stdout.strip() if rev.returncode == 0 else "unknown"
            return True, f"HEAD is detached at {sha}"
        return False, ""
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def dump_worker_state(workers_base: str = ".spiral-workers") -> dict[str, Any]:
    """Scan workers_base and return structured worker state + diagnostics.

    Args:
        workers_base: Path to the directory containing worker-N subdirectories.
                      Defaults to .spiral-workers relative to cwd.

    Returns:
        Dict with "workers" list and "diagnostics" list.
    """
    workers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    if not os.path.isdir(workers_base):
        return {"workers": workers, "diagnostics": diagnostics}

    pattern = os.path.join(workers_base, "worker-*")
    for worker_dir in sorted(glob.glob(pattern)):
        if not os.path.isdir(worker_dir):
            continue

        worker_id = os.path.basename(worker_dir)
        hb_path = os.path.join(worker_dir, ".heartbeat")
        hb = _read_heartbeat(hb_path)

        pid: int = int(hb.get("pid", 0))
        current_story_id: str = str(hb.get("storyId", "unknown"))
        phase: str = str(hb.get("phase", "unknown"))
        memory_mb: int = int(hb.get("memMb", 0))
        prd_slice_size: int = _prd_slice_size(worker_dir)

        workers.append(
            {
                "worker_id": worker_id,
                "pid": pid,
                "worktree_path": os.path.abspath(worker_dir),
                "current_story_id": current_story_id,
                "phase": phase,
                "memory_mb": memory_mb,
                "prd_slice_size": prd_slice_size,
            }
        )

        # Check for detached HEAD
        detached, detail = _is_detached_head(worker_dir)
        if detached:
            diagnostics.append(
                {
                    "worker_id": worker_id,
                    "issue": "detached_head",
                    "detail": detail,
                }
            )

    return {"workers": workers, "diagnostics": diagnostics}
