#!/usr/bin/env python3
"""
lib/perf_analyzer.py — Phase Timing Report & SLA Breach Analysis (US-546)

Reads results.tsv, groups rows by phase_name column, computes median and p95
durations, and flags SLA breaches.

Usage:
    spiral phase-timing-report --format json [--history results.tsv] [--sla 300]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from typing import Any

# Default SLA threshold in seconds (5 minutes)
_DEFAULT_SLA_SEC = 300.0

# Sub-phase columns in results.tsv that contain per-phase timing data
_SUB_PHASE_COLUMNS = {
    "decompose": "decompose_secs",
    "impl": "impl_secs",
    "verify": "verify_secs",
}


def load_results(tsv_path: str) -> list[dict[str, Any]]:
    """Load results.tsv and return list of row dicts."""
    if not os.path.isfile(tsv_path):
        return []
    rows: list[dict[str, Any]] = []
    with open(tsv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(dict(row))
    return rows


def _percentile(values: list[float], pct: float) -> float:
    """Compute the pct-th percentile of a sorted list using nearest-rank.

    Args:
        values: List of numeric values (will be sorted internally).
        pct: Percentile to compute (0-100).

    Returns:
        The percentile value. Returns 0.0 for empty list.
    """
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    # Nearest-rank method: ceil(pct/100 * n) - 1, clamped
    rank = int((pct / 100.0) * n + 0.5)  # round to nearest
    idx = max(0, min(rank - 1, n - 1))
    return s[idx]


def _median(values: list[float]) -> float:
    """Return median of a list of floats. Returns 0.0 for empty list."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _safe_float(val: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def analyze_phase_timings(
    tsv_path: str,
    sla_threshold_sec: float = _DEFAULT_SLA_SEC,
) -> list[dict[str, Any]]:
    """Analyze phase timings from results.tsv.

    Groups rows by phase_name column if present. Otherwise, extracts
    sub-phase timings from decompose_secs, impl_secs, verify_secs columns
    and uses overall duration_sec.

    Args:
        tsv_path: Path to results.tsv.
        sla_threshold_sec: SLA threshold in seconds for breach detection.

    Returns:
        List of {phase, median_duration_sec, p95_duration_sec,
                 sla_threshold_sec, breach_count} dicts.
    """
    rows = load_results(tsv_path)

    # Group durations by phase name
    phase_durations: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        # If results.tsv has a phase_name column, use it
        phase_name = (row.get("phase_name") or "").strip()
        if phase_name:
            dur = _safe_float(row.get("duration_sec"))
            if dur is not None:
                phase_durations[phase_name].append(dur)
        else:
            # Extract sub-phase timings from dedicated columns
            for phase_key, col_name in _SUB_PHASE_COLUMNS.items():
                dur = _safe_float(row.get(col_name))
                if dur is not None and dur > 0:
                    phase_durations[phase_key].append(dur)

            # Also record overall duration as "total" phase
            total_dur = _safe_float(row.get("duration_sec"))
            if total_dur is not None and total_dur > 0:
                phase_durations["total"].append(total_dur)

    # Build report entries
    report: list[dict[str, Any]] = []
    for phase in sorted(phase_durations.keys()):
        durations = phase_durations[phase]
        median_val = _median(durations)
        p95_val = _percentile(durations, 95)
        breach_count = sum(1 for d in durations if d > sla_threshold_sec)

        report.append(
            {
                "phase": phase,
                "median_duration_sec": round(median_val, 2),
                "p95_duration_sec": round(p95_val, 2),
                "sla_threshold_sec": sla_threshold_sec,
                "breach_count": breach_count,
            }
        )

    return report


def _cli(argv: list[str] | None = None) -> int:
    """CLI entry point for phase-timing-report."""
    parser = argparse.ArgumentParser(
        description="Generate phase timing report with SLA breach analysis from results.tsv",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--history",
        default="results.tsv",
        metavar="TSV",
        help="Path to results.tsv (default: results.tsv)",
    )
    parser.add_argument(
        "--sla",
        type=float,
        default=_DEFAULT_SLA_SEC,
        metavar="SEC",
        help=f"SLA threshold in seconds (default: {_DEFAULT_SLA_SEC})",
    )
    args = parser.parse_args(argv)

    result = analyze_phase_timings(args.history, sla_threshold_sec=args.sla)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
