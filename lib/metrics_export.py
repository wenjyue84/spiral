#!/usr/bin/env python3
"""
metrics_export.py — Export time-series metrics from results.tsv and spiral_events.jsonl.

Aggregates iteration data to enable external dashboarding and trend analysis:
  - Parses results.tsv for story outcomes and token spend
  - Parses spiral_events.jsonl for iteration timeline
  - Outputs JSON array: {iteration, timestamp, cumulative_tokens, stories_passed_delta, avg_model_tier, total_cost}
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Model tier scoring: lower = cheaper/faster
MODEL_TIER_SCORE = {"haiku": 1, "sonnet": 2, "opus": 3}

# Pricing per million tokens (input)
PRICING = {
    "haiku": {"input": 0.80},
    "sonnet": {"input": 3.00},
    "opus": {"input": 15.00},
}

TOKENS_PER_SEC_OUTPUT = 20
INPUT_OUTPUT_RATIO = 3.0


def _total_tokens_from_duration(duration_sec: float) -> float:
    """Total (input + output) tokens estimated from wall-clock duration."""
    output = duration_sec * float(TOKENS_PER_SEC_OUTPUT)
    input_ = output * float(INPUT_OUTPUT_RATIO)
    return float(input_ + output)


def _cost_per_token(model: str) -> float:
    """Cost in USD per input token for the given model."""
    model_norm = model.lower() if model else ""
    for key in PRICING:
        if key in model_norm:
            input_cost = float(PRICING[key]["input"])
            return input_cost / 1_000_000.0
    # Default to sonnet pricing
    return float(PRICING.get("sonnet", {}).get("input", 3.00)) / 1_000_000.0


def _model_tier_score(model: str) -> int:
    """Map model name to tier score (1=haiku, 2=sonnet, 3=opus)."""
    if not model:
        return 2  # Default to sonnet
    model_norm = model.lower().strip()
    for key in MODEL_TIER_SCORE:
        if key in model_norm:
            return MODEL_TIER_SCORE[key]
    return 2  # Default to sonnet


def parse_results_tsv(results_tsv: Path) -> dict[int, list[dict[str, Any]]]:
    """
    Parse results.tsv and group rows by iteration.

    Returns:
        dict mapping spiral_iter -> list of rows for that iteration
    """
    by_iteration: dict[int, list[dict[str, Any]]] = defaultdict(list)

    if not results_tsv.exists():
        return by_iteration

    try:
        with open(results_tsv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return by_iteration

            for row in reader:
                try:
                    if not row.get("spiral_iter"):
                        continue
                    iter_num = int(row["spiral_iter"])
                    by_iteration[iter_num].append(row)
                except (ValueError, TypeError, KeyError):
                    continue
    except Exception:
        pass

    return by_iteration


def parse_spiral_events(
    spiral_events: Path,
) -> dict[int, str]:
    """
    Parse spiral_events.jsonl and extract Phase G completion timestamps per iteration.

    Returns:
        dict mapping iteration -> timestamp (ISO 8601)
    """
    iter_timestamps: dict[int, str] = {}

    if not spiral_events.exists():
        return iter_timestamps

    try:
        with open(spiral_events, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Look for phase_complete events with phase_letter == "G"
                if event.get("event_type") == "phase_complete" and event.get("phase_letter") == "G":
                    try:
                        iter_num = int(event.get("iteration", 0))
                        timestamp = event.get("timestamp", "")
                        if iter_num > 0 and timestamp:
                            # Keep latest timestamp for iteration
                            iter_timestamps[iter_num] = timestamp
                    except (ValueError, TypeError):
                        continue
    except Exception:
        pass

    return iter_timestamps


def aggregate_timeseries(
    by_iteration: dict[int, list[dict[str, Any]]],
    iter_timestamps: dict[int, str],
) -> list[dict[str, Any]]:
    """
    Aggregate iteration data into time-series entries.

    Returns:
        List of {iteration, timestamp, cumulative_tokens, stories_passed_delta, avg_model_tier, total_cost}
        sorted by iteration number
    """
    timeseries: list[dict[str, Any]] = []
    cumulative_tokens = 0.0
    cumulative_cost = 0.0

    for iter_num in sorted(by_iteration.keys()):
        rows = by_iteration[iter_num]
        if not rows:
            continue

        # Calculate per-iteration metrics
        stories_passed = 0
        iter_tokens = 0.0
        iter_cost = 0.0
        model_scores: list[int] = []

        for row in rows:
            try:
                # Count passed stories
                if row.get("status", "").lower() == "pass":
                    stories_passed += 1

                # Calculate tokens and cost
                if row.get("duration_sec") and row.get("model"):
                    duration = float(row["duration_sec"])
                    if duration > 0:
                        tokens = _total_tokens_from_duration(duration)
                        iter_tokens += tokens
                        cumulative_tokens += tokens

                        model = row["model"].strip()
                        cost_per_tok = _cost_per_token(model)
                        cost = tokens * cost_per_tok
                        iter_cost += cost
                        cumulative_cost += cost

                        # Track model tier for averaging
                        model_scores.append(_model_tier_score(model))
            except (ValueError, TypeError, KeyError):
                continue

        # Calculate average model tier
        avg_tier = sum(model_scores) / len(model_scores) if model_scores else 2.0

        # Use timestamp from spiral_events if available, otherwise use first story timestamp
        timestamp = iter_timestamps.get(iter_num, "")
        if not timestamp and rows:
            timestamp = rows[0].get("timestamp", "")

        entry = {
            "iteration": iter_num,
            "timestamp": timestamp,
            "cumulative_tokens": round(cumulative_tokens, 2),
            "stories_passed_delta": stories_passed,
            "avg_model_tier": round(avg_tier, 2),
            "total_cost": round(cumulative_cost, 4),
        }
        timeseries.append(entry)

    return timeseries


def export_timeseries(results_tsv: Path, spiral_events: Path, output_file: Path) -> None:
    """
    Export time-series metrics to JSON file.

    Args:
        results_tsv: Path to results.tsv
        spiral_events: Path to spiral_events.jsonl
        output_file: Path to write JSON output

    Raises:
        ValueError: if fewer than 10 story records exist
    """
    by_iteration = parse_results_tsv(results_tsv)

    # Check minimum record count
    total_records = sum(len(rows) for rows in by_iteration.values())
    if total_records < 10:
        raise ValueError(f"Insufficient data: only {total_records} story records found (minimum 10 required)")

    iter_timestamps = parse_spiral_events(spiral_events)
    timeseries = aggregate_timeseries(by_iteration, iter_timestamps)

    # Write output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(timeseries, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: metrics_export.py <results.tsv> <spiral_events.jsonl> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    results_file = Path(sys.argv[1])
    events_file = Path(sys.argv[2])
    output_path = Path(sys.argv[3])

    try:
        export_timeseries(results_file, events_file, output_path)
        print(f"[spiral] Exported metrics to {output_path}", file=sys.stderr)
        sys.exit(0)
    except ValueError as e:
        print(f"[spiral] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[spiral] ERROR: Failed to export metrics: {e}", file=sys.stderr)
        sys.exit(1)
