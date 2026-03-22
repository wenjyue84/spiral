"""lib/cli/federated_cost_report.py — Federated cost breakdown by sub-project and phase (US-713).

Reads results.tsv and groups costs by (sub_project, phase), summing tokens_used and cost_usd.
Outputs markdown table showing cost distribution across sub-projects and phases.
Handles missing sub_project column gracefully (treats as "default").
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

# Cost per million tokens for each model (from federated_status.py pattern)
COST_PER_MTOK = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}


def _calculate_cost(tokens: int, model: str) -> float:
    """Calculate USD cost from token count and model.

    Args:
        tokens: Total tokens (input + output combined).
        model: Model name (haiku, sonnet, opus).

    Returns:
        Estimated cost in USD (assumes 50/50 input/output split).
    """
    model = (model or "sonnet").lower()
    if model not in COST_PER_MTOK:
        model = "sonnet"

    rates = COST_PER_MTOK[model]
    avg_rate = (rates["input"] + rates["output"]) / 2.0
    cost_usd = (tokens / 1_000_000) * avg_rate
    return cost_usd


def read_results_tsv(path: Path | str) -> list[dict[str, Any]]:
    """Read results.tsv and return rows as list of dicts.

    Args:
        path: Path to results.tsv file.

    Returns:
        List of row dicts from CSV.

    Raises:
        FileNotFoundError: If results.tsv not found.
        Exception: On CSV parse errors.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"results.tsv not found: {path}")

    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames:
                rows = list(reader)
    except Exception as exc:
        raise Exception(f"Failed to read {path}: {exc}") from exc

    return rows


def aggregate_by_group(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    """Group rows by (sub_project, phase) and sum tokens/cost.

    Args:
        rows: List of result rows from results.tsv.

    Returns:
        Dict mapping (sub_project, phase) tuple to {tokens_used, cost_usd, story_count}.
        Missing sub_project defaults to "default".
        Missing phase defaults to "unknown".
    """
    groups: dict[tuple[str, str], dict[str, float]] = {}

    for row in rows:
        sub_project = row.get("sub_project", "").strip() or "default"
        phase = row.get("phase", "").strip() or "unknown"

        # Calculate tokens from cache columns (handle each separately for robustness)
        tokens = 0
        try:
            tokens += int(row.get("cache_read_tokens", 0) or 0)
        except (ValueError, TypeError):
            pass
        try:
            tokens += int(row.get("cache_creation_tokens", 0) or 0)
        except (ValueError, TypeError):
            pass

        # Calculate cost
        model = row.get("model", "sonnet")
        cost = _calculate_cost(tokens, model)

        # Aggregate
        key = (sub_project, phase)
        if key not in groups:
            groups[key] = {"tokens_used": 0, "cost_usd": 0.0, "story_count": 0}

        groups[key]["tokens_used"] += tokens
        groups[key]["cost_usd"] += cost
        groups[key]["story_count"] += 1

    return groups


def format_markdown_table(
    groups: dict[tuple[str, str], dict[str, float]],
) -> str:
    """Format aggregated groups as markdown table.

    Args:
        groups: Output from aggregate_by_group().

    Returns:
        Markdown-formatted table string, sorted by total_cost descending.
    """
    if not groups:
        return "No data to report.\n"

    # Compute totals per sub_project across all phases
    project_totals: dict[str, dict[str, float]] = {}

    for (sub_project, phase), metrics in groups.items():
        if sub_project not in project_totals:
            project_totals[sub_project] = {}
        project_totals[sub_project][phase] = metrics["cost_usd"]

    # Build rows sorted by total cost descending
    rows = []
    for sub_project in sorted(project_totals.keys()):
        phases = project_totals[sub_project]
        phase_r_cost = phases.get("R", 0.0)
        phase_i_cost = phases.get("I", 0.0)
        total_cost = sum(phases.values())

        rows.append((sub_project, phase_r_cost, phase_i_cost, total_cost))

    rows.sort(key=lambda x: x[3], reverse=True)  # Sort by total_cost desc

    # Format table
    lines = []
    lines.append("| Sub-Project | Phase R Cost | Phase I Cost | Total Cost |")
    lines.append("|---|---|---|---|")

    for sub_project, phase_r, phase_i, total in rows:
        lines.append(f"| {sub_project} | ${phase_r:.4f} | ${phase_i:.4f} | ${total:.4f} |")

    # Add totals row
    total_r = sum(row[1] for row in rows)
    total_i = sum(row[2] for row in rows)
    total_all = sum(row[3] for row in rows)
    lines.append("|---|---|---|---|")
    lines.append(f"| **TOTAL** | **${total_r:.4f}** | **${total_i:.4f}** | **${total_all:.4f}** |")

    return "\n".join(lines) + "\n"


def federated_cost_report(results_path: Path | str) -> str:
    """Generate federated cost report from results.tsv.

    Args:
        results_path: Path to results.tsv file.

    Returns:
        Formatted markdown table string.

    Raises:
        FileNotFoundError: If results.tsv not found.
    """
    rows = read_results_tsv(results_path)
    groups = aggregate_by_group(rows)
    return format_markdown_table(groups)
