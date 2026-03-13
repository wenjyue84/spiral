#!/usr/bin/env python3
"""
cost_check.py — Compute cumulative estimated API cost from results.tsv.

Reads results.tsv (produced by ralph.sh append_result), estimates USD cost
per row using Anthropic 2025 pricing, and prints cumulative cost.

Usage:
    python lib/cost_check.py --results results.tsv [--ceiling 50.0]

Exit codes:
    0 — under ceiling (or no ceiling set)
    2 — cumulative cost >= ceiling (budget exceeded)
    1 — error (missing file, bad data)
"""
import argparse
import csv
import os
import sys

# Anthropic 2025 pricing per million tokens (input / output)
# Source: technicalNotes in US-043
PRICING = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}

# Default model when results.tsv has an unrecognised or empty model field
DEFAULT_MODEL = "sonnet"

# Rough token estimate from duration: ~20 tokens/sec output, input ~= 3x output
# This is a coarse heuristic when actual token counts aren't available.
TOKENS_PER_SEC_OUTPUT = 20
INPUT_OUTPUT_RATIO = 3.0


def estimate_tokens_from_duration(duration_sec: float) -> tuple[float, float]:
    """Return (input_tokens, output_tokens) estimated from wall-clock duration."""
    output_tokens = duration_sec * TOKENS_PER_SEC_OUTPUT
    input_tokens = output_tokens * INPUT_OUTPUT_RATIO
    return input_tokens, output_tokens


def normalise_model(raw: str) -> str:
    """Map model string to one of haiku/sonnet/opus."""
    raw_lower = raw.strip().lower() if raw else ""
    for key in PRICING:
        if key in raw_lower:
            return key
    return DEFAULT_MODEL


def compute_row_cost(row: dict) -> float:
    """Estimate USD cost for a single results.tsv row."""
    model = normalise_model(row.get("model", ""))
    pricing = PRICING[model]

    duration_str = row.get("duration_sec", "0")
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        duration = 0.0

    if duration <= 0:
        return 0.0

    input_tokens, output_tokens = estimate_tokens_from_duration(duration)
    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return cost


def compute_cumulative_cost(results_path: str) -> tuple[float, int]:
    """Read results.tsv and return (total_usd, row_count)."""
    if not os.path.isfile(results_path):
        return 0.0, 0

    total = 0.0
    count = 0
    with open(results_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            total += compute_row_cost(row)
            count += 1
    return total, count


def format_cost_summary(total: float, count: int, ceiling: float | None) -> str:
    """Return a human-readable cost summary string."""
    lines = [f"  [cost] Cumulative estimated cost: ${total:.2f} USD ({count} attempts)"]
    if ceiling is not None and ceiling > 0:
        remaining = max(0.0, ceiling - total)
        lines.append(f"  [cost] Budget ceiling: ${ceiling:.2f} | Remaining: ${remaining:.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check cumulative API cost")
    parser.add_argument("--results", required=True, help="Path to results.tsv")
    parser.add_argument("--ceiling", type=float, default=0.0,
                        help="Cost ceiling in USD (0 = disabled)")
    args = parser.parse_args(argv)

    total, count = compute_cumulative_cost(args.results)
    print(format_cost_summary(total, count, args.ceiling if args.ceiling > 0 else None))

    if args.ceiling > 0 and total >= args.ceiling:
        print(f"  [cost] BUDGET EXCEEDED: ${total:.2f} >= ${args.ceiling:.2f} — aborting")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
