#!/usr/bin/env python3
"""
complexity_trend.py — Analyze story retry & duration patterns from results.tsv.

Groups stories by phase, computes avg_retries, p50_duration_seconds,
model_escalations, and tokens_per_retry. Outputs CSV or JSON.

Usage:
    python lib/complexity_trend.py --phase I --output trend-report.csv
    python lib/complexity_trend.py --phase I --format json
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

# Model tier ordering for escalation detection
_MODEL_TIERS: dict[str, int] = {
    "haiku": 0,
    "claude-haiku": 0,
    "claude-haiku-4-5": 0,
    "sonnet": 1,
    "claude-sonnet": 1,
    "claude-sonnet-4-6": 1,
    "opus": 2,
    "claude-opus": 2,
    "claude-opus-4-6": 2,
}

# Tokens/second estimate for duration-based fallback (matches predict_cost.py)
_TOKENS_PER_SEC = 40.0


def _model_tier(model: str) -> int:
    """Return numeric tier for a model name (0=haiku, 1=sonnet, 2=opus)."""
    m = model.strip().lower()
    for key, tier in _MODEL_TIERS.items():
        if key in m:
            return tier
    return 0  # unknown → treat as haiku


def _p50(values: list[float]) -> float:
    """Return median (p50) of a list of floats. Returns 0.0 for empty list."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _tokens_from_row(row: dict[str, Any]) -> float:
    """Estimate total tokens from a results.tsv row."""
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


def _story_phase(story_id: str) -> str:
    """Derive a phase label for a story (all results.tsv rows are Phase I)."""
    # All entries in results.tsv come from Phase I (implementation)
    return "I"


def compute_story_metrics(
    rows: list[dict[str, Any]], phase_filter: str | None = None
) -> list[dict[str, Any]]:
    """
    Compute per-story metrics from results.tsv rows.

    Returns a list of dicts with keys:
        id, phase, retries, avg_retries, p50_duration_seconds,
        model_escalations, tokens_per_retry, duration_seconds
    """
    # Group rows by story_id, maintaining insertion order per story
    by_story: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sid = row.get("story_id", "").strip()
        if not sid:
            continue
        phase = _story_phase(sid)
        if phase_filter and phase.upper() != phase_filter.upper():
            continue
        by_story[sid].append(row)

    results: list[dict[str, Any]] = []
    for sid, story_rows in by_story.items():
        # Sort by retry_num if available, else keep insertion order
        def _retry_key(r: dict[str, Any]) -> int:
            try:
                return int(r.get("retry_num") or 0)
            except (ValueError, TypeError):
                return 0

        story_rows_sorted = sorted(story_rows, key=_retry_key)

        retry_nums = [_retry_key(r) for r in story_rows_sorted]
        durations = []
        tokens_list = []
        models = [r.get("model", "").strip() for r in story_rows_sorted]

        for r in story_rows_sorted:
            try:
                dur = float(r.get("duration_sec") or r.get("duration_s") or 0)
                if dur > 0:
                    durations.append(dur)
            except (ValueError, TypeError):
                pass
            tok = _tokens_from_row(r)
            if tok > 0:
                tokens_list.append(tok)

        # Count model escalations: tier increasing between consecutive retries
        escalations = 0
        for i in range(1, len(models)):
            prev_tier = _model_tier(models[i - 1])
            curr_tier = _model_tier(models[i])
            if curr_tier > prev_tier:
                escalations += 1

        num_retries = len(story_rows_sorted)
        avg_tokens_per_retry = (
            sum(tokens_list) / len(tokens_list) if tokens_list else 0.0
        )

        results.append(
            {
                "id": sid,
                "phase": _story_phase(sid),
                "retries": retry_nums,
                "avg_retries": num_retries,
                "p50_duration_seconds": _p50(durations),
                "model_escalations": escalations,
                "tokens_per_retry": round(avg_tokens_per_retry, 1),
                "duration_seconds": sum(durations),
            }
        )

    return results


def build_phase_report(
    metrics: list[dict[str, Any]], phase: str
) -> dict[str, Any]:
    """Build the JSON report structure for a phase."""
    if not metrics:
        return {
            "phase": phase,
            "stories": [],
            "phase_avg_retries": 0.0,
            "total_escalations": 0,
        }

    stories_out = [
        {
            "id": m["id"],
            "retries": m["retries"],
            "duration_seconds": m["duration_seconds"],
            "escalations": m["model_escalations"],
        }
        for m in metrics
    ]

    avg_retries = sum(m["avg_retries"] for m in metrics) / len(metrics)

    return {
        "phase": phase,
        "stories": stories_out,
        "phase_avg_retries": round(avg_retries, 2),
        "total_escalations": sum(m["model_escalations"] for m in metrics),
    }


def write_csv(metrics: list[dict[str, Any]], output_path: str) -> None:
    """Write metrics to a CSV file."""
    fieldnames = [
        "story_id",
        "avg_retries",
        "p50_duration_seconds",
        "model_escalations",
        "tokens_per_retry",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in metrics:
            writer.writerow(
                {
                    "story_id": m["id"],
                    "avg_retries": m["avg_retries"],
                    "p50_duration_seconds": round(m["p50_duration_seconds"], 2),
                    "model_escalations": m["model_escalations"],
                    "tokens_per_retry": m["tokens_per_retry"],
                }
            )


def run_trend(
    tsv_path: str,
    phase: str = "I",
    output_path: str | None = None,
    fmt: str = "csv",
) -> dict[str, Any]:
    """
    Main entry: load results.tsv, compute metrics, output CSV or JSON.

    Returns the phase report dict regardless of output mode.
    """
    rows = load_results(tsv_path)
    metrics = compute_story_metrics(rows, phase_filter=phase)
    report = build_phase_report(metrics, phase)

    if fmt == "json":
        payload = json.dumps(report, indent=2)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(payload)
        else:
            print(payload)
    else:
        # CSV mode
        if output_path:
            write_csv(metrics, output_path)
            print(f"Wrote {len(metrics)} rows to {output_path}")
        else:
            # Print to stdout as CSV
            fieldnames = [
                "story_id",
                "avg_retries",
                "p50_duration_seconds",
                "model_escalations",
                "tokens_per_retry",
            ]
            writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
            writer.writeheader()
            for m in metrics:
                writer.writerow(
                    {
                        "story_id": m["id"],
                        "avg_retries": m["avg_retries"],
                        "p50_duration_seconds": round(m["p50_duration_seconds"], 2),
                        "model_escalations": m["model_escalations"],
                        "tokens_per_retry": m["tokens_per_retry"],
                    }
                )

    return report


def _cli() -> None:
    parser = argparse.ArgumentParser(
        prog="complexity-trend",
        description="Analyze story retry & duration patterns from results.tsv",
    )
    parser.add_argument(
        "--phase",
        default="I",
        metavar="PHASE",
        help="Phase to analyze (default: I)",
    )
    parser.add_argument(
        "--history",
        default="results.tsv",
        metavar="TSV",
        help="Path to results.tsv (default: results.tsv)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=["csv", "json"],
        default="csv",
        help="Output format: csv or json (default: csv)",
    )
    args = parser.parse_args()
    run_trend(
        tsv_path=args.history,
        phase=args.phase,
        output_path=args.output,
        fmt=args.fmt,
    )


if __name__ == "__main__":
    _cli()
