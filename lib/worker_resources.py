"""worker_resources.py — Worker resource usage metrics for dashboard.

Reads .spiral/worker_heartbeats.json and exposes metrics for
GET /api/dashboard/worker-resources. Persists snapshots to
.spiral/worker-resources-history.json for post-run analysis.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any


def read_worker_resources(spiral_dir: str) -> list[dict[str, Any]]:
    """Read worker metrics from .spiral/worker_heartbeats.json."""
    hb_file = os.path.join(spiral_dir, "worker_heartbeats.json")
    if not os.path.exists(hb_file):
        return []
    try:
        with open(hb_file, encoding="utf-8") as f:
            raw: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    return [
        {
            "worker_id": str(d.get("worker_id", wid)),
            "memory_peak_mb": float(d.get("memory_peak_mb", 0)),
            "avg_cpu_percent": float(d.get("avg_cpu_percent", 0)),
            "stories_completed": int(d.get("stories_completed", 0)),
            "uptime_seconds": int(d.get("uptime_seconds", 0)),
        }
        for wid, d in raw.items()
        if isinstance(d, dict)
    ]


def append_history(spiral_dir: str, metrics: list[dict[str, Any]]) -> None:
    """Append timestamped snapshot to .spiral/worker-resources-history.json."""
    hist_file = os.path.join(spiral_dir, "worker-resources-history.json")
    history: list[dict[str, Any]] = []
    if os.path.exists(hist_file):
        try:
            with open(hist_file, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    history = loaded
        except (json.JSONDecodeError, OSError):
            pass
    history.append({"timestamp": datetime.now(timezone.utc).isoformat(), "workers": metrics})
    try:
        with open(hist_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass
