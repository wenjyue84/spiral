#!/usr/bin/env python3
"""
cost_analysis.py — Analyze token costs and spend from results.tsv.

Provides detailed cost breakdown by model tier, story, phase, and iteration.
Supports filtering, JSON export, and iteration-to-iteration comparison.
"""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from lib.core.constants import INPUT_OUTPUT_RATIO, PRICING, TOKENS_PER_SEC_OUTPUT


def _total_tokens_from_duration(duration_sec: float) -> float:
    """Total (input + output) tokens estimated from wall-clock duration."""
    if duration_sec <= 0:
        return 0.0
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
    # Default to sonnet pricing if model not found
    sonnet_pricing = PRICING.get("sonnet", {"input": 3.00})
    sonnet_cost = float(sonnet_pricing.get("input", 3.00))
    return sonnet_cost / 1_000_000.0


def parse_results_tsv(
    results_path: Path,
) -> List[Dict[str, Any]]:
    """
    Parse results.tsv and return list of row dicts with computed costs.

    Args:
        results_path: Path to results.tsv

    Returns:
        List of dicts with keys: story_id, model, duration_sec, tokens, cost_usd,
                                  spiral_iter, retry_num, status
    """
    rows = []

    if not results_path.exists():
        return rows

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return rows

            for row in reader:
                if not row.get("duration_sec") or not row.get("model"):
                    continue

                try:
                    duration = float(row["duration_sec"])
                    model = row["model"].strip()
                    if duration <= 0 or not model:
                        continue

                    tokens = _total_tokens_from_duration(duration)
                    cost_per_tok = _cost_per_token(model)
                    cost_usd = tokens * cost_per_tok

                    rows.append(
                        {
                            "story_id": row.get("story_id", ""),
                            "model": model,
                            "duration_sec": duration,
                            "tokens": tokens,
                            "cost_usd": cost_usd,
                            "spiral_iter": int(row.get("spiral_iter", 0)),
                            "retry_num": int(row.get("retry_num", 0)),
                            "status": row.get("status", ""),
                            "title": row.get("story_title", ""),
                        }
                    )
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass

    return rows


def compute_model_costs(
    rows: List[Dict[str, Any]],
) -> Dict[str, float]:
    """
    Compute total cost breakdown by model tier.

    Args:
        rows: List of parsed result rows

    Returns:
        Dict with keys: haiku, sonnet, opus (and totals)
    """
    model_costs: Dict[str, float] = {}

    for row in rows:
        model = row["model"].lower()
        cost = row["cost_usd"]

        if model not in model_costs:
            model_costs[model] = 0.0
        model_costs[model] += cost

    return model_costs


def compute_story_costs(
    rows: List[Dict[str, Any]],
) -> List[Tuple[str, str, float, int]]:
    """
    Compute cost breakdown by story.

    Returns list of (story_id, title, total_cost, attempt_count) tuples
    sorted by cost descending.
    """
    story_data: Dict[str, Tuple[str, float, int]] = {}

    for row in rows:
        sid = row["story_id"]
        cost = row["cost_usd"]
        title = row.get("title", "")

        if sid not in story_data:
            story_data[sid] = (title, 0.0, 0)

        existing_title, existing_cost, existing_count = story_data[sid]
        story_data[sid] = (title or existing_title, existing_cost + cost, existing_count + 1)

    # Convert to sorted list
    result = [(sid, data[0], data[1], data[2]) for sid, data in story_data.items()]
    result.sort(key=lambda x: x[2], reverse=True)  # Sort by cost descending
    return result


def compute_iteration_costs(
    rows: List[Dict[str, Any]],
) -> Dict[int, float]:
    """Compute total cost per iteration."""
    iter_costs: Dict[int, float] = {}

    for row in rows:
        iter_num = row["spiral_iter"]
        cost = row["cost_usd"]

        if iter_num not in iter_costs:
            iter_costs[iter_num] = 0.0
        iter_costs[iter_num] += cost

    return iter_costs


