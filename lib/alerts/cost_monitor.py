#!/usr/bin/env python3
"""cost_monitor.py — Monitor costs and emit ceiling alerts.

Checks cumulative SPIRAL costs against SPIRAL_COST_CEILING and emits
warning alerts at 80% and critical alerts at 95%.
"""

import csv
import os
from pathlib import Path
from typing import Tuple


def read_current_cost() -> float:
    """Calculate current cumulative cost from results.tsv.

    Returns:
        Total cost in USD from all completed stories in results.tsv.
    """
    results_path = Path(".spiral/results.tsv")

    if not results_path.exists():
        return 0.0

    total_cost = 0.0

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return 0.0

            for row in reader:
                try:
                    # Try to read estimated_cost_usd column if available
                    cost_str = row.get("estimated_cost_usd", row.get("cost", "0"))
                    if cost_str and cost_str != "":
                        total_cost += float(cost_str)
                except (ValueError, TypeError):
                    # Skip rows with non-numeric costs
                    pass
    except Exception:
        # If parsing fails, return 0
        return 0.0

    return total_cost


def get_ceiling() -> float:
    """Get SPIRAL_COST_CEILING from environment.

    Returns:
        Ceiling in USD, or 0 if not set (no limit).
    """
    ceiling_str = os.environ.get("SPIRAL_COST_CEILING", "0")
    try:
        return float(ceiling_str)
    except ValueError:
        return 0.0


def check_cost_thresholds() -> Tuple[bool, str]:
    """Check if costs exceed warning or critical thresholds.

    Returns:
        Tuple of (should_emit_alert, severity) where severity is 'warning' or 'critical',
        or (False, '') if no alert should be emitted.
    """
    ceiling = get_ceiling()

    # No ceiling set = no alerts
    if ceiling <= 0:
        return False, ""

    current_cost = read_current_cost()

    # Calculate percentage used
    percent_used = (current_cost / ceiling * 100) if ceiling > 0 else 0

    # Critical at 95% or higher
    if percent_used >= 95:
        return True, "critical"

    # Warning at 80% or higher (but below 95%)
    if percent_used >= 80:
        return True, "warning"

    return False, ""
