#!/usr/bin/env python3
"""
cli_compare_iterations.py — Compare story status between two iterations.

Shows delta analysis: new stories, recovered stories, still-failing stories,
token delta, and cost delta between two iterations.
"""

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class IterationData:
    """Stories and metrics for a single iteration."""

    iteration: int
    stories: dict[str, dict[str, Any]]  # story_id -> {status, model, duration, tokens, cost}
    total_tokens: int
    total_cost: float


def load_iteration_data(results_path: Path, iteration: int) -> IterationData:
    """Load all story records for a single iteration from results.tsv.

    Args:
        results_path: Path to results.tsv
        iteration: SPIRAL iteration number

    Returns:
        IterationData with stories dict and aggregated metrics
    """
    stories: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_cost = 0.0

    if not results_path.exists():
        return IterationData(iteration, stories, total_tokens, total_cost)

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return IterationData(iteration, stories, total_tokens, total_cost)

            for row in reader:
                try:
                    iter_num = int(row.get("spiral_iter", 0) or 0)
                except (ValueError, TypeError):
                    iter_num = 0

                if iter_num != iteration:
                    continue

                story_id = row.get("story_id", "")
                if not story_id:
                    continue

                # For each story, keep the latest attempt (highest retry_num)
                try:
                    retry = int(row.get("retry_num", 0) or 0)
                except (ValueError, TypeError):
                    retry = 0

                if story_id in stories:
                    existing_retry = int(stories[story_id].get("retry_num", 0) or 0)
                    if retry < existing_retry:
                        continue

                # Calculate tokens and cost
                try:
                    cache_read = int(row.get("cache_read_tokens", 0) or 0)
                    cache_create = int(row.get("cache_creation_tokens", 0) or 0)
                except (ValueError, TypeError):
                    cache_read = 0
                    cache_create = 0

                tokens = cache_read + cache_create
                # Simplified cost calculation: ~$0.003 per 1M tokens
                cost = tokens * 0.000003

                stories[story_id] = {
                    "status": row.get("status", ""),
                    "model": row.get("model", ""),
                    "duration": row.get("duration_sec", "0"),
                    "tokens": tokens,
                    "cost": cost,
                    "retry_num": retry,
                }

                total_tokens += tokens
                total_cost += cost

    except OSError:
        pass

    return IterationData(iteration, stories, total_tokens, total_cost)


def compute_story_deltas(
    iter_a: IterationData, iter_b: IterationData
) -> dict[str, Any]:
    """Compute story status changes between two iterations.

    Args:
        iter_a: Earlier iteration
        iter_b: Later iteration

    Returns:
        dict with keys: new_stories, recovered_stories, still_failing, regressed
    """
    new_stories = []
    recovered_stories = []
    still_failing = []
    regressed = []

    # Stories in iter_b but not in iter_a
    for story_id in iter_b.stories:
        if story_id not in iter_a.stories:
            new_stories.append(story_id)

    # Stories in both iterations
    for story_id in iter_b.stories:
        if story_id not in iter_a.stories:
            continue

        status_a = iter_a.stories[story_id].get("status", "")
        status_b = iter_b.stories[story_id].get("status", "")

        # Status values: 'pass', 'keep', 'reject', etc.
        failed_a = status_a in ("reject", "fail")
        failed_b = status_b in ("reject", "fail")
        passed_a = status_a in ("pass", "keep")
        passed_b = status_b in ("pass", "keep")

        if failed_a and passed_b:
            recovered_stories.append(story_id)
        elif failed_a and failed_b:
            still_failing.append(story_id)
        elif passed_a and failed_b:
            regressed.append(story_id)

    return {
        "new_stories": new_stories,
        "recovered_stories": recovered_stories,
        "still_failing": still_failing,
        "regressed": regressed,
    }


