"""lib/retry_analysis.py — Retry distribution analysis by phase from results.tsv (US-655)."""

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


def compute_retry_stats(results: list[dict[str, str]]) -> dict[str, dict[str, float | int]]:
    """Compute retry statistics grouped by phase.

    Returns dict with phase as key and stats dict as value:
        {phase: {count, mean, median, max, retry_rate, story_count}}
    """
    phase_retries: dict[str, list[int]] = {}

    for row in results:
        phase = row.get("phase", "").upper() or "UNKNOWN"
        try:
            retry_count = int(row.get("retry_count", 0) or 0)
        except (ValueError, TypeError):
            retry_count = 0

        if phase not in phase_retries:
            phase_retries[phase] = []
        phase_retries[phase].append(retry_count)

    stats: dict[str, dict[str, float | int]] = {}
    sum(count for counts in phase_retries.values() for count in counts)
    len(results)

    for phase, retries in sorted(phase_retries.items()):
        if not retries:
            continue

        phase_total_retries = sum(retries)
        stats[phase] = {
            "count": len(retries),
            "mean": statistics.mean(retries),
            "median": statistics.median(retries),
            "max": max(retries),
            "retry_rate": phase_total_retries / len(retries) if retries else 0.0,
            "story_count": len(retries),
        }

    return stats


def compute_retry_rates(
    results: list[dict[str, str]],
) -> list[dict[str, float | int | str]]:
    """Compute per-phase retry rates sorted by rate descending.

    Returns list of dicts: [{phase: 'I', retry_rate: 0.35, story_count: 7}, ...]
    """
    stats = compute_retry_stats(results)

    # Sort by retry_rate descending
    sorted_phases = sorted(
        stats.items(),
        key=lambda item: float(item[1]["retry_rate"]),
        reverse=True,
    )

    return [
        {
            "phase": phase,
            "retry_rate": round(float(data["retry_rate"]), 4),
            "story_count": int(data["story_count"]),
        }
        for phase, data in sorted_phases
    ]
