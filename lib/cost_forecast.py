"""lib/cost_forecast.py — Cost and timeline forecasting from results.tsv velocity data (US-650)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

PASS_STATUSES = {"keep", "pass", "success"}


def load_results(path: Path) -> list[dict[str, str]]:
    """Load results.tsv into a list of row dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _row_tokens(row: dict[str, str]) -> int:
    """Sum all token columns in a row."""
    total = 0
    for col in ("cache_read_tokens", "cache_creation_tokens", "review_tokens"):
        try:
            total += int(row.get(col, 0) or 0)
        except (ValueError, TypeError):
            pass
    return total


def compute_velocity(
    rows: list[dict[str, str]],
    last_n_iterations: int = 5,
) -> dict[str, float]:
    """Compute velocity metrics from the last N spiral iterations.

    Returns dict with keys:
        velocity: completed stories per iteration
        cost_velocity: total tokens per iteration
        completed_iterations: actual number of iterations observed
    """
    iter_data: dict[int, dict[str, int]] = {}
    for row in rows:
        try:
            it = int(row.get("spiral_iter", 0) or 0)
        except (ValueError, TypeError):
            continue
        if it not in iter_data:
            iter_data[it] = {"completed": 0, "tokens": 0}
        status = (row.get("status") or "").strip().lower()
        if status in PASS_STATUSES:
            iter_data[it]["completed"] += 1
        iter_data[it]["tokens"] += _row_tokens(row)

    if not iter_data:
        return {"velocity": 0.0, "cost_velocity": 0.0, "completed_iterations": 0.0}

    sorted_iters = sorted(iter_data.keys())[-last_n_iterations:]
    n = len(sorted_iters)
    total_completed = sum(iter_data[i]["completed"] for i in sorted_iters)
    total_tokens = sum(iter_data[i]["tokens"] for i in sorted_iters)

    return {
        "velocity": total_completed / n,
        "cost_velocity": total_tokens / n,
        "completed_iterations": float(n),
    }


def forecast(
    prd_path: Path,
    results_path: Path,
    last_n: int = 5,
) -> dict[str, float | int]:
    """Forecast remaining cost and timeline from velocity data.

    Returns dict with keys:
        remaining_stories: int — stories not yet passing
        iterations_needed: float — estimated iterations to complete (-1 if infinite)
        projected_cost: float — total tokens projected to finish
        confidence_pct: float — 0-100, based on data availability
    """
    remaining_stories = 0
    if prd_path.exists():
        with open(prd_path, encoding="utf-8") as f:
            prd_data = json.load(f)
        stories = prd_data.get("userStories", [])
        remaining_stories = sum(1 for s in stories if not s.get("passes", False) and not s.get("_decomposed", False))

    rows = load_results(results_path)
    metrics = compute_velocity(rows, last_n_iterations=last_n)

    velocity = metrics["velocity"]
    cost_velocity = metrics["cost_velocity"]
    completed_iterations = int(metrics["completed_iterations"])

    if velocity <= 0:
        iterations_needed: float = -1.0 if remaining_stories > 0 else 0.0
        projected_cost = 0.0
    else:
        iterations_needed = remaining_stories / velocity
        projected_cost = iterations_needed * cost_velocity

    if completed_iterations >= last_n:
        confidence_pct = 100.0
    elif completed_iterations == 0:
        confidence_pct = 0.0
    else:
        confidence_pct = (completed_iterations / last_n) * 100.0

    return {
        "remaining_stories": remaining_stories,
        "iterations_needed": round(iterations_needed, 2),
        "projected_cost": round(projected_cost, 0),
        "confidence_pct": round(confidence_pct, 1),
    }


def main() -> None:
    """CLI entry point for direct use: python lib/cost_forecast.py."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Forecast remaining cost and timeline")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    parser.add_argument("--last-n", type=int, default=5, help="Number of recent iterations to use")
    args = parser.parse_args()

    result = forecast(
        prd_path=Path(args.prd),
        results_path=Path(args.results),
        last_n=args.last_n,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