def calculate_token_delta(iter_a: IterationData, iter_b: IterationData) -> dict[str, Any]:
    """Calculate token and cost deltas between iterations.

    Args:
        iter_a: Earlier iteration
        iter_b: Later iteration

    Returns:
        dict with keys: token_delta, cost_delta, iter_a_tokens, iter_b_tokens, iter_a_cost, iter_b_cost
    """
    token_delta = iter_b.total_tokens - iter_a.total_tokens
    cost_delta = iter_b.total_cost - iter_a.total_cost

    return {
        "token_delta": token_delta,
        "cost_delta": round(cost_delta, 4),
        "iter_a_tokens": iter_a.total_tokens,
        "iter_b_tokens": iter_b.total_tokens,
        "iter_a_cost": round(iter_a.total_cost, 4),
        "iter_b_cost": round(iter_b.total_cost, 4),
    }


def format_delta_report(
    iter_a: int, iter_b: int, deltas: dict[str, Any], token_info: dict[str, Any]
) -> str:
    """Format plain text delta report.

    Args:
        iter_a: Earlier iteration number
        iter_b: Later iteration number
        deltas: Output from compute_story_deltas()
        token_info: Output from calculate_token_delta()

    Returns:
        Formatted plain text report
    """
    new = deltas.get("new_stories", [])
    recovered = deltas.get("recovered_stories", [])
    still_failing = deltas.get("still_failing", [])
    regressed = deltas.get("regressed", [])

    token_delta = token_info.get("token_delta", 0)
    cost_delta = token_info.get("cost_delta", 0.0)

    lines = []
    lines.append(f"Iteration {iter_a} → {iter_b} (Delta Analysis)")
    lines.append("=" * 60)
    lines.append("")

    lines.append(f"New stories: {len(new)}")
    if new:
        lines.append(f"  {', '.join(new)}")
    lines.append("")

    lines.append(f"Failed→Recovered: {len(recovered)}")
    if recovered:
        lines.append(f"  {', '.join(recovered)}")
    lines.append("")

    lines.append(f"Still Failing: {len(still_failing)}")
    if still_failing:
        lines.append(f"  {', '.join(still_failing)}")
    lines.append("")

    if regressed:
        lines.append(f"Regressed (Passed→Failed): {len(regressed)}")
        lines.append(f"  {', '.join(regressed)}")
        lines.append("")

    lines.append(f"Token delta: {token_delta:+,}")
    lines.append(f"Cost delta: ${cost_delta:+.4f}")
    lines.append("")

    return "\n".join(lines)


def format_detailed_report(
    iter_a: int,
    iter_b: int,
    iter_a_data: IterationData,
    iter_b_data: IterationData,
    deltas: dict[str, Any],
    token_info: dict[str, Any],
) -> str:
    """Format detailed plain text report with per-story status.

    Args:
        iter_a: Earlier iteration number
        iter_b: Later iteration number
        iter_a_data: IterationData for earlier iteration
        iter_b_data: IterationData for later iteration
        deltas: Output from compute_story_deltas()
        token_info: Output from calculate_token_delta()

    Returns:
        Formatted detailed report
    """
    base_report = format_delta_report(iter_a, iter_b, deltas, token_info)
    lines = base_report.split("\n")
    lines.append("Detailed Status")
    lines.append("=" * 60)
    lines.append("")

    # New stories
    new = deltas.get("new_stories", [])
    if new:
        lines.append("NEW STORIES:")
        for story_id in new:
            story_info = iter_b_data.stories.get(story_id, {})
            status = story_info.get("status", "?")
            model = story_info.get("model", "?")
            duration = story_info.get("duration", "0")
            tokens = story_info.get("tokens", 0)
            lines.append(
                f"  {story_id}: {status.upper()} ({duration}s, {model}, {tokens:,} tokens)"
            )
        lines.append("")

    # Recovered stories
    recovered = deltas.get("recovered_stories", [])
    if recovered:
        lines.append("RECOVERED (Failed→Passed):")
        for story_id in recovered:
            iter_a_info = iter_a_data.stories.get(story_id, {})
            iter_b_info = iter_b_data.stories.get(story_id, {})
            old_status = iter_a_info.get("status", "?").upper()
            new_status = iter_b_info.get("status", "?").upper()
            model = iter_b_info.get("model", "?")
            duration = iter_b_info.get("duration", "0")
            lines.append(f"  {story_id}: {old_status}→{new_status} ({duration}s, {model})")
        lines.append("")

    # Still failing
    still_failing = deltas.get("still_failing", [])
    if still_failing:
        lines.append("STILL FAILING:")
        for story_id in still_failing:
            story_info = iter_b_data.stories.get(story_id, {})
            status = story_info.get("status", "?")
            model = story_info.get("model", "?")
            retry_num = story_info.get("retry_num", 0)
            lines.append(f"  {story_id}: {status.upper()} (retry #{retry_num}, {model})")
        lines.append("")

    # Regressed
    regressed = deltas.get("regressed", [])
    if regressed:
        lines.append("REGRESSED (Passed→Failed):")
        for story_id in regressed:
            iter_a_info = iter_a_data.stories.get(story_id, {})
            iter_b_info = iter_b_data.stories.get(story_id, {})
            old_status = iter_a_info.get("status", "?").upper()
            new_status = iter_b_info.get("status", "?").upper()
            model = iter_b_info.get("model", "?")
            lines.append(f"  {story_id}: {old_status}→{new_status} ({model})")
        lines.append("")

    return "\n".join(lines)


