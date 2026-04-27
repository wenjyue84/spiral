#!/usr/bin/env python3
"""
cost_estimator.py — Predict total cost for N iterations with confidence bounds.

Uses historical results.tsv data to estimate average tokens/cost per model and
complexity band, then projects costs for N iterations with 68% confidence intervals
based on variance (mean ± 1 std dev).
"""

from __future__ import annotations

import argparse
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


def estimate_story_cost_breakdown(
    prd_data: dict[str, Any],
    results_tsv_path: str = "results.tsv",
) -> list[dict[str, Any]]:
    """
    Estimate cost breakdown for each story in prd.json.

    Returns list of dicts with per-story cost estimates sorted by descending cost.
    Each dict contains: story_id, complexity, tokens_h, tokens_s, tokens_o,
    cost_haiku, cost_sonnet, cost_opus, escalation_prob, model_pick, total_cost
    """
    stats = compute_historical_stats(results_tsv_path)

    stories = prd_data.get("userStories", [])
    breakdown_list: list[dict[str, Any]] = []

    # Build per-complexity token estimates from historical data
    # Default token estimate if no historical data: 5000 tokens
    complexity_tokens: dict[str, float] = {
        "small": 3000.0,
        "medium": 7500.0,
        "large": 15000.0,
        "general": 5000.0,
    }

    # Override with actual historical data if available
    if stats["total_attempts"] > 0:
        for comp, data in stats["per_complexity"].items():
            # Use count as proxy for average tokens (rough estimate)
            complexity_tokens[comp] = max(3000.0, float(data.get("count", 1) * 500))

    for story in stories:
        if story.get("passes") or story.get("_skipped"):
            continue

        story_id = story.get("id", "")
        title = story.get("title", "")
        complexity = classify_story(title) if title else "general"

        # Estimate tokens for this story (use complexity average)
        tokens = complexity_tokens.get(complexity, 5000.0)

        # Calculate costs for each model
        cost_haiku = _cost_from_tokens(tokens, "haiku")
        cost_sonnet = _cost_from_tokens(tokens, "sonnet")
        cost_opus = _cost_from_tokens(tokens, "opus")

        # Escalation probability: based on historical distribution
        escalation_prob = 0.0
        if stats["total_attempts"] > 0 and complexity in stats["per_complexity"]:
            # Lower escalation if we have many successful haiku attempts for this complexity
            complexity_count = stats["per_complexity"][complexity].get("count", 0)
            escalation_prob = max(5.0, min(50.0, 100.0 * (1.0 - complexity_count / stats["total_attempts"])))

        # Model pick: use haiku by default, escalate if high complexity
        if complexity == "large" or tokens > 10000:
            model_pick = "opus"
        elif complexity == "medium" or tokens > 5000:
            model_pick = "sonnet"
        else:
            model_pick = "haiku"

        # Total cost: use expected value with escalation
        total_cost = cost_haiku * (1.0 - escalation_prob / 100.0) + cost_opus * (escalation_prob / 100.0)

        breakdown_list.append(
            {
                "story_id": story_id,
                "complexity": complexity,
                "tokens_h": round(tokens, 0),
                "tokens_s": round(tokens, 0),
                "tokens_o": round(tokens, 0),
                "cost_haiku": round(cost_haiku, 6),
                "cost_sonnet": round(cost_sonnet, 6),
                "cost_opus": round(cost_opus, 6),
                "escalation_prob": round(escalation_prob, 1),
                "model_pick": model_pick,
                "total_cost": round(total_cost, 6),
            }
        )

    # Sort by descending total cost
    breakdown_list.sort(key=lambda x: x["total_cost"], reverse=True)
    return breakdown_list


def compute_parallelization_adjustment(
    num_stories: int,
    num_workers: int,
    num_iterations: int,
) -> dict[str, Any]:
    """
    Compute cost adjustment for parallel execution.

    Returns dict with:
      - iterations_per_worker: ceil(num_stories / num_workers)
      - total_parallel_iterations: iterations_per_worker * num_iterations
      - parallelization_factor: reduction factor compared to serial execution
    """
    if num_workers <= 0:
        num_workers = 1

    iterations_per_worker = math.ceil(num_stories / num_workers)
    total_parallel_iterations = iterations_per_worker * num_iterations
    parallelization_factor = total_parallel_iterations / max(1, num_stories * num_iterations)

    return {
        "iterations_per_worker": iterations_per_worker,
        "total_parallel_iterations": total_parallel_iterations,
        "parallelization_factor": round(parallelization_factor, 3),
    }


def format_table_output(
    breakdown: list[dict[str, Any]],
    grand_total: float,
    contingency_pct: float = 0.20,
) -> str:
    """Format per-story breakdown as human-readable table."""
    lines = [
        "Per-Story Cost Breakdown (sorted by descending cost):",
        "",
        (
            f"{'ID':<12} {'Complexity':<12} {'Tokens':<10} "
            f"{'Cost(H/S/O)':<20} {'Esc%':<6} {'Model':<8} {'Total':<10}"
        ),
        "-" * 91,
    ]

    total_cost = 0.0
    for row in breakdown:
        cost_str = f"${row['cost_haiku']:.4f}/${row['cost_sonnet']:.4f}/${row['cost_opus']:.4f}"
        lines.append(
            f"{row['story_id']:<15} {row['complexity']:<12} {int(row['tokens_h']):<10} "
            f"{cost_str:<20} {row['escalation_prob']:<6.1f} {row['model_pick']:<8} ${row['total_cost']:<9.6f}"
        )
        total_cost += row["total_cost"]

    lines.append("-" * 95)
    contingency = total_cost * contingency_pct
    final_total = total_cost + contingency

    lines.append(
        f"Subtotal:                                                                          ${total_cost:.2f}"
    )
    lines.append(
        f"Contingency (20%):                                                                 ${contingency:.2f}"
    )
    lines.append(
        f"Grand Total:                                                                       ${final_total:.2f}"
    )
    lines.append("")

    return "\n".join(lines)


