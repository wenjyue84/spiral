"""lib/worker_swimlanes.py — Worker phase duration tracking and swimlane visualization (US-652).

Parses phase timing data to compute per-worker phase durations across iterations.
Returns JSON for interactive swimlane chart visualization.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_phase_trace(path: Path) -> dict[str, Any]:
    """Load phase-trace-data.json into a dict."""
    if not path.exists():
        return {"iterations": []}
    with open(path, encoding="utf-8") as f:
        data: Any = json.load(f)
        return data if isinstance(data, dict) else {"iterations": []}


def compute_swimlane_data(
    phase_trace: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute swimlane data from phase trace.

    Returns list of {worker_id, iteration, phases: [{phase_name, duration_ms, start_time, status}]}

    For now, returns worker_id 0 since single-worker mode. Multi-worker support added when
    parallel workers are fully integrated into phase tracing.
    """
    swimlanes: list[dict[str, Any]] = []

    iterations = phase_trace.get("iterations", [])
    for iter_data in iterations:
        iter_num = iter_data.get("iter", 0)
        phases_list = iter_data.get("phases", [])

        # Single worker for now; multi-worker support when workers write to phase_trace
        if phases_list:
            swimlanes.append({
                "worker_id": 0,
                "iteration": iter_num,
                "phases": _format_phases(phases_list),
            })

    return swimlanes


def _format_phases(phases_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format phases for swimlane output.

    Each phase has: phase_name, duration_ms (computed from line counts or 0),
    start_time (ISO8601), and status (success/skipped based on label).
    """
    formatted = []
    current_ms = 0

    for phase_data in phases_list:
        phase_name = phase_data.get("phase", "UNKNOWN")
        label = phase_data.get("label", "")
        lines = phase_data.get("lines", [])

        # Estimate duration: 100ms per line or 50ms minimum
        duration_ms = max(50, len(lines) * 100)
        start_time = datetime.now(timezone.utc).isoformat()
        status = "skipped" if "Skipping" in label else "success"

        formatted.append({
            "phase_name": phase_name,
            "duration_ms": duration_ms,
            "start_time": start_time,
            "status": status,
        })
        current_ms += duration_ms

    return formatted


def get_swimlane_data(phase_trace_path: Path) -> list[dict[str, Any]]:
    """Load phase trace and return swimlane JSON for dashboard visualization."""
    trace = load_phase_trace(phase_trace_path)
    return compute_swimlane_data(trace)


def main() -> None:
    """CLI entry point."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate worker swimlane data")
    parser.add_argument(
        "--phase-trace",
        default=".spiral/phase-trace-data.json",
        help="Path to phase-trace-data.json",
    )
    args = parser.parse_args()

    swimlanes = get_swimlane_data(Path(args.phase_trace))
    print(json.dumps(swimlanes, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
