#!/usr/bin/env python3
"""
Phase Bottleneck Analyzer — identifies performance bottlenecks in SPIRAL phase execution.

Reads results.jsonl (per-phase timing data across iterations), computes statistics,
and provides actionable optimization recommendations.
"""

import argparse
import json
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List

PHASE_RECOMMENDATIONS = {
    "A": {
        "threshold": 20,
        "message": "Phase A (AI Suggest) exceeded 20% of loop time. Consider: caching story candidates, parallelizing suggestion logic.",
    },
    "R": {
        "threshold": 40,
        "message": "Phase R (Research) exceeded 40% of loop time (typical bottleneck). Optimization: enable research cache, limit web searches per story, batch API calls.",
    },
    "T": {
        "threshold": 25,
        "message": "Phase T (Test Synth) exceeded 25% of loop time. Consider: reduce test synthesis scope, parallelize test generation.",
    },
    "S": {
        "threshold": 10,
        "message": "Phase S (Story Validate) exceeded 10% of loop time. Review: constitution checks, goal alignment, dedup logic.",
    },
    "E": {
        "threshold": 15,
        "message": "Phase E (Enrichment) exceeded 15% of loop time. Consider: caching enrichment results, limiting context build per story.",
    },
    "M": {
        "threshold": 5,
        "message": "Phase M (Merge) exceeded 5% of loop time. Review: merge logic, prd.json patch operations.",
    },
    "I": {
        "threshold": 35,
        "message": "Phase I (Implementation) exceeded 35% of loop time. Optimization: increase parallel workers, reduce per-story retry attempts, optimize decompose logic.",
    },
    "V": {
        "threshold": 20,
        "message": "Phase V (Validate) exceeded 20% of loop time. Consider: reduce validation scope, parallelize test execution, cache test results.",
    },
}


class PhaseBottleneckAnalyzer:
    """Analyzes phase execution times and identifies optimization opportunities."""

    def analyze(self, results_file: Path) -> Dict[str, Any]:
        """
        Analyze results.jsonl and compute per-phase statistics.

        Args:
            results_file: Path to results.jsonl (JSONL format)

        Returns:
            Dict with: iteration_count, phases (sorted by total_time_sec DESC),
            total_time_sec, and per-phase: mean_duration_sec, stdev_duration_sec,
            total_time_sec, percent_of_total, bottleneck_rank, recommendation
        """
        results_file = Path(results_file)

        if not results_file.exists():
            return {
                "phases": [],
                "total_time_sec": 0.0,
                "iteration_count": 0,
            }

        # Parse JSONL
        phase_data: Dict[str, List[float]] = {}
        iterations = set()

        try:
            with open(results_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    phase = obj.get("phase")
                    duration = obj.get("duration_sec")
                    iteration = obj.get("iteration")

                    if phase and duration is not None:
                        if phase not in phase_data:
                            phase_data[phase] = []
                        phase_data[phase].append(duration)
                        if iteration is not None:
                            iterations.add(iteration)
        except (json.JSONDecodeError, IOError):
            return {
                "phases": [],
                "total_time_sec": 0.0,
                "iteration_count": 0,
            }

        if not phase_data:
            return {
                "phases": [],
                "total_time_sec": 0.0,
                "iteration_count": len(iterations),
            }

        # Compute statistics
        total_time: float = 0.0
        phases_list: List[Dict[str, Any]] = []

        for phase_name in sorted(phase_data.keys()):
            durations = phase_data[phase_name]
            total = sum(durations)
            total_time += total

            phase_info: Dict[str, Any] = {
                "phase_name": phase_name,
                "mean_duration_sec": mean(durations),
                "stdev_duration_sec": stdev(durations) if len(durations) > 1 else 0.0,
                "total_time_sec": total,
                "sample_count": len(durations),
            }
            phases_list.append(phase_info)

        # Add percentages and recommendations
        for phase_info in phases_list:
            total_time_sec: float = float(phase_info["total_time_sec"])
            percent: float = (total_time_sec / total_time * 100) if total_time > 0 else 0.0
            phase_info["percent_of_total"] = percent

            rec_config: Dict[str, Any] = PHASE_RECOMMENDATIONS.get(phase_info["phase_name"], {})
            threshold: int = rec_config.get("threshold", 100)
            if percent > threshold:
                phase_info["recommendation"] = rec_config.get("message", "")
            else:
                phase_info["recommendation"] = ""

        # Sort by total_time_sec descending
        phases_list.sort(key=lambda p: float(p["total_time_sec"]), reverse=True)

        # Add bottleneck ranks
        for rank, phase_info in enumerate(phases_list, start=1):
            phase_info["bottleneck_rank"] = rank

        return {
            "phases": phases_list,
            "total_time_sec": total_time,
            "iteration_count": len(iterations),
        }

    def format_table(self, report: Dict[str, Any]) -> str:
        """
        Format analysis report as a human-readable ASCII table.

        Args:
            report: Dict returned from analyze()

        Returns:
            Formatted string with table and recommendations
        """
        lines = []
        lines.append("")
        lines.append("=" * 80)
        lines.append("PHASE BOTTLENECK ANALYSIS")
        lines.append("=" * 80)

        if not report.get("phases"):
            lines.append("No phase data available.")
            lines.append("")
            return "\n".join(lines)

        lines.append("")
        lines.append("PHASE | MEAN (s) | STDEV (s) | TOTAL (s) | % TOTAL | RANK | RECOMMENDATION")
        lines.append("-" * 80)

        for phase in report["phases"]:
            phase_name = phase["phase_name"]
            mean_dur = phase["mean_duration_sec"]
            stdev_dur = phase["stdev_duration_sec"]
            total_dur = phase["total_time_sec"]
            percent = phase["percent_of_total"]
            rank = phase["bottleneck_rank"]
            rec = phase.get("recommendation", "")

            # Highlight top bottleneck
            prefix = ">>> " if rank == 1 else "    "

            rec_short = rec[:40] if rec else "(no recommendation)"
            line = (
                f"{prefix}{phase_name:5} | {mean_dur:8.2f} | {stdev_dur:9.2f} | "
                f"{total_dur:9.2f} | {percent:6.1f}% | {rank:4} | {rec_short}"
            )
            lines.append(line)

        lines.append("")
        lines.append("RECOMMENDATIONS:")
        lines.append("-" * 80)
        for phase in report["phases"]:
            if phase.get("recommendation"):
                lines.append(f"{phase['phase_name']}: {phase['recommendation']}")

        lines.append("")
        lines.append(f"Total loop time: {report['total_time_sec']:.2f}s across {report['iteration_count']} iterations")
        lines.append("=" * 80)
        lines.append("")

        return "\n".join(lines)

    def format_json(self, report: Dict[str, Any]) -> str:
        """
        Format analysis report as newline-delimited JSON.

        Args:
            report: Dict returned from analyze()

        Returns:
            Newline-delimited JSON (one object per line)
        """
        lines = []
        for phase in report.get("phases", []):
            lines.append(json.dumps(phase))
        return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Analyze SPIRAL phase execution bottlenecks.")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path(".spiral/results.jsonl"),
        help="Path to results.jsonl (default: .spiral/results.jsonl)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as newline-delimited JSON instead of table",
    )

    args = parser.parse_args()
    analyzer = PhaseBottleneckAnalyzer()
    report = analyzer.analyze(args.results)

    if args.json:
        output = analyzer.format_json(report)
    else:
        output = analyzer.format_table(report)

    print(output)


if __name__ == "__main__":
    main()
