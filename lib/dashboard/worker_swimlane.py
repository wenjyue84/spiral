"""lib/dashboard/worker_swimlane.py — Worker phase status and swimlane rendering.

Reads .spiral/_checkpoint.json and worker heartbeat files to determine each active
worker's current phase, start time, and estimated remaining time. Powers the
GET /api/dashboard/worker-phase-swimlane endpoint.
"""

from __future__ import annotations

import glob
import json
import time
from pathlib import Path
from typing import Any


def get_worker_phase_status(spiral_home: str = ".") -> list[dict[str, Any]]:
    """Get phase status for each active worker.

    Reads .spiral/_checkpoint.json for global phase and start time, then reads
    .spiral-workers/worker-N/.heartbeat files for per-worker phase and timing.

    Args:
        spiral_home: Root directory containing .spiral and .spiral-workers

    Returns:
        List of dicts with keys:
            - worker_id (str): e.g. "worker-1", "worker-2"
            - current_phase (str): phase from heartbeat (e.g. "Phase I")
            - phase_start_time (float): Unix timestamp when phase started
            - estimated_completion_seconds (float): Estimated seconds until phase ends

        Returns empty list if no checkpoint or no active workers found.
    """
    spiral_home_path = Path(spiral_home)
    checkpoint_path = spiral_home_path / ".spiral" / "_checkpoint.json"
    workers_dir = spiral_home_path / ".spiral-workers"

    # Read checkpoint to get global phase info
    checkpoint: dict[str, Any] | None = None
    if checkpoint_path.exists():
        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                checkpoint = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    if not checkpoint or "phase" not in checkpoint or "ts" not in checkpoint:
        return []

    global_phase = checkpoint.get("phase", "unknown")
    phase_start_time = float(checkpoint.get("ts", 0))
    now = time.time()

    # Scan for active workers
    workers: list[dict[str, Any]] = []

    if not workers_dir.exists():
        return workers

    # Pattern: .spiral-workers/worker-N/.heartbeat
    pattern = str(workers_dir / "worker-*" / ".heartbeat")
    for hb_file in sorted(glob.glob(pattern)):
        try:
            with open(hb_file, encoding="utf-8") as f:
                hb_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # Extract worker_id from path
        worker_dir = Path(hb_file).parent
        worker_id = worker_dir.name  # e.g., "worker-1"

        # Get phase from heartbeat, fall back to global phase
        worker_phase = hb_data.get("phase", global_phase)

        # Elapsed time since phase started
        elapsed_sec = max(0.0, now - phase_start_time)

        # Estimate remaining time (use "medium" as default complexity if unknown)
        # TODO: Could enhance with actual story complexity from prd.json
        estimated_remaining = estimate_phase_remaining_time(elapsed_sec, "medium")

        workers.append(
            {
                "worker_id": worker_id,
                "current_phase": worker_phase,
                "phase_start_time": phase_start_time,
                "estimated_completion_seconds": round(estimated_remaining, 1),
            }
        )

    return workers


def estimate_phase_remaining_time(elapsed_sec: float, complexity: str) -> float:
    """Estimate remaining time for a phase based on elapsed time and complexity.

    Uses heuristic timing models by complexity:
    - small: 5 min typical, 8 min max
    - medium: 15 min typical, 25 min max
    - large: 30 min typical, 50 min max
    - critical: 45 min typical, 90 min max

    Args:
        elapsed_sec: Seconds elapsed in the phase
        complexity: One of "small", "medium", "large", "critical"

    Returns:
        Estimated seconds remaining (0 if already exceeded typical time)
    """
    # Define phase timing thresholds (in seconds)
    timing_models: dict[str, tuple[float, float]] = {
        "small": (300, 480),  # 5 min typical, 8 min max
        "medium": (900, 1500),  # 15 min typical, 25 min max
        "large": (1800, 3000),  # 30 min typical, 50 min max
        "critical": (2700, 5400),  # 45 min typical, 90 min max
    }

    typical_sec, max_sec = timing_models.get(complexity.lower(), (900, 1500))

    # If already past typical time, estimate remaining as 20% of max
    if elapsed_sec >= typical_sec:
        remaining = max(0.0, max_sec - elapsed_sec)
        return remaining * 0.2  # Diminishing returns after typical time

    # Linear interpolation: remaining = typical - elapsed
    remaining = typical_sec - elapsed_sec
    return max(0.0, remaining)
