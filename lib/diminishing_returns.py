#!/usr/bin/env python3
"""
diminishing_returns.py — Diminishing returns detection for Phase C.

Analyzes cost-per-new-pass across iterations. When the cost to implement
each new story doubles 3+ consecutive times, signals a diminishing returns
condition and suggests exiting to avoid budget waste.

US-783: Phase C Diminishing Returns Exit
"""

from pathlib import Path
from typing import Optional

from lib.results_tsv import parse_results_tsv


def parse_iteration_costs(results_path: str) -> dict[int, dict[str, int | float]]:
    """
    Parse results.tsv and extract cost and pass count per iteration.

    Returns:
        {
            iteration_num: {
                "new_passes": count of stories with status='accept' in this iteration,
                "total_cost_usd": sum of input tokens * rate (estimated),
                "story_count": number of stories attempted,
            },
            ...
        }

    Cost estimation: approximate $0.80 per 1M input tokens (Claude Haiku rate).
    """
    records = parse_results_tsv(results_path)
    if not records:
        return {}

    # Group records by spiral_iter
    iter_data: dict[int, dict[str, int | float]] = {}

    for record in records:
        try:
            iter_num = int(record.spiral_iter)
        except (ValueError, TypeError):
            continue

        if iter_num not in iter_data:
            iter_data[iter_num] = {
                "new_passes": 0,
                "total_cost_usd": 0.0,
                "story_count": 0,
            }

        # Count new passes (accept status)
        if record.status and record.status.lower() == "accept":
            iter_data[iter_num]["new_passes"] += 1

        # Estimate cost from input tokens (rough estimate)
        try:
            cache_read = int(record.cache_read_tokens or 0)
            cache_creation = int(record.cache_creation_tokens or 0)
            # Cost: cache reads are cheaper (~80% of creation cost)
            iter_cost = (cache_read * 0.0008) + (cache_creation * 0.001)
            iter_data[iter_num]["total_cost_usd"] += iter_cost
        except (ValueError, TypeError):
            pass

        iter_data[iter_num]["story_count"] += 1

    return iter_data


def calculate_cost_per_pass(
    iteration_data: dict[int, dict[str, int | float]],
) -> dict[int, Optional[float]]:
    """
    Calculate cost-per-new-pass for each iteration.

    Returns:
        {iteration_num: cost_per_pass or None (if no passes)}
    """
    cost_per_pass: dict[int, Optional[float]] = {}

    for iter_num in sorted(iteration_data.keys()):
        data = iteration_data[iter_num]
        new_passes = data["new_passes"]
        total_cost = data["total_cost_usd"]

        if new_passes > 0:
            cost_per_pass[iter_num] = total_cost / new_passes
        else:
            cost_per_pass[iter_num] = None

    return cost_per_pass


def detect_diminishing_returns(
    cost_per_pass: dict[int, Optional[float]], multiplier: float = 2.0
) -> tuple[bool, list[tuple[int, float]]]:
    """
    Detect if cost-per-pass doubled 3+ consecutive times.

    Args:
        cost_per_pass: {iteration_num: cost_per_pass or None}
        multiplier: threshold multiplier (default 2.0 = doubling)

    Returns:
        (is_diminishing: bool, sequence: list of (iter, cost) tuples showing the pattern)

    A valid sequence requires 3 consecutive iterations with cost_per_pass data,
    and each iteration's cost >= previous_cost * multiplier.
    """
    sorted_iters = sorted(
        [it for it, cost in cost_per_pass.items() if cost is not None]
    )

    if len(sorted_iters) < 3:
        return False, []

    # Slide a 3-iteration window looking for 3 consecutive doublings
    for i in range(len(sorted_iters) - 2):
        iter1, iter2, iter3 = sorted_iters[i : i + 3]
        cost1 = cost_per_pass[iter1]
        cost2 = cost_per_pass[iter2]
        cost3 = cost_per_pass[iter3]

        if cost1 is None or cost2 is None or cost3 is None:
            continue

        # Check if each doubled (or exceeded multiplier threshold)
        if cost2 >= cost1 * multiplier and cost3 >= cost2 * multiplier:
            sequence = [(iter1, cost1), (iter2, cost2), (iter3, cost3)]
            return True, sequence

    return False, []


def generate_diagnostic_report(
    iteration_data: dict[int, dict[str, int | float]],
    cost_per_pass: dict[int, Optional[float]],
    detected: bool,
    sequence: Optional[list[tuple[int, float]]] = None,
) -> str:
    """
    Generate formatted diagnostic report showing cost trends.

    Returns:
        Multi-line string suitable for printing to terminal.
    """
    lines = []
    lines.append("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("  💡 DIMINISHING RETURNS ANALYSIS")
    lines.append("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    sorted_iters = sorted(iteration_data.keys())

    if not sorted_iters:
        lines.append("  No iteration data available.")
        return "\n".join(lines)

    # Table header
    lines.append("  Iteration │ Stories Passed │ Cost (USD) │ Cost/Pass │ Trend")
    lines.append("  ──────────┼────────────────┼────────────┼───────────┼──────")

    prev_cpp = None
    for iter_num in sorted_iters:
        data = iteration_data[iter_num]
        passes = data["new_passes"]
        cost = data["total_cost_usd"]
        cpp = cost_per_pass.get(iter_num)

        trend = ""
        if cpp is not None and prev_cpp is not None:
            ratio = cpp / prev_cpp
            if ratio >= 2.0:
                trend = "📈 2x+"
            elif ratio >= 1.5:
                trend = "📈 1.5x"
            elif ratio < 0.5:
                trend = "📉 0.5x"
            else:
                trend = "→ stable"

        cpp_str = f"${cpp:.2f}" if cpp is not None else "N/A"
        lines.append(
            f"  {iter_num:9d} │ {passes:14d} │ ${cost:9.4f} │ {cpp_str:9s} │ {trend}"
        )

        if cpp is not None:
            prev_cpp = cpp

    lines.append("  ──────────┴────────────────┴────────────┴───────────┴──────")
    lines.append("")

    if detected and sequence:
        lines.append("  ⚠️  DIMINISHING RETURNS DETECTED")
        lines.append("")
        lines.append("  Three consecutive iterations where cost-per-pass ≥ 2.0x:")
        for idx, (iter_num, cpp) in enumerate(sequence, 1):
            lines.append(f"    {idx}. Iteration {iter_num}: ${cpp:.2f} per story")
        lines.append("")
        lines.append("  Recommendation: Exit loop to avoid budget waste.")
        lines.append("  Consider: story complexity review, scope reduction, or")
        lines.append("  deferring remaining stories to next session.")
    else:
        lines.append("  ✓ Cost-per-pass trend is healthy. Continuing loop.")

    lines.append("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    return "\n".join(lines)


def check_diminishing_returns(
    results_path: str, multiplier: float = 2.0
) -> tuple[bool, str]:
    """
    Main entry point: check if SPIRAL should exit due to diminishing returns.

    Args:
        results_path: path to results.tsv
        multiplier: cost multiplier threshold (default 2.0)

    Returns:
        (should_exit: bool, diagnostic_report: str)
    """
    if not Path(results_path).exists():
        return False, ""

    iteration_data = parse_iteration_costs(results_path)
    if not iteration_data:
        return False, ""

    cost_per_pass = calculate_cost_per_pass(iteration_data)
    detected, sequence = detect_diminishing_returns(cost_per_pass, multiplier)

    report = generate_diagnostic_report(
        iteration_data, cost_per_pass, detected, sequence
    )

    return detected, report
