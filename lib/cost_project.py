#!/usr/bin/env python3
"""
cost_project.py — Pre-flight API cost projection for SPIRAL runs.

Estimates the API cost of completing all pending stories using historical
results.tsv token data.  Displays a projection table and optionally prompts
for confirmation when projected cost exceeds SPIRAL_COST_WARN_THRESHOLD.

Usage:
    python lib/cost_project.py --prd prd.json --results results.tsv
        [--model sonnet] [--threshold 5.00] [--yes] [--default-tokens 8000]

Exit codes:
    0 — projection shown (or skipped); user confirmed or below threshold
    1 — user declined (answered N at confirmation prompt)
    2 — insufficient history (< 5 usable rows in results.tsv) — projection skipped
    3 — error (missing/corrupt prd.json or I/O failure)
"""
import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from constants import (
    DEFAULT_TOKENS_PER_STORY,
    INPUT_OUTPUT_RATIO,
    MIN_HISTORY_ROWS,
    PRICING,
    TOKENS_PER_SEC_OUTPUT,
)

DEFAULT_MODEL = "sonnet"


def normalise_model(raw: str) -> str:
    """Map any model string to haiku / sonnet / opus."""
    raw_lower = raw.strip().lower() if raw else ""
    for key in PRICING:
        if key in raw_lower:
            return key
    return DEFAULT_MODEL


def _total_tokens_from_duration(duration_sec: float) -> float:
    """Total (input + output) tokens estimated from wall-clock duration."""
    output = duration_sec * TOKENS_PER_SEC_OUTPUT
    input_ = output * INPUT_OUTPUT_RATIO
    return input_ + output


def compute_mean_tokens(results_path: str) -> tuple[float, float, int]:
    """
    Compute mean and population std-dev of total tokens per row from results.tsv.

    Only rows with a positive duration_sec are included.
    Returns (mean, std_dev, usable_row_count).
    """
    if not os.path.isfile(results_path):
        return 0.0, 0.0, 0

    samples: list[float] = []
    with open(results_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                duration = float(row.get("duration_sec") or 0)
            except (ValueError, TypeError):
                duration = 0.0
            if duration > 0:
                samples.append(_total_tokens_from_duration(duration))

    count = len(samples)
    if count == 0:
        return 0.0, 0.0, 0

    mean = sum(samples) / count
    variance = sum((x - mean) ** 2 for x in samples) / count
    std_dev = math.sqrt(variance)
    return mean, std_dev, count


def count_pending(prd_path: str) -> int:
    """Count stories that are neither passed nor skipped/decomposed."""
    if not os.path.isfile(prd_path):
        return 0
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)
    return sum(
        1
        for s in prd.get("userStories", [])
        if not s.get("passes") and not s.get("_skipped") and not s.get("_decomposed")
    )


def project_cost(total_tokens: float, model: str) -> float:
    """Estimate USD cost for *total* token count (input + output combined)."""
    m = normalise_model(model)
    p = PRICING[m]
    # Split into input/output using the same ratio as cost_check.py
    output = total_tokens / (1 + INPUT_OUTPUT_RATIO)
    input_ = total_tokens - output
    return (input_ / 1_000_000) * p["input"] + (output / 1_000_000) * p["output"]


def format_table(
    pending_count: int,
    model: str,
    mean_tokens: float,
    std_tokens: float,
    row_count: int,
    default_tokens: int,
) -> tuple[str, float]:
    """
    Build a cost-projection table.

    Returns (table_str, est_usd) where est_usd is the central estimate.
    """
    m = normalise_model(model)
    est_tokens = mean_tokens if row_count >= MIN_HISTORY_ROWS else float(default_tokens)
    source_label = f"history ({row_count} rows)" if row_count >= MIN_HISTORY_ROWS else "default fallback"

    est_usd = project_cost(est_tokens * pending_count, model)

    lines = [
        "",
        "  ┌──────────────────────────────────────────────────────────────────┐",
        "  │  SPIRAL — Pre-flight Cost Projection                             │",
        "  ├─────────────────────────────┬────────────────────────────────────┤",
        f"  │  Model                      │  {m:<34s}│",
        f"  │  Pending stories            │  {pending_count:<34d}│",
        f"  │  Tokens / story (est.)      │  {int(est_tokens):>10,d}  [{source_label}]{'':<{max(0, 17 - len(source_label))}s}│",
        f"  │  Estimated cost             │  ${est_usd:<33.2f}│",
    ]

    if row_count >= MIN_HISTORY_ROWS and std_tokens > 0 and pending_count > 0:
        low_usd = project_cost(max(0.0, est_tokens - std_tokens) * pending_count, model)
        high_usd = project_cost((est_tokens + std_tokens) * pending_count, model)
        range_str = f"${low_usd:.2f} – ${high_usd:.2f}"
        lines.append(
            f"  │  Confidence range (±1σ)     │  {range_str:<34s}│"
        )

    lines.append("  └──────────────────────────────────────────────────────────────────┘")
    return "\n".join(lines), est_usd


def run_projection(
    prd_path: str,
    results_path: str,
    model: str,
    threshold: float,
    yes: bool,
    default_tokens: int,
) -> int:
    """
    Core projection logic.  Returns an exit code (0 / 1 / 2 / 3).
    """
    # Count pending stories
    try:
        pending_count = count_pending(prd_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  [cost-project] ERROR reading prd.json: {exc}", file=sys.stderr)
        return 3

    if pending_count == 0:
        return 0

    # Compute historical token statistics
    try:
        mean_tokens, std_tokens, row_count = compute_mean_tokens(results_path)
    except OSError as exc:
        print(f"  [cost-project] ERROR reading results.tsv: {exc}", file=sys.stderr)
        return 3

    # Skip projection when insufficient history
    if row_count < MIN_HISTORY_ROWS:
        return 2

    # Resolve model name
    effective_model = model or os.environ.get("SPIRAL_MODEL", DEFAULT_MODEL)

    # Build and print table
    table_str, est_usd = format_table(
        pending_count=pending_count,
        model=effective_model,
        mean_tokens=mean_tokens,
        std_tokens=std_tokens,
        row_count=row_count,
        default_tokens=default_tokens,
    )
    print(table_str)

    # Prompt when projected cost exceeds threshold
    if threshold > 0 and est_usd > threshold:
        prompt_msg = f"  Estimated cost: ${est_usd:.2f} — Continue? [y/N] "
        if yes:
            print(f"{prompt_msg}y (--yes flag set)")
            return 0
        try:
            answer = input(prompt_msg).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes"):
            print("  [cost-project] Aborted by user.")
            return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-flight API cost projection for SPIRAL runs"
    )
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--model", default="", help="Model tier (haiku|sonnet|opus)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=5.00,
        help="Cost warning threshold in USD (default: 5.00; 0 = never prompt)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt — for non-interactive CI environments",
    )
    parser.add_argument(
        "--default-tokens",
        type=int,
        default=DEFAULT_TOKENS_PER_STORY,
        help=f"Fallback tokens/story when history is unavailable (default: {DEFAULT_TOKENS_PER_STORY})",
    )
    args = parser.parse_args(argv)

    return run_projection(
        prd_path=args.prd,
        results_path=args.results,
        model=args.model,
        threshold=args.threshold,
        yes=args.yes,
        default_tokens=args.default_tokens,
    )


if __name__ == "__main__":
    sys.exit(main())
