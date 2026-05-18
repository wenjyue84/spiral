#!/usr/bin/env python3
"""Phase bottleneck analyzer for results.jsonl — compute per-phase metrics and recommendations."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


class PhaseBottleneckAnalyzer:
    """Analyze phase execution bottlenecks from results.jsonl."""

    def __init__(self) -> None:
        """Initialize the analyzer."""
        self.phase_data: dict[str, dict[str, Any]] = {}
        self.total_loop_time: float = 0.0

    def analyze(self, results_file: Path | str) -> dict[str, Any]:
        """Analyze results.jsonl and compute per-phase metrics.

        Args:
            results_file: Path to results.jsonl file

        Returns:
            Dict with 'phases' list containing per-phase metrics
        """
        results_file = Path(results_file)

        if not results_file.exists():
            return {"phases": []}

        # Read and parse JSONL
        entries: list[dict[str, Any]] = []
        try:
            with open(results_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            return {"phases": []}

        # Group by phase name, extract duration_ms
        phase_durations: dict[str, list[float]] = {}
        for entry in entries:
            phase = (entry.get("phase") or "UNKNOWN").upper()
            # Duration can be in ms (duration_ms) or seconds (duration_sec)
            duration_ms = entry.get("duration_ms", 0)
            if duration_ms == 0:
                # Try duration_sec if duration_ms not present
                duration_sec = entry.get("duration_sec", 0)
                duration_ms = (duration_sec or 0) * 1000

            if duration_ms > 0:
                if phase not in phase_durations:
                    phase_durations[phase] = []
                phase_durations[phase].append(duration_ms / 1000.0)  # Convert to seconds

        # Compute total loop time
        self.total_loop_time = sum(d for durations in phase_durations.values() for d in durations)

        # Compute statistics per phase
        phases: list[dict[str, Any]] = []
        for phase in sorted(phase_durations.keys()):
            durations = phase_durations[phase]
            if not durations:
                continue

            total_time = sum(durations)
            iteration_count = len(durations)
            mean_duration = statistics.mean(durations)
            stddev = statistics.stdev(durations) if len(durations) > 1 else 0.0
            percent_of_total = (total_time / self.total_loop_time * 100) if self.total_loop_time > 0 else 0.0

            recommendation = self._generate_recommendation(phase, total_time, mean_duration, percent_of_total)

            phases.append({
                "phase_name": f"Phase {phase}",
                "mean_duration_sec": round(mean_duration, 2),
                "stddev_sec": round(stddev, 2),
                "total_time_sec": round(total_time, 2),
                "iteration_count": iteration_count,
                "percent_of_total": round(percent_of_total, 1),
                "bottleneck_rank": 0,  # Will be set later
                "recommendation": recommendation,
            })

        # Sort by total_time DESC and assign bottleneck ranks
        phases.sort(key=lambda x: x["total_time_sec"], reverse=True)
        for idx, phase in enumerate(phases, 1):
            phase["bottleneck_rank"] = idx

        return {"phases": phases}

    def to_ascii_table(self, analysis: dict[str, Any]) -> str:
        """Format analysis results as ASCII table with formatting.

        Args:
            analysis: Result from analyze() method

        Returns:
            Human-readable ASCII table string
        """
        phases = analysis.get("phases", [])
        if not phases:
            return "[spiral] No phase data found in results.jsonl"

        # Build table
        lines: list[str] = []
        lines.append("")
        lines.append("  Phase Bottleneck Analysis")
        lines.append("  " + "=" * 80)
        lines.append("")

        # Header
        header = "  Phase      Mean (s)  Stddev (s)  Total (s)  Count  % Loop  Rank"
        lines.append(header)
        lines.append("  " + "-" * 76)

        # Rows
        for phase in phases:
            rank = phase["bottleneck_rank"]
            phase_name = phase["phase_name"]
            mean_dur = phase["mean_duration_sec"]
            stddev = phase["stddev_sec"]
            total = phase["total_time_sec"]
            count = phase["iteration_count"]
            percent = phase["percent_of_total"]

            # Highlight top 3 bottlenecks with bold markers
            rank_str = str(rank)
            if rank <= 3:
                rank_str = f"[{rank}]"

            line = f"  {phase_name:<10} {mean_dur:>8.2f}  {stddev:>10.2f}  {total:>9.2f}  {count:>5}  {percent:>5.1f}%  {rank_str:>4}"
            lines.append(line)

        lines.append("  " + "-" * 76)
        lines.append("")

        # Recommendations for top 3 bottlenecks
        lines.append("  Top 3 Bottlenecks & Recommendations:")
        lines.append("  " + "-" * 76)
        for phase in phases[:3]:
            phase_name = phase["phase_name"]
            percent = phase["percent_of_total"]
            recommendation = phase["recommendation"]
            lines.append(f"  {phase_name:<15} {percent:>5.1f}% — {recommendation}")
        lines.append("")

        return "\n".join(lines)

    def to_json_lines(self, analysis: dict[str, Any]) -> str:
        """Format analysis results as newline-delimited JSON.

        Args:
            analysis: Result from analyze() method

        Returns:
            JSONL string (one JSON object per line)
        """
        lines: list[str] = []
        for phase in analysis.get("phases", []):
            lines.append(json.dumps(phase))
        return "\n".join(lines)

    def _generate_recommendation(
        self,
        phase: str,
        total_time: float,
        mean_duration: float,
        percent_of_total: float,
    ) -> str:
        """Generate optimization recommendation based on phase metrics.

        Args:
            phase: Phase name
            total_time: Total time spent in phase (seconds)
            mean_duration: Average duration per execution (seconds)
            percent_of_total: Percentage of total loop time

        Returns:
            Actionable recommendation text
        """
        # Check most specific conditions first
        if mean_duration > 300:
            return "reduce scope: stories are spending excessive time in this phase"
        elif total_time > 1800:
            return "optimize: phase takes too long in aggregate"
        elif percent_of_total > 50:
            return "parallelize: this phase dominates iteration time"
        elif percent_of_total > 30:
            return "increase workers: phase accounts for significant overhead"
        else:
            return "monitor: phase is within normal parameters"
