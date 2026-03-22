"""lib/forecast_ceiling.py — Forecast SPIRAL_COST_CEILING breach timing from results.tsv (US-699)."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np


def load_results(path: Path) -> list[dict[str, str]]:
    """Load results.tsv into a list of row dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader) if reader.fieldnames else []


def compute_cost_per_iteration(rows: list[dict[str, str]]) -> dict[int, int]:
    """Sum all tokens per spiral_iter.

    Returns dict mapping iteration number to total tokens (cost proxy).
    """
    iter_tokens: dict[int, int] = {}
    for row in rows:
        try:
            iteration = int(row.get("spiral_iter", 0) or 0)
        except (ValueError, TypeError):
            continue

        if iteration not in iter_tokens:
            iter_tokens[iteration] = 0

        # Sum all token columns as cost proxy
        for col in ("cache_read_tokens", "cache_creation_tokens", "review_tokens"):
            try:
                tokens = int(row.get(col, 0) or 0)
                iter_tokens[iteration] += tokens
            except (ValueError, TypeError):
                pass

    return iter_tokens


def forecast_breach(
    cost_ceiling: float,
    iter_tokens: dict[int, int],
) -> dict[str, float | int | str]:
    """Forecast when cost_ceiling will be breached using linear regression.

    Args:
        cost_ceiling: USD ceiling to project breach for (assumed cost = tokens/1000)
        iter_tokens: dict mapping iteration to total tokens

    Returns dict with keys:
        breach_iteration: float — projected iteration when breach occurs (-1 if never)
        confidence: str — "high" if >=5 data points, "low" if <5
        data_points: int — number of iterations analyzed
        burn_rate: float — tokens per iteration (from regression)
    """
    if not iter_tokens:
        return {
            "breach_iteration": -1,
            "confidence": "low",
            "data_points": 0,
            "burn_rate": 0.0,
        }

    # Sort iterations and extract x, y for regression
    sorted_iters = sorted(iter_tokens.keys())
    x = np.array(sorted_iters, dtype=float)
    y = np.array([iter_tokens[i] for i in sorted_iters], dtype=float)

    data_points = len(sorted_iters)
    confidence = "high" if data_points >= 5 else "low"

    # Fit linear trend: y = a*x + b
    # polyfit(x, y, 1) returns [a, b] for degree-1 polynomial
    try:
        coeffs = np.polyfit(x, y, 1)
        slope = float(coeffs[0])  # tokens per iteration
        intercept = float(coeffs[1])
    except (np.linalg.LinAlgError, ValueError):
        return {
            "breach_iteration": -1,
            "confidence": "low",
            "data_points": data_points,
            "burn_rate": 0.0,
        }

    # Cost in USD = total_tokens / 1000 (approximate Claude pricing)
    # Ceiling in tokens = cost_ceiling * 1000
    ceiling_tokens = cost_ceiling * 1000

    # At iteration x, total cost = sum of all iterations up to x
    # With linear burn rate, cumulative cost ≈ integral of (slope*t + intercept) from 0 to x
    # Cumulative = slope * x^2/2 + intercept * x
    # Solve: slope * x^2/2 + intercept * x = ceiling_tokens
    # -> slope/2 * x^2 + intercept * x - ceiling_tokens = 0

    if slope <= 0:
        # Non-increasing burn rate, won't reach ceiling
        return {
            "breach_iteration": -1,
            "confidence": confidence,
            "data_points": data_points,
            "burn_rate": max(0.0, slope),
        }

    a = slope / 2
    b = intercept
    c = -ceiling_tokens

    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return {
            "breach_iteration": -1,
            "confidence": confidence,
            "data_points": data_points,
            "burn_rate": slope,
        }

    # Solve quadratic: x = (-b ± sqrt(discriminant)) / (2a)
    x_positive = (-b + np.sqrt(discriminant)) / (2 * a)
    x_negative = (-b - np.sqrt(discriminant)) / (2 * a)

    # Take the smallest positive root
    candidates = [x for x in [x_positive, x_negative] if x > 0]
    breach_iteration = float(min(candidates)) if candidates else -1

    return {
        "breach_iteration": round(breach_iteration, 1),
        "confidence": confidence,
        "data_points": data_points,
        "burn_rate": round(slope, 2),
    }