def format_json_output(
    breakdown: list[dict[str, Any]],
    grand_total: float,
    contingency_pct: float = 0.20,
) -> str:
    """Format per-story breakdown as JSON."""
    contingency = grand_total * contingency_pct
    return json.dumps(
        {
            "breakdown": breakdown,
            "subtotal": round(grand_total, 2),
            "contingency_pct": contingency_pct * 100,
            "contingency": round(contingency, 2),
            "grand_total": round(grand_total + contingency, 2),
        },
        indent=2,
    )


def format_csv_output(
    breakdown: list[dict[str, Any]],
    grand_total: float,
    contingency_pct: float = 0.20,
) -> str:
    """Format per-story breakdown as CSV."""
    lines = [
        "story_id,complexity,tokens,cost_haiku,cost_sonnet,cost_opus,escalation_prob,model_pick,total_cost",
    ]

    for row in breakdown:
        lines.append(
            f"{row['story_id']},{row['complexity']},{int(row['tokens_h'])},"
            f"{row['cost_haiku']},{row['cost_sonnet']},{row['cost_opus']},"
            f"{row['escalation_prob']},{row['model_pick']},{row['total_cost']}"
        )

    contingency = grand_total * contingency_pct
    lines.append(f"TOTAL,,,,,,,{round(grand_total + contingency, 2)}")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Estimate SPIRAL execution cost")
    parser.add_argument("--iterations", type=int, default=1, help="Number of iterations (default: 1)")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers (default: 1)")
    parser.add_argument(
        "--format", choices=["text", "json", "csv"], default="text", help="Output format (default: text)"
    )
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json (default: prd.json)")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv (default: results.tsv)")
    parser.add_argument("--dry-run", action="store_true", help="Show command without API calls")

    args = parser.parse_args()

    # Legacy support: if no args, assume first positional is num_iterations
    if len(sys.argv) == 2 and sys.argv[1].isdigit():
        args.iterations = int(sys.argv[1])
        args.results = sys.argv[2] if len(sys.argv) > 2 else "results.tsv"

    if args.dry_run:
        print("[DRY RUN] Would estimate cost for:")
        print(f"  Iterations: {args.iterations}")
        print(f"  Workers: {args.workers}")
        print(f"  Format: {args.format}")
        print(f"  PRD: {args.prd}")
        print(f"  Results: {args.results}")
        sys.exit(0)

    # Load prd.json
    prd_data = {}
    if os.path.isfile(args.prd):
        try:
            with open(args.prd, encoding="utf-8") as f:
                prd_data = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load {args.prd}: {e}", file=sys.stderr)

    # Estimate per-story breakdown
    breakdown = estimate_story_cost_breakdown(prd_data, args.results)

    if not breakdown:
        # Fallback to legacy behavior if no stories
        prediction = predict_cost_for_n_iterations(args.iterations, args.results)
        total = prediction["estimated_cost"]
        lower = prediction["confidence_lower"]
        upper = prediction["confidence_upper"]
        attempts = prediction["total_attempts"]

        output_msg = (
            f"Estimated cost for {args.iterations} iterations: ${total:.2f} "
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
        sys.exit(0)

    # Compute grand total with contingency
    subtotal = sum(row["total_cost"] for row in breakdown)
    contingency = subtotal * 0.20  # 20% contingency buffer
    grand_total = subtotal + contingency

    # Account for parallelization
    num_stories = len(breakdown)
    adj = compute_parallelization_adjustment(num_stories, args.workers, args.iterations)

    # Adjust grand total for iterations
    adjusted_total = grand_total * args.iterations
    adjusted_contingency = adjusted_total - (subtotal * args.iterations)

    # Output based on format
    if args.format == "json":
        output_dict = {
            "breakdown": breakdown,
            "subtotal": round(subtotal, 2),
            "contingency_pct": 20.0,
            "contingency": round(adjusted_contingency, 2),
            "grand_total": round(adjusted_total, 2),
            "iterations": args.iterations,
            "workers": args.workers,
            "parallelization": adj,
        }
        print(json.dumps(output_dict, indent=2))
    elif args.format == "csv":
        print(format_csv_output(breakdown, subtotal, 0.20))
        print("\nAdjustments:")
        print(f"Iterations: {args.iterations}")
        print(f"Workers: {args.workers}")
        print(f"Grand Total (with {args.iterations} iterations): ${adjusted_total:.2f}")
    else:  # text
        print(format_table_output(breakdown, subtotal, 0.20))
        print("Adjustments:")
        print(f"  Iterations: {args.iterations}")
        print(f"  Workers: {args.workers}")
        print(f"  Iterations per worker: {adj['iterations_per_worker']}")
        print(f"  Total parallel iterations: {adj['total_parallel_iterations']}")
        print(f"\nGrand Total (with {args.iterations} iterations): ${adjusted_total:.2f}")
