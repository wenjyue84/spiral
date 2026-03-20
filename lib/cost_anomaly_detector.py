#!/usr/bin/env python3
"""
cost_anomaly_detector.py — Detect stories with unusual token-spend patterns.

Reads results.tsv, groups rows by story_id, computes median and stddev of
token costs per story, and flags entries where cost > (median + 2*stddev).

Usage:
    python lib/cost_anomaly_detector.py [--history results.tsv] [--zscore 2.0]
    spiral detect-anomalies [--history results.tsv] [--zscore 2.0]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from typing import Any

# Token estimate fallback: tokens per second of duration
_TOKENS_PER_SEC = 40.0


def _tokens_from_row(row: dict[str, Any]) -> float:
    """Estimate total tokens from a results.tsv row.

    Prefers tokens_in + tokens_out if available; falls back to
    duration_sec * _TOKENS_PER_SEC.
    """
    try:
        t_in = float(row.get("tokens_in") or 0)
        t_out = float(row.get("tokens_out") or 0)
        if t_in + t_out > 0:
            return t_in + t_out
    except (ValueError, TypeError):
        pass
    try:
        dur = float(row.get("duration_sec") or row.get("duration_s") or 0)
        return dur * _TOKENS_PER_SEC
    except (ValueError, TypeError):
        return 0.0


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


def _stddev(values: list[float]) -> float:
    """Return population standard deviation. Returns 0.0 for < 2 values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def detect_anomalies(
    tsv_path: str,
    zscore_threshold: float = 2.0,
) -> dict[str, Any]:
    """Detect stories with unusual token-spend patterns.

    Args:
        tsv_path: Path to results.tsv.
        zscore_threshold: Z-score cutoff for anomaly detection (default 2.0).

    Returns:
        Dict with keys:
            anomalies: list of {storyId, iteration, cost, median, zscore, model}
            summary:   {totalAnomalies, affectedStories}
    """
    rows = load_results(tsv_path)

    # Group rows by story_id, preserving all row metadata
    by_story: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sid = (row.get("story_id") or "").strip()
        if not sid:
            continue
        cost = _tokens_from_row(row)
        by_story[sid].append(
            {
                "cost": cost,
                "iteration": row.get("spiral_iter", ""),
                "model": (row.get("model") or "").strip(),
                "row": row,
            }
        )

    anomalies: list[dict[str, Any]] = []
    affected_stories: set[str] = set()

    for sid, entries in by_story.items():
        costs = [e["cost"] for e in entries]
        med = _median(costs)
        std = _stddev(costs)

        for entry in entries:
            cost = entry["cost"]
            if std > 0:
                z = (cost - med) / std
            else:
                z = 0.0

            if z >= zscore_threshold:
                anomalies.append(
                    {
                        "storyId": sid,
                        "iteration": entry["iteration"],
                        "cost": cost,
                        "median": med,
                        "zscore": round(z, 4),
                        "model": entry["model"],
                    }
                )
                affected_stories.add(sid)

    return {
        "anomalies": anomalies,
        "summary": {
            "totalAnomalies": len(anomalies),
            "affectedStories": len(affected_stories),
        },
    }


def _cli(argv: list[str] | None = None) -> int:
    """CLI entry point for detect-anomalies."""
    parser = argparse.ArgumentParser(
        description="Detect stories with unusual token-spend patterns from results.tsv",
    )
    parser.add_argument(
        "--history",
        default="results.tsv",
        metavar="TSV",
        help="Path to results.tsv (default: results.tsv)",
    )
    parser.add_argument(
        "--zscore",
        type=float,
        default=2.0,
        metavar="N",
        help="Z-score threshold for anomaly detection (default: 2.0)",
    )
    args = parser.parse_args(argv)

    result = detect_anomalies(args.history, zscore_threshold=args.zscore)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