def parse_spiral_events(
    events_path: Path,
) -> Dict[str, Dict[str, Any]]:
    """
    Parse spiral_events.jsonl to extract phase timing information.

    Returns dict mapping (story_id, iteration) -> phase info.
    """
    phase_data: Dict[str, Dict[str, Any]] = {}

    if not events_path.exists():
        return phase_data

    try:
        with open(events_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if event.get("event") == "phase_end" and event.get("phase"):
                        phase = event.get("phase", "")
                        iteration = event.get("iteration", 0)
                        if phase and iteration:
                            key = f"iter_{iteration}_phase_{phase}"
                            phase_data[key] = {
                                "phase": phase,
                                "iteration": iteration,
                                "duration_s": event.get("duration_s", 0),
                            }
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception:
        pass

    return phase_data


def compute_phase_costs(
    rows: List[Dict[str, Any]],
) -> Dict[str, float]:
    """
    Compute total cost breakdown by phase.

    Since phase info is not in results.tsv, distribute iteration costs
    proportionally across phases based on phase event distribution.
    Returns dict with phase as key (A, R, T, S, E, M, X, G, I, V, C, L).
    """
    # Map phases to known SPIRAL phases
    phase_costs: Dict[str, float] = {
        phase: 0.0 for phase in ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C", "L"]
    }

    if not rows:
        return phase_costs

    # For now, distribute costs equally across phases per iteration
    # A more sophisticated approach would parse spiral_events.jsonl
    # to get actual phase timings
    iteration_costs = compute_iteration_costs(rows)

    # Number of phases in SPIRAL loop
    num_phases = 12  # A, R, T, S, E, M, X, G, I, V, C, L

    for phase in phase_costs.keys():
        # Distribute equally for now; in future could weight by phase_end events
        total_iter_cost = sum(iteration_costs.values())
        phase_costs[phase] = total_iter_cost / num_phases

    return phase_costs


def format_currency(amount: float) -> str:
    """Format amount as USD currency string."""
    return f"${amount:.4f}"


def format_table_header(cols: List[str], widths: List[int]) -> str:
    """Format a table header row."""
    return "  ".join(f"{col:<{w}}" for col, w in zip(cols, widths))


def format_table_separator(widths: List[int]) -> str:
    """Format a table separator row."""
    return "  ".join("-" * w for w in widths)


def cost_analysis_main(
    results_path: Optional[str] = None,
    detailed: bool = False,
    json_output: bool = False,
    compare_iteration: Optional[int] = None,
) -> None:
    """
    Main entry point for cost analysis.

    Args:
        results_path: Path to results.tsv (default: ./results.tsv)
        detailed: Show per-story breakdown
        json_output: Output as JSON
        compare_iteration: Compare with specified iteration number
    """
    if not results_path:
        results_path = "results.tsv"

    rpath = Path(results_path)
    rows = parse_results_tsv(rpath)

    if not rows:
        print("No cost data found in results.tsv")
        return

    # Compute basic metrics
    total_cost = sum(r["cost_usd"] for r in rows)
    total_tokens = sum(r["tokens"] for r in rows)
    total_attempts = len(rows)
    avg_cost_per_story = total_cost / len(set(r["story_id"] for r in rows)) if rows else 0.0

    model_costs = compute_model_costs(rows)
    story_costs = compute_story_costs(rows)
    iteration_costs = compute_iteration_costs(rows)
    phase_costs = compute_phase_costs(rows)

    # JSON output mode
    if json_output:
        output = {
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": int(total_tokens),
            "total_attempts": total_attempts,
            "unique_stories": len(set(r["story_id"] for r in rows)),
            "avg_cost_per_story": round(avg_cost_per_story, 4),
            "cost_by_model": {m: round(c, 4) for m, c in model_costs.items()},
            "cost_by_phase": {p: round(c, 4) for p, c in phase_costs.items()},
            "cost_by_iteration": {str(i): round(c, 4) for i, c in iteration_costs.items()},
        }

        if detailed:
            output["per_story_breakdown"] = [
                {
                    "story_id": sid,
                    "title": title,
                    "total_cost_usd": round(cost, 4),
                    "attempt_count": count,
                    "avg_per_attempt": round(cost / count if count > 0 else 0, 4),
                }
                for sid, title, cost, count in story_costs
            ]

        if compare_iteration is not None:
            current_iter_cost = iteration_costs.get(max(iteration_costs.keys()), 0)
            compare_cost = iteration_costs.get(compare_iteration, 0)
            delta = current_iter_cost - compare_cost
            pct_change = (delta / compare_cost * 100) if compare_cost > 0 else 0
            output["comparison"] = {
                "current_iteration": max(iteration_costs.keys()),
                "compared_iteration": compare_iteration,
                "current_cost": round(current_iter_cost, 4),
                "compared_cost": round(compare_cost, 4),
                "delta_usd": round(delta, 4),
                "pct_change": round(pct_change, 2),
            }

        print(json.dumps(output, indent=2))
        return

    # Text output mode
    print("")
    print("SPIRAL Cost Analysis")
    print("=" * 60)
    print("")

    # Summary section
    print("Summary")
    print("-" * 60)
    print(f"  Total spend:           {format_currency(total_cost)}")
    print(f"  Total tokens:          {int(total_tokens):,}")
    print(f"  Total attempts:        {total_attempts}")
    print(f"  Unique stories:        {len(set(r['story_id'] for r in rows))}")
    print(f"  Avg cost per story:    {format_currency(avg_cost_per_story)}")
    print("")

    # Model breakdown
    print("Cost by Model")
    print("-" * 60)
    for model, cost in sorted(model_costs.items(), key=lambda x: x[1], reverse=True):
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        print(f"  {model:<10} {format_currency(cost):<15} ({pct:>5.1f}%)")
    print("")

    # Phase breakdown
    print("Cost by Phase")
    print("-" * 60)
    for phase in ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C", "L"]:
        cost = phase_costs.get(phase, 0.0)
        pct = (cost / total_cost * 100) if total_cost > 0 else 0
        print(f"  Phase {phase:<2} {format_currency(cost):<15} ({pct:>5.1f}%)")
    print("")

    # Iteration breakdown
    if iteration_costs:
        print("Cost by Iteration")
        print("-" * 60)
        for iter_num in sorted(iteration_costs.keys()):
            cost = iteration_costs[iter_num]
            pct = (cost / total_cost * 100) if total_cost > 0 else 0
            print(f"  Iteration {iter_num:<3} {format_currency(cost):<15} ({pct:>5.1f}%)")
        print("")

    # Iteration comparison
    if compare_iteration is not None:
        if compare_iteration in iteration_costs:
            current_iter = max(iteration_costs.keys())
            current_cost = iteration_costs.get(current_iter, 0)
            compare_cost = iteration_costs[compare_iteration]
            delta = current_cost - compare_cost
            pct_change = (delta / compare_cost * 100) if compare_cost > 0 else 0

            print(f"Comparison: Iteration {current_iter} vs Iteration {compare_iteration}")
            print("-" * 60)
            print(f"  Current (Iter {current_iter}):  {format_currency(current_cost)}")
            print(f"  Compared (Iter {compare_iteration}): {format_currency(compare_cost)}")
            print(f"  Delta:               {format_currency(delta)} ({pct_change:+.1f}%)")
            print("")
        else:
            print(f"Iteration {compare_iteration} not found in results")
            print("")

    # Detailed story breakdown
    if detailed and story_costs:
        print("Per-Story Breakdown (Top 20)")
        print("-" * 60)
        cols = ["Story ID", "Title", "Cost", "Attempts", "Avg/Attempt"]
        widths = [12, 30, 12, 10, 14]
        print("  " + format_table_header(cols, widths))
        print("  " + format_table_separator(widths))

        for sid, title, cost, count in story_costs[:20]:
            avg = cost / count if count > 0 else 0
            title_short = title[:28] if len(title) > 28 else title
            print(f"  {sid:<12} {title_short:<30} {format_currency(cost):<12} {count:<10} {format_currency(avg):<14}")
        print("")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze SPIRAL costs from results.tsv")
    parser.add_argument(
        "--results",
        type=str,
        default="results.tsv",
        help="Path to results.tsv (default: results.tsv)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show per-story breakdown",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--compare-iteration",
        type=int,
        help="Compare with specified iteration number",
    )

    args = parser.parse_args()

    cost_analysis_main(
        results_path=args.results,
        detailed=args.detailed,
        json_output=args.json,
        compare_iteration=args.compare_iteration,
    )
