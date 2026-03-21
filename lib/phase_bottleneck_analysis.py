"""lib/phase_bottleneck_analysis.py — Phase bottleneck analysis from results.tsv (US-664)."""

from __future__ import annotations

import csv
import statistics
from pathlib import Path


def load_results(path: Path) -> list[dict[str, str]]:
    """Load results.tsv into a list of row dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def filter_results(
    rows: list[dict[str, str]],
    iteration_min: int | None = None,
    iteration_max: int | None = None,
    story_status: str | None = None,
) -> list[dict[str, str]]:
    """Filter results by iteration range and story status.

    Args:
        rows: List of result rows
        iteration_min: Minimum spiral_iter (inclusive), None for no min
        iteration_max: Maximum spiral_iter (inclusive), None for no max
        story_status: Filter by status field (exact match), None for all

    Returns:
        Filtered list of rows
    """
    filtered = []
    for row in rows:
        # Check iteration range
        if iteration_min is not None or iteration_max is not None:
            try:
                it = int(row.get("spiral_iter", 0) or 0)
            except (ValueError, TypeError):
                continue
            if iteration_min is not None and it < iteration_min:
                continue
            if iteration_max is not None and it > iteration_max:
                continue

        # Check status
        if story_status is not None:
            if (row.get("status") or "").strip() != story_status:
                continue

        filtered.append(row)

    return filtered


def compute_phase_bottlenecks(
    filtered_rows: list[dict[str, str]],
) -> list[dict[str, str | float]]:
    """Compute phase bottleneck metrics from filtered results.

    Returns list of dicts with:
        {name, totalTime, avgPerStory, percentOfIteration, recommendation}
    """
    phase_data: dict[str, list[float]] = {}

    for row in filtered_rows:
        phase = (row.get("phase") or "").strip().upper() or "UNKNOWN"
        try:
            duration = float(row.get("duration_sec", 0) or 0)
        except (ValueError, TypeError):
            duration = 0.0

        if phase not in phase_data:
            phase_data[phase] = []
        phase_data[phase].append(duration)

    # Calculate totals
    total_iteration_time = sum(duration for durations in phase_data.values() for duration in durations)

    bottlenecks: list[dict[str, str | float]] = []

    for phase in sorted(phase_data.keys()):
        durations = phase_data[phase]
        if not durations:
            continue

        total_time = sum(durations)
        avg_per_story = statistics.mean(durations)
        percent_of_iteration = (total_time / total_iteration_time * 100) if total_iteration_time > 0 else 0.0

        recommendation = _generate_recommendation(
            phase,
            total_time,
            avg_per_story,
            percent_of_iteration,
        )

        bottlenecks.append(
            {
                "name": f"Phase {phase}",
                "totalTime": round(total_time, 1),
                "avgPerStory": round(avg_per_story, 1),
                "percentOfIteration": round(percent_of_iteration, 1),
                "recommendation": recommendation,
            }
        )

    return bottlenecks


def _generate_recommendation(
    phase: str,
    total_time: float,
    avg_per_story: float,
    percent_of_iteration: float,
) -> str:
    """Generate optimization recommendation based on phase metrics.

    Args:
        phase: Phase name (R, T, S, M, I, V, C)
        total_time: Total time spent in phase (seconds)
        avg_per_story: Average time per story (seconds)
        percent_of_iteration: Percentage of total iteration time

    Returns:
        Actionable recommendation text
    """
    # Check most specific conditions first
    if avg_per_story > 300:
        return "reduce scope: stories are spending excessive time in this phase"
    elif total_time > 1800:
        return "optimize: phase takes too long in aggregate"
    elif percent_of_iteration > 50:
        return "parallelize: this phase dominates iteration time"
    elif percent_of_iteration > 30:
        return "increase workers: phase accounts for significant overhead"
    else:
        return "monitor: phase is within normal parameters"
