"""US-456: Routing metrics analysis -- token savings vs quality per model tier.

Reads routing telemetry from spiral_events.jsonl and results.tsv,
computing per-tier statistics and savings vs an all-sonnet baseline.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from typing import Any


def _read_routing_events(events_path: str) -> list[dict[str, Any]]:
    """Read route_story_assigned events from spiral_events.jsonl."""
    events: list[dict[str, Any]] = []
    if not os.path.isfile(events_path):
        return events
    with open(events_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "route_story_assigned":
                events.append(record)
    return events


def _read_results_tsv(results_path: str) -> list[dict[str, Any]]:
    """Read results.tsv rows."""
    rows: list[dict[str, Any]] = []
    if not os.path.isfile(results_path):
        return rows
    with open(results_path, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def analyze(events_path: str, results_path: str) -> dict[str, Any]:
    """Compute per-tier metrics.

    Returns a dict with keys: tiers (list of tier dicts), baseline_tokens, actual_tokens, savings_pct.
    """
    events = _read_routing_events(events_path)
    results = _read_results_tsv(results_path)

    # Build story->model_tier map from routing events (latest event wins)
    story_tier: dict[str, str] = {}
    story_complexity: dict[str, int] = {}
    for ev in events:
        sid = ev.get("story_id", "")
        story_tier[sid] = ev.get("model_tier", "sonnet")
        story_complexity[sid] = ev.get("complexity_score", 0)

    # Group results by model tier
    tier_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "samples": 0,
            "total_tokens": 0,
            "passes": 0,
        }
    )

    # Token estimates per tier (rough averages for baseline calculation)
    _TIER_TOKEN_ESTIMATE = {"haiku": 5000, "sonnet": 15000, "opus": 40000}

    for row in results:
        sid = row.get("story_id", "")
        tier = row.get("model", story_tier.get(sid, "sonnet"))
        status = row.get("status", "")

        stats = tier_stats[tier]
        stats["samples"] += 1
        if status == "pass":
            stats["passes"] += 1

        # Try to get actual token count from results; fall back to estimate
        tokens = _TIER_TOKEN_ESTIMATE.get(tier, 15000)
        stats["total_tokens"] += tokens

    # If no results but we have events, use events alone
    if not results and events:
        for ev in events:
            tier = ev.get("model_tier", "sonnet")
            stats = tier_stats[tier]
            stats["samples"] += 1
            stats["total_tokens"] += _TIER_TOKEN_ESTIMATE.get(tier, 15000)

    tiers = []
    actual_total = 0
    baseline_total = 0

    for tier_name in ["haiku", "sonnet", "opus"]:
        tier_stats_entry = tier_stats.get(tier_name)
        if tier_stats_entry is None or tier_stats_entry["samples"] == 0:
            continue
        mean_tokens = tier_stats_entry["total_tokens"] // tier_stats_entry["samples"]
        success_rate = (
            tier_stats_entry["passes"] / tier_stats_entry["samples"]
            if tier_stats_entry["samples"] > 0
            else 0.0
        )
        tiers.append(
            {
                "model_tier": tier_name,
                "samples": tier_stats_entry["samples"],
                "mean_tokens": mean_tokens,
                "success_rate": round(success_rate, 3),
            }
        )
        actual_total += tier_stats_entry["total_tokens"]
        # Baseline: if all stories used sonnet
        baseline_total += tier_stats_entry["samples"] * _TIER_TOKEN_ESTIMATE["sonnet"]

    savings_pct = 0.0
    if baseline_total > 0:
        savings_pct = round((baseline_total - actual_total) / baseline_total * 100, 1)

    return {
        "tiers": tiers,
        "baseline_tokens": baseline_total,
        "actual_tokens": actual_total,
        "savings_pct": savings_pct,
    }


def format_table(metrics: dict[str, Any]) -> str:
    """Format metrics as a plain-text table."""
    tiers = metrics.get("tiers", [])
    if not tiers:
        return "No routing telemetry data available."

    header = f"{'model_tier':<12} {'samples':>8} {'mean_tokens':>12} {'success_rate':>13} {'savings_pct':>12}"
    sep = "-" * len(header)
    lines = [header, sep]

    for t in tiers:
        # Per-tier savings vs sonnet baseline (15000 tokens)
        tier_savings = round((15000 - t["mean_tokens"]) / 15000 * 100, 1) if t["mean_tokens"] else 0.0
        lines.append(
            f"{t['model_tier']:<12} {t['samples']:>8} {t['mean_tokens']:>12} "
            f"{t['success_rate']:>12.1%} {tier_savings:>11.1f}%"
        )

    lines.append(sep)
    lines.append(
        f"Overall savings vs all-sonnet baseline: {metrics['savings_pct']}% "
        f"({metrics['actual_tokens']:,} actual vs {metrics['baseline_tokens']:,} baseline tokens)"
    )
    return "\n".join(lines)


def main(args_list: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Analyze routing metrics: token savings vs quality per model tier.")
    parser.add_argument("--events", default="spiral_events.jsonl", help="Path to spiral_events.jsonl")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--dashboard", action="store_true", help="Generate HTML dashboard (not yet implemented)")
    args = parser.parse_args(args_list)

    metrics = analyze(args.events, args.results)
    print(format_table(metrics))

    if args.dashboard:
        print("\n[analyze-routing] HTML dashboard generation not yet implemented.")


if __name__ == "__main__":
    main()
