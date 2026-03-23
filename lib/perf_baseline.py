#!/usr/bin/env python3
"""
lib/perf_baseline.py — Phase C: Performance Baseline and Regression Detector

Records execution time baseline (P50/P90) for each SPIRAL phase from the last 10
iterations. After each iteration, checks if any phase exceeded 2x its P90 baseline.
Flags performance regression before it compounds across iterations.

Usage:
  python lib/perf_baseline.py update \
    --iteration-summary .spiral/_iteration_summary.json \
    --baseline-file .spiral/perf_baseline.json

  python lib/perf_baseline.py check \
    --iteration-summary .spiral/_iteration_summary.json \
    --baseline-file .spiral/perf_baseline.json \
    --multiplier 2.0

Inputs:
  --iteration-summary     Path to .spiral/_iteration_summary.json (from write_iter_summary)
  --baseline-file         Path to .spiral/perf_baseline.json (created/updated)
  --multiplier            Regression threshold multiplier (default 2.0, e.g., 2x P90)

Output (check mode):
  Returns 0 if no regression detected
  Returns 1 if regression detected (prints report to stdout)
  Writes .spiral/perf_regression_report.json on regression

Structure of .spiral/perf_baseline.json:
{
  "rolling_window": [
    {"iteration": 1, "phases": {"R": 45.2, "T": 12.3, "M": 8.1, ...}},
    ...
  ],
  "p50": {"R": 50.0, "T": 15.0, ...},
  "p90": {"R": 120.0, "T": 45.0, ...}
}
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def update_baseline(
    iteration_summary_file: Path,
    baseline_file: Path,
    window_size: int = 10,
) -> Dict[str, Any]:
    """
    Update rolling window baseline with current iteration's phase timings.

    Maintains last 10 iterations, computes P50 and P90 per phase.

    Args:
      iteration_summary_file: Path to .spiral/_iteration_summary.json
      baseline_file: Path to .spiral/perf_baseline.json (created if missing)
      window_size: Rolling window size (default 10 iterations)

    Returns:
      Updated baseline dict with rolling_window, p50, p90
    """
    if not iteration_summary_file.exists():
        return {
            "rolling_window": [],
            "p50": {},
            "p90": {},
            "error": f"Iteration summary not found: {iteration_summary_file}",
        }

    try:
        with open(iteration_summary_file, encoding="utf-8") as f:
            iteration_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "rolling_window": [],
            "p50": {},
            "p90": {},
            "error": f"Failed to parse iteration summary: {e}",
        }

    # Load existing baseline or start fresh
    baseline: Dict[str, Any] = {"rolling_window": [], "p50": {}, "p90": {}}
    if baseline_file.exists():
        try:
            with open(baseline_file, encoding="utf-8") as f:
                baseline = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Extract phases from iteration summary
    phases: Dict[str, float] = {}
    iteration_num = iteration_data.get("iteration", 0)

    for phase_name in ["R", "T", "M", "I", "V", "C"]:
        key = f"phase_{phase_name.lower()}_duration_s"
        if key in iteration_data:
            phases[phase_name] = float(iteration_data[key])

    if phases:
        # Add to rolling window
        baseline["rolling_window"].append(
            {"iteration": iteration_num, "phases": phases}
        )

        # Keep only last N iterations
        if len(baseline["rolling_window"]) > window_size:
            baseline["rolling_window"] = baseline["rolling_window"][-window_size:]

        # Compute P50 and P90 per phase
        phase_timings: Dict[str, List[float]] = {}
        for entry in baseline["rolling_window"]:
            for phase_name, duration in entry["phases"].items():
                if phase_name not in phase_timings:
                    phase_timings[phase_name] = []
                phase_timings[phase_name].append(duration)

        baseline["p50"] = {}
        baseline["p90"] = {}
        for phase_name, timings in phase_timings.items():
            if timings:
                baseline["p50"][phase_name] = statistics.median(timings)
                baseline["p90"][phase_name] = statistics.quantiles(
                    timings, n=10, method="inclusive"
                )[8]  # 90th percentile

    return baseline


def check_regression(
    iteration_summary_file: Path,
    baseline_file: Path,
    multiplier: float = 2.0,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Check if current iteration shows phase timing regression vs baseline.

    Args:
      iteration_summary_file: Path to .spiral/_iteration_summary.json
      baseline_file: Path to .spiral/perf_baseline.json
      multiplier: Regression threshold (default 2.0 = 2x P90)

    Returns:
      (has_regression, report_dict)
      has_regression: True if any phase > P90 * multiplier
      report_dict: {
        "phases_checked": int,
        "regressions": [
          {"phase": "I", "current": 833, "p90": 400, "ratio": 2.08, "threshold": 800}
        ],
        "summary": "Phase I regression..."
      }
    """
    if not iteration_summary_file.exists():
        return False, {
            "error": f"Iteration summary not found: {iteration_summary_file}",
            "phases_checked": 0,
            "regressions": [],
        }

    if not baseline_file.exists():
        return False, {
            "message": "No baseline yet (first iteration)",
            "phases_checked": 0,
            "regressions": [],
        }

    try:
        with open(iteration_summary_file, encoding="utf-8") as f:
            iteration_data = json.load(f)
        with open(baseline_file, encoding="utf-8") as f:
            baseline = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, {
            "error": f"Failed to parse files: {e}",
            "phases_checked": 0,
            "regressions": [],
        }

    # Extract current phase durations
    current_phases: Dict[str, float] = {}
    for phase_name in ["R", "T", "M", "I", "V", "C"]:
        key = f"phase_{phase_name.lower()}_duration_s"
        if key in iteration_data:
            current_phases[phase_name] = float(iteration_data[key])

    # Check for regressions
    regressions: List[Dict[str, Any]] = []
    p90 = baseline.get("p90", {})

    for phase_name, current_duration in current_phases.items():
        if phase_name in p90:
            threshold = p90[phase_name] * multiplier
            if current_duration > threshold:
                ratio = current_duration / p90[phase_name]
                regressions.append(
                    {
                        "phase": phase_name,
                        "current": round(current_duration, 1),
                        "p90": round(p90[phase_name], 1),
                        "ratio": round(ratio, 2),
                        "threshold": round(threshold, 1),
                    }
                )

    has_regression = len(regressions) > 0
    report = {
        "phases_checked": len(current_phases),
        "regressions": regressions,
        "summary": (
            f"Phase regression detected ({len(regressions)} phase(s)): "
            + ", ".join(
                f"{r['phase']} ({r['current']}s vs P90 {r['p90']}s, {r['ratio']}x)"
                for r in regressions
            )
            if regressions
            else "No regression detected"
        ),
    }

    return has_regression, report


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Phase C: Performance Baseline and Regression Detector"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # update subcommand
    update_parser = subparsers.add_parser("update", help="Update baseline")
    update_parser.add_argument(
        "--iteration-summary",
        type=Path,
        default=Path(".spiral/_iteration_summary.json"),
        help="Path to iteration summary JSON",
    )
    update_parser.add_argument(
        "--baseline-file",
        type=Path,
        default=Path(".spiral/perf_baseline.json"),
        help="Path to baseline JSON file",
    )
    update_parser.add_argument(
        "--window-size", type=int, default=10, help="Rolling window size"
    )

    # check subcommand
    check_parser = subparsers.add_parser("check", help="Check for regression")
    check_parser.add_argument(
        "--iteration-summary",
        type=Path,
        default=Path(".spiral/_iteration_summary.json"),
        help="Path to iteration summary JSON",
    )
    check_parser.add_argument(
        "--baseline-file",
        type=Path,
        default=Path(".spiral/perf_baseline.json"),
        help="Path to baseline JSON file",
    )
    check_parser.add_argument(
        "--multiplier",
        type=float,
        default=2.0,
        help="Regression threshold multiplier (default 2.0)",
    )
    check_parser.add_argument(
        "--report-file",
        type=Path,
        default=Path(".spiral/perf_regression_report.json"),
        help="Output regression report JSON",
    )

    args = parser.parse_args()

    if args.command == "update":
        baseline = update_baseline(
            args.iteration_summary,
            args.baseline_file,
            args.window_size,
        )
        args.baseline_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.baseline_file, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)
        print(json.dumps(baseline, indent=2))

    elif args.command == "check":
        has_regression, report = check_regression(
            args.iteration_summary,
            args.baseline_file,
            args.multiplier,
        )
        if has_regression:
            args.report_file.parent.mkdir(parents=True, exist_ok=True)
            with open(args.report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(json.dumps(report, indent=2))
        exit(1 if has_regression else 0)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
