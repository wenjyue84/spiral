#!/usr/bin/env python3
"""timing_analyzer.py — Cross-phase timing analysis with bottleneck detection.

Parses spiral_events.jsonl to extract phase_start/phase_end events,
computes per-phase duration by iteration, identifies outliers (>mean+2sigma),
and generates a formatted grid showing iteration x phase timing with outlier flags.

Usage:
    python lib/observability/timing_analyzer.py --events spiral_events.jsonl --format grid
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class PhaseEventPair:
    """Start and end event pair for a single phase in a single iteration."""

    phase: str
    iteration: int
    start_ts: float
    end_ts: float

    @property
    def duration_s(self) -> float:
        """Duration in seconds."""
        return max(0.0, self.end_ts - self.start_ts)


def parse_events(event_file: str) -> dict[tuple[int, str], float]:
    """Parse spiral_events.jsonl and extract per-iteration per-phase durations.

    Returns dict[(iteration, phase)] = duration_seconds
    Handles both explicit duration_s field and computed timestamps.
    """
    durations: dict[tuple[int, str], float] = {}

    if not os.path.isfile(event_file):
        return durations

    # First pass: collect all phase_start and phase_end events
    events_by_phase: dict[tuple[int, str], dict[str, Any]] = {}

    try:
        with open(event_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = record.get("event")
                phase = record.get("phase")
                iteration = record.get("iteration")

                if not phase or iteration is None:
                    continue

                key = (iteration, phase)

                # Store phase_start with timestamp
                if event_type == "phase_start":
                    ts = record.get("ts")
                    if ts:
                        if key not in events_by_phase:
                            events_by_phase[key] = {}
                        events_by_phase[key]["start_ts"] = _parse_timestamp(ts)

                # Store phase_end with timestamp or duration
                elif event_type == "phase_end":
                    # First prefer explicit duration_s field
                    if "duration_s" in record:
                        durations[key] = float(record["duration_s"])
                    else:
                        # Fall back to computed duration from ts
                        ts = record.get("ts")
                        if ts:
                            if key not in events_by_phase:
                                events_by_phase[key] = {}
                            events_by_phase[key]["end_ts"] = _parse_timestamp(ts)

    except OSError:
        return durations

    # Second pass: compute durations from start/end timestamps
    for key, events in events_by_phase.items():
        if key not in durations:  # Only if not already set by duration_s
            if "start_ts" in events and "end_ts" in events:
                duration = max(0.0, events["end_ts"] - events["start_ts"])
                durations[key] = duration

    return durations


def _parse_timestamp(ts: str) -> float:
    """Parse ISO 8601 timestamp to Unix epoch seconds.

    Handles formats like '2026-03-23T22:04:01Z' and numeric timestamps.
    """
    if isinstance(ts, (int, float)):
        return float(ts)

    if isinstance(ts, str):
        try:
            # Try parsing ISO 8601 format
            from datetime import datetime

            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, AttributeError):
            pass

    return 0.0


def compute_stats(durations: dict[tuple[int, str], float]) -> dict[str, Any]:
    """Compute per-phase statistics (mean, stddev, outliers).

    Returns dict with keys:
      {phase: {"mean": float, "sigma": float, "outliers": set[int]}}
    where outliers are iteration numbers with duration > mean + 2*sigma.
    """
    stats: dict[str, dict[str, Any]] = {}

    # Group durations by phase
    by_phase: dict[str, list[float]] = defaultdict(list)
    for (iteration, phase), duration in durations.items():
        by_phase[phase].append(duration)

    # Compute stats for each phase
    for phase, durations_list in by_phase.items():
        if not durations_list:
            continue

        mean = statistics.mean(durations_list)
        sigma = statistics.stdev(durations_list) if len(durations_list) > 1 else 0.0
        threshold = mean + 2 * sigma

        # Find outlier iterations
        outliers = set()
        for (iteration, p), duration in durations.items():
            if p == phase and duration > threshold:
                outliers.add(iteration)

        stats[phase] = {
            "mean": mean,
            "sigma": sigma,
            "threshold": threshold,
            "outliers": outliers,
            "count": len(durations_list),
        }

    return stats


def identify_outliers(stats: dict[str, Any]) -> dict[tuple[int, str], bool]:
    """Build outlier map: (iteration, phase) -> True if outlier.

    Returns dict[(iteration, phase)] = True (outlier) or missing (normal).
    """
    outlier_map: dict[tuple[int, str], bool] = {}

    for phase, phase_stats in stats.items():
        for iteration in phase_stats["outliers"]:
            outlier_map[(iteration, phase)] = True

    return outlier_map


def format_timing_grid(
    durations: dict[tuple[int, str], float],
    stats: dict[str, Any],
    outlier_map: dict[tuple[int, str], bool],
) -> str:
    """Format timing report as an iteration x phase grid.

    Outliers are flagged with *** prefix.
    Returns formatted string suitable for terminal output.
    """
    if not durations:
        return "No phase timing data found in events."

    # Collect all iterations and phases
    iterations = sorted(set(it for it, _ in durations.keys()))
    phases = sorted(set(ph for _, ph in durations.keys()))

    # Build header row
    lines = []
    header = "Iteration" + "".join(f" {ph:>8}" for ph in phases)
    lines.append(header)
    lines.append("-" * len(header))

    # Build data rows
    for iteration in iterations:
        row = f"{iteration:<9}"
        for phase in phases:
            key = (iteration, phase)
            if key in durations:
                duration = durations[key]
                is_outlier = outlier_map.get(key, False)
                # Format: duration with *** prefix if outlier
                if is_outlier:
                    row += f" ***{duration:>5.1f}s"
                else:
                    row += f"  {duration:>6.1f}s"
            else:
                row += "       -"
        lines.append(row)

    # Add stats footer
    lines.append("")
    lines.append("Outlier Thresholds (mean + 2σ):")
    for phase in phases:
        if phase in stats:
            phase_stats = stats[phase]
            threshold = phase_stats["threshold"]
            lines.append(
                f"  {phase}: {phase_stats['mean']:.1f}s (σ={phase_stats['sigma']:.1f}s) → threshold {threshold:.1f}s"
            )

    return "\n".join(lines)


def format_timing_json(
    durations: dict[tuple[int, str], float],
    stats: dict[str, Any],
    outlier_map: dict[tuple[int, str], bool],
) -> str:
    """Format timing report as JSON."""
    # Collect all iterations and phases
    iterations = sorted(set(it for it, _ in durations.keys()))
    phases = sorted(set(ph for _, ph in durations.keys()))

    # Build grid
    grid = {}
    for iteration in iterations:
        row = {}
        for phase in phases:
            key = (iteration, phase)
            if key in durations:
                row[phase] = {
                    "duration_s": durations[key],
                    "is_outlier": outlier_map.get(key, False),
                }
        grid[str(iteration)] = row

    # Build result
    result = {
        "grid": grid,
        "stats": {
            phase: {
                "mean_s": s["mean"],
                "sigma_s": s["sigma"],
                "threshold_s": s["threshold"],
                "outlier_count": len(s["outliers"]),
            }
            for phase, s in stats.items()
        },
    }

    return json.dumps(result, indent=2)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Analyze phase timing from spiral_events.jsonl with outlier detection")
    parser.add_argument(
        "--events",
        default=".spiral/spiral_events.jsonl",
        help="Path to spiral_events.jsonl (default: .spiral/spiral_events.jsonl)",
    )
    parser.add_argument(
        "--format",
        choices=["grid", "json"],
        default="grid",
        help="Output format (default: grid)",
    )
    args = parser.parse_args()

    # Parse events
    durations = parse_events(args.events)
    if not durations:
        print("No phase timing data found.", file=sys.stderr)
        return 1

    # Compute stats
    stats = compute_stats(durations)

    # Identify outliers
    outlier_map = identify_outliers(stats)

    # Format output
    if args.format == "json":
        print(format_timing_json(durations, stats, outlier_map))
    else:
        print(format_timing_grid(durations, stats, outlier_map))

    return 0


if __name__ == "__main__":
    sys.exit(main())
