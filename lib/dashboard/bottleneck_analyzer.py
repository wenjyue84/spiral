"""lib/dashboard/bottleneck_analyzer.py — Phase duration variance analyzer (US-670).

Analyzes results.tsv to rank phases by average duration and coefficient of variance.
Returns metrics for performance tuning and optimization targeting.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path


class BottleneckAnalyzer:
    """Analyzes phase duration variance from results.tsv."""

    def __init__(self, results_path: Path | str = ".spiral/results.tsv"):
        """Initialize analyzer with path to results.tsv."""
        self.results_path = Path(results_path)

    def analyze(self) -> list[dict[str, str | int | float]]:
        """Analyze phase durations and return sorted by avg_duration_ms descending.

        Returns:
            List of dicts with {phase, avg_duration_ms, variance, story_count}
            sorted by avg_duration_ms descending.
            Only includes phases with story_count > 0.
        """
        if not self.results_path.exists():
            return []

        # Load results
        phase_durations: dict[str, list[float]] = {}

        try:
            with open(self.results_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                if reader.fieldnames is None:
                    return []

                for row in reader:
                    phase = (row.get("phase") or "").strip().upper() or "UNKNOWN"
                    try:
                        duration_sec = float(row.get("duration_sec", 0) or 0)
                    except (ValueError, TypeError):
                        continue

                    if duration_sec > 0:  # Only positive durations
                        if phase not in phase_durations:
                            phase_durations[phase] = []
                        phase_durations[phase].append(duration_sec)

        except Exception:
            return []

        # Calculate metrics
        result: list[dict[str, str | int | float]] = []

        for phase in sorted(phase_durations.keys()):
            durations = phase_durations[phase]
            if not durations:
                continue

            story_count = len(durations)
            avg_duration_sec = statistics.mean(durations)
            avg_duration_ms = avg_duration_sec * 1000

            # Coefficient of variance (std dev / mean)
            if story_count > 1:
                std_dev = statistics.stdev(durations)
                variance = std_dev / avg_duration_sec if avg_duration_sec > 0 else 0.0
            else:
                # Single sample: no variance
                variance = 0.0

            result.append(
                {
                    "phase": phase,
                    "avg_duration_ms": round(avg_duration_ms, 1),
                    "variance": round(variance, 3),
                    "story_count": story_count,
                }
            )

        # Sort by avg_duration_ms descending
        result.sort(key=lambda x: x["avg_duration_ms"], reverse=True)

        return result
