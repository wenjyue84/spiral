#!/usr/bin/env python3
"""
cost_estimator.py — Predict total cost for N iterations with confidence bounds.

Uses historical results.tsv data to estimate average tokens/cost per model and
complexity band, then projects costs for N iterations with 68% confidence intervals
based on variance (mean ± 1 std dev).
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.constants import INPUT_OUTPUT_RATIO, PRICING, TOKENS_PER_SEC_OUTPUT
from routing.velocity_model import classify_story


def _tokens_from_duration(duration_sec: float) -> float:
    """Estimate total tokens from wall-clock duration."""
    if duration_sec <= 0:
        return 0.0
    output = duration_sec * float(TOKENS_PER_SEC_OUTPUT)
    input_ = output * float(INPUT_OUTPUT_RATIO)
    return float(input_ + output)


def _cost_from_tokens(tokens: float, model: str) -> float:
    """Compute USD cost from tokens and model."""
    model_norm = (model or "").lower().strip()
    pricing = PRICING.get("sonnet", {"input": 3.00, "output": 15.00})
    for key in PRICING:
        if key in model_norm:
            pricing = PRICING[key]
            break

    # Estimate split: tokens = input + output, where output = tokens / (1 + ratio)
    output_tokens = tokens / (1.0 + INPUT_OUTPUT_RATIO)
    input_tokens = tokens - output_tokens

    input_cost = (input_tokens / 1_000_000.0) * pricing["input"]
    output_cost = (output_tokens / 1_000_000.0) * pricing["output"]
    return float(input_cost + output_cost)


def compute_historical_stats(
    results_tsv_path: str = "results.tsv",
) -> dict[str, Any]:
    """
    Compute statistics from historical results.tsv.

    Returns:
        dict with keys:
          - per_model: {model: {avg_tokens, avg_cost, std_dev_cost, count}}
          - per_complexity: {complexity: {avg_tokens, avg_cost, count}}
          - total_attempts: total number of story attempts in results.tsv
          - model_distribution: {model: percentage}
    """
    if not os.path.isfile(results_tsv_path):
        return {
            "per_model": {},
            "per_complexity": {},
            "total_attempts": 0,
            "model_distribution": {},
        }

    model_data: dict[str, list[float]] = {}  # model -> [costs]
    complexity_data: dict[str, list[float]] = {}  # complexity -> [costs]
    model_counts: dict[str, int] = {}
    total_count = 0

    try:
        with open(results_tsv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return {
                    "per_model": {},
                    "per_complexity": {},
                    "total_attempts": 0,
                    "model_distribution": {},
                }

            for row in reader:
                try:
                    duration = float(row.get("duration_sec") or 0)
                    model = (row.get("model") or "").strip()
                    title = (row.get("story_title") or "").strip()

                    if duration <= 0 or not model:
                        continue

                    tokens = _tokens_from_duration(duration)
                    cost = _cost_from_tokens(tokens, model)

                    # Accumulate per-model
                    if model not in model_data:
                        model_data[model] = []
                    model_data[model].append(cost)
                    model_counts[model] = model_counts.get(model, 0) + 1

                    # Accumulate per-complexity
                    complexity = classify_story(title) if title else "general"
                    if complexity not in complexity_data:
                        complexity_data[complexity] = []
                    complexity_data[complexity].append(cost)

                    total_count += 1
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass

    # Compute statistics
    per_model: dict[str, dict[str, float]] = {}
    for model, costs in model_data.items():
        if costs:
            avg = sum(costs) / len(costs)
            variance = sum((c - avg) ** 2 for c in costs) / len(costs)
            std_dev = math.sqrt(variance)
            per_model[model] = {
                "avg_tokens": 0,  # Not used in this context
                "avg_cost": round(avg, 6),
                "std_dev_cost": round(std_dev, 6),
                "count": len(costs),
            }

    per_complexity: dict[str, dict[str, float]] = {}
    for complexity, costs in complexity_data.items():
        if costs:
            avg = sum(costs) / len(costs)
            per_complexity[complexity] = {
                "avg_tokens": 0,
                "avg_cost": round(avg, 6),
                "count": len(costs),
            }

    model_distribution = {}
    for model, count in model_counts.items():
        if total_count > 0:
            pct = round(100.0 * count / total_count, 1)
            model_distribution[model] = pct

    return {
        "per_model": per_model,
        "per_complexity": per_complexity,
        "total_attempts": total_count,
        "model_distribution": model_distribution,
    }


def predict_cost_for_n_iterations(
    n_iterations: int,
    results_tsv_path: str = "results.tsv",
) -> dict[str, Any]:
    """
    Predict total cost for N iterations with 68% confidence bounds.

    Uses historical stats to estimate average cost per iteration,
    then multiplies by N iterations with std dev bounds (mean ± 1σ = 68% CI).

    Args:
        n_iterations: number of iterations to project cost for
        results_tsv_path: path to results.tsv for historical data

    Returns:
        dict with keys:
          - estimated_cost: mean projected cost in USD
          - confidence_lower: 68% CI lower bound
          - confidence_upper: 68% CI upper bound
          - per_story_avg: average cost per story (across all models)
          - breakdown_by_model: {model: {pct, cost, total_cost}}
          - total_attempts: number of historical attempts used
          - note: explanation of escalation impact
    """
    stats = compute_historical_stats(results_tsv_path)

    if stats["total_attempts"] == 0:
        return {
            "estimated_cost": 0.0,
            "confidence_lower": 0.0,
            "confidence_upper": 0.0,
            "per_story_avg": 0.0,
            "breakdown_by_model": {},
            "total_attempts": 0,
            "note": "No historical data available",
        }

    # Compute weighted average cost per story (across all models)
    all_costs: list[float] = []
    for model_stats in stats["per_model"].values():
        count = model_stats.get("count", 0)
        avg_cost = model_stats.get("avg_cost", 0.0)
        all_costs.extend([avg_cost] * count)

    if not all_costs:
        return {
            "estimated_cost": 0.0,
            "confidence_lower": 0.0,
            "confidence_upper": 0.0,
            "per_story_avg": 0.0,
            "breakdown_by_model": {},
            "total_attempts": 0,
            "note": "No valid cost data available",
        }

    per_story_avg = sum(all_costs) / len(all_costs)

    # Estimate total cost for N iterations (assume avg stories per iteration)
    # For now, assume stories per iteration = total_attempts / num_iterations (rough estimate)
    # Or use per_story_avg * estimated_stories_per_iteration
    # Conservative: assume N iterations adds N * (avg stories per past iteration)
    # But we don't know iterations count, so assume one "typical" iteration worth of stories
    estimated_total = per_story_avg * n_iterations

    # Compute std dev across all observed costs for confidence bounds
    mean = sum(all_costs) / len(all_costs)
    variance = sum((c - mean) ** 2 for c in all_costs) / len(all_costs)
    std_dev = math.sqrt(variance)
    # Scale std dev by sqrt(n_iterations) for accumulated uncertainty
    scaled_std_dev = std_dev * math.sqrt(n_iterations)

    confidence_lower = max(0.0, estimated_total - scaled_std_dev)
    confidence_upper = estimated_total + scaled_std_dev

    # Breakdown by model (showing impact of model distribution)
    breakdown: dict[str, dict[str, Any]] = {}
    for model, dist_pct in stats["model_distribution"].items():
        if model in stats["per_model"]:
            model_stats = stats["per_model"][model]
            avg_model_cost = model_stats.get("avg_cost", 0.0)
            # Cost contribution of this model tier to total
            model_total = (dist_pct / 100.0) * estimated_total
            breakdown[model] = {
                "pct": dist_pct,
                "cost_per_story": round(avg_model_cost, 6),
                "total_cost": round(model_total, 6),
            }

    # Notes on escalation impact
    escalation_note = ""
    if "opus" in breakdown and breakdown["opus"]["pct"] > 0:
        escalation_note = (
            f"Escalation to Opus detected ({breakdown['opus']['pct']:.1f}% of stories) — "
            f"{round(breakdown['opus']['total_cost'], 2)} USD from model tier alone"
        )
    elif "sonnet" in breakdown and breakdown["sonnet"]["pct"] > 50:
        escalation_note = "Sonnet dominant (>50% of stories) — consider evaluating haiku for simpler tasks"

    return {
        "estimated_cost": round(estimated_total, 2),
        "confidence_lower": round(confidence_lower, 2),
        "confidence_upper": round(confidence_upper, 2),
        "per_story_avg": round(per_story_avg, 6),
        "breakdown_by_model": breakdown,
        "total_attempts": stats["total_attempts"],
        "note": escalation_note if escalation_note else "No escalation detected",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lib/cost_estimator.py <num_iterations> [results.tsv]", file=sys.stderr)
        sys.exit(1)

    try:
        n_iters = int(sys.argv[1])
    except ValueError:
        print(f"ERROR: num_iterations must be an integer, got {sys.argv[1]!r}", file=sys.stderr)
        sys.exit(1)

    results_path = sys.argv[2] if len(sys.argv) > 2 else "results.tsv"

    prediction = predict_cost_for_n_iterations(n_iters, results_path)

    # Format output message
    total = prediction["estimated_cost"]
    lower = prediction["confidence_lower"]
    upper = prediction["confidence_upper"]
    attempts = prediction["total_attempts"]

    output_msg = (
        f"Estimated cost for {n_iters} iterations: ${total:.2f} "
        f"(68% confidence: ${lower:.2f} - ${upper:.2f}) "
        f"based on {attempts} historical attempts"
    )

    print(output_msg)

    if prediction["breakdown_by_model"]:
        print("\nBreakdown by model:")
        for model, data in sorted(prediction["breakdown_by_model"].items()):
            print(
                f"  {model}: {data['pct']:.1f}% of stories, "
                f"${data['cost_per_story']:.6f}/story = ${data['total_cost']:.2f} total"
            )

    if prediction["note"] and prediction["note"] != "No escalation detected":
        print(f"\nNote: {prediction['note']}")

    # Also output JSON for programmatic use
    print(f"\nJSON: {json.dumps(prediction)}")