def to_calendar_date(
    breach_iteration: float,
    iter_tokens: dict[int, int],
) -> str | None:
    """Convert breach iteration to calendar date based on iteration cadence.

    Assumes one iteration per run; measures elapsed time from first to last iteration.
    """
    if breach_iteration <= 0 or not iter_tokens:
        return None

    sorted_iters = sorted(iter_tokens.keys())
    if len(sorted_iters) < 2:
        return None

    # Estimate: elapsed_days = (last_iter - first_iter) / (last_iter - first_iter) * total_days
    # Simplified: assume linear cadence
    first_iter = sorted_iters[0]
    last_iter = sorted_iters[-1]

    # We need timestamps to compute cadence; for now, assume ~1 iteration per day on average
    # This is a placeholder — real implementation would parse timestamps from results.tsv
    iters_span = last_iter - first_iter
    if iters_span == 0:
        return None

    # Assume current date is "today"; estimate days per iteration from data density
    # Placeholder: 1 iteration = 1 day (conservative estimate)
    days_per_iteration = 1.0
    days_to_breach = (breach_iteration - last_iter) * days_per_iteration

    if days_to_breach <= 0:
        return None

    target_date = datetime.now() + timedelta(days=days_to_breach)
    return target_date.strftime("%Y-%m-%d")


def format_forecast(
    result: dict[str, float | int | str],
    cost_ceiling: float,
    until_date: bool = False,
) -> str:
    """Format forecast result as human-readable text.

    Args:
        result: dict from forecast_breach()
        cost_ceiling: The ceiling value in USD
        until_date: Whether to include calendar date in output

    Returns formatted string ready for print()
    """
    breach_iter_raw = result.get("breach_iteration", -1)
    breach_iter = float(breach_iter_raw) if isinstance(breach_iter_raw, (float, int)) else -1.0
    confidence = str(result.get("confidence", "low"))
    data_points_raw = result.get("data_points", 0)
    data_points = int(data_points_raw) if isinstance(data_points_raw, (int, float)) else 0
    burn_rate_raw = result.get("burn_rate", 0.0)
    burn_rate = float(burn_rate_raw) if isinstance(burn_rate_raw, (float, int)) else 0.0

    # Default message if no breach detected
    if breach_iter <= 0:
        output = f"No breach detected for ceiling ${cost_ceiling:.2f} (based on {data_points} iterations)"
        if confidence == "low":
            output += f" [WARNING: only {data_points} data points — low confidence]"
        return output

    # Breach detected
    output = f"Breach projected in {breach_iter} iterations"
    output += f" (burn rate: {burn_rate:.0f} tokens/iteration)"

    if confidence == "low":
        output += f" [WARNING: only {data_points} data points — low confidence]"

    # Optional calendar date
    if until_date:
        output += f" — projected ceiling breach: ${cost_ceiling:.2f}"

    return output


def forecast_ceiling_cli(
    cost_ceiling: float,
    prd_path: Path | str = "prd.json",
    results_path: Path | str = "results.tsv",
    until_date: bool = False,
) -> dict[str, object]:
    """CLI entry point for forecast_ceiling command.

    Returns JSON-serializable dict with forecast result and formatted message.
    """
    prd_path_obj = Path(prd_path)
    results_path_obj = Path(results_path)

    rows = load_results(results_path_obj)
    iter_tokens = compute_cost_per_iteration(rows)
    result = forecast_breach(cost_ceiling, iter_tokens)

    # Add formatted message
    message = format_forecast(result, cost_ceiling, until_date=until_date)

    # Build output
    output: dict[str, object] = {
        "forecast": result,
        "cost_ceiling_usd": cost_ceiling,
        "message": message,
        "data_source": str(results_path_obj),
    }

    breach_iter_raw = result.get("breach_iteration", -1)
    breach_iter = float(breach_iter_raw) if isinstance(breach_iter_raw, (float, int)) else -1.0
    if until_date and breach_iter > 0:
        date_str = to_calendar_date(breach_iter, iter_tokens)
        if date_str:
            output["projected_breach_date"] = date_str

    return output