def format_json_report(
    iter_a: int,
    iter_b: int,
    deltas: dict[str, Any],
    token_info: dict[str, Any],
) -> str:
    """Format structured JSON delta report.

    Args:
        iter_a: Earlier iteration number
        iter_b: Later iteration number
        deltas: Output from compute_story_deltas()
        token_info: Output from calculate_token_delta()

    Returns:
        JSON string
    """
    report = {
        "iteration_a": iter_a,
        "iteration_b": iter_b,
        "new_stories": deltas.get("new_stories", []),
        "recovered_stories": deltas.get("recovered_stories", []),
        "still_failing": deltas.get("still_failing", []),
        "regressed": deltas.get("regressed", []),
        "token_delta": token_info.get("token_delta", 0),
        "cost_delta": token_info.get("cost_delta", 0.0),
        "iter_a_tokens": token_info.get("iter_a_tokens", 0),
        "iter_b_tokens": token_info.get("iter_b_tokens", 0),
        "iter_a_cost": token_info.get("iter_a_cost", 0.0),
        "iter_b_cost": token_info.get("iter_b_cost", 0.0),
    }
    return json.dumps(report, indent=2)


def main() -> int:
    """CLI entry point for spiral compare-iterations command."""
    import argparse

    parser = argparse.ArgumentParser(description="Compare story status between two iterations")
    parser.add_argument("iter_a", type=int, help="Earlier iteration number")
    parser.add_argument("iter_b", type=int, help="Later iteration number")
    parser.add_argument(
        "--results", type=Path, default=Path("results.tsv"), help="Path to results.tsv"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--detailed", action="store_true", help="Include per-story details")

    args = parser.parse_args()

    if not args.results.exists():
        print(f"[spiral] ERROR: {args.results} not found", file=sys.stderr)
        return 1

    # Load data
    iter_a_data = load_iteration_data(args.results, args.iter_a)
    iter_b_data = load_iteration_data(args.results, args.iter_b)

    if not iter_a_data.stories:
        print(f"[spiral] WARNING: No stories found for iteration {args.iter_a}", file=sys.stderr)
    if not iter_b_data.stories:
        print(f"[spiral] WARNING: No stories found for iteration {args.iter_b}", file=sys.stderr)

    # Compute deltas
    deltas = compute_story_deltas(iter_a_data, iter_b_data)
    token_info = calculate_token_delta(iter_a_data, iter_b_data)

    # Output
    if args.json:
        print(format_json_report(args.iter_a, args.iter_b, deltas, token_info))
    elif args.detailed:
        print(
            format_detailed_report(
                args.iter_a, args.iter_b, iter_a_data, iter_b_data, deltas, token_info
            )
        )
    else:
        print(format_delta_report(args.iter_a, args.iter_b, deltas, token_info))

    return 0


if __name__ == "__main__":
    sys.exit(main())
