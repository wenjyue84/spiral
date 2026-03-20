"""aggregator.py — Unified cross-project metrics aggregation.

Computes dashboard overview metrics across multiple sub-projects by reading
their individual results.tsv files. Supports filtering by sub_project column
when a single aggregated TSV is used instead of per-project files.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

# Token-cost estimates (USD per 1M tokens) by model tier for rough cost estimation
_COST_PER_M: dict[str, float] = {
    "haiku": 0.25,
    "sonnet": 3.0,
    "opus": 15.0,
}


def _estimate_cost(row: dict[str, str]) -> float:
    """Estimate USD cost for a row from token counts and model tier."""
    model = (row.get("model") or "sonnet").lower()
    rate = _COST_PER_M.get(model, 3.0)
    try:
        input_tok = float(row.get("cache_read_tokens") or 0) + float(row.get("cache_creation_tokens") or 0)
        output_tok = float(row.get("review_tokens") or 0)
        return (input_tok + output_tok) / 1_000_000 * rate
    except (ValueError, TypeError):
        return 0.0


def _escalation_pct(rows: list[dict[str, str]]) -> float:
    """Return fraction of rows that are model escalations (retry_num >= 1)."""
    if not rows:
        return 0.0
    escalated = sum(1 for r in rows if int(r.get("retry_num") or 0) >= 1)
    return escalated / len(rows)


def _read_tsv(path: Path, sub_project: str | None = None) -> list[dict[str, str]]:
    """Read a results.tsv file, optionally filtering by sub_project column."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        if sub_project and rows and "sub_project" in (rows[0] if rows else {}):
            rows = [r for r in rows if r.get("sub_project") == sub_project]
        return rows
    except Exception:
        return []


def _project_key(path: Path) -> str:
    """Return a human-readable sub-project key from a path."""
    # Use parent directory name as project identifier
    return path.parent.name or str(path)


def aggregate_overview(
    results_paths: list[Path],
) -> dict[str, Any]:
    """Compute unified cross-project metrics from multiple results.tsv files.

    Each path is treated as one independent sub-project. Rows are collected
    per sub-project for per-project stats (slowestSubProject).

    Returns:
        {
            "totalCost": float,           # sum of estimated costs (USD)
            "storiesPassed": int,         # count of keep rows across all projects
            "avgPhaseTime": float,        # mean duration_sec across all rows (seconds)
            "blockerCount": int,          # non-keep rows across all projects
            "slowestSubProject": str,     # project key with highest avg duration_sec
            "escalationPct": float,       # fraction of rows with retry_num >= 1
            "subProjectCount": int,       # number of sub-projects included
        }
    """
    total_cost = 0.0
    stories_passed = 0
    blocker_count = 0
    all_durations: list[float] = []

    # Per sub-project average durations to find slowest
    project_durations: dict[str, list[float]] = {}

    for path in results_paths:
        rows = _read_tsv(path)
        key = _project_key(path)
        project_durations[key] = []

        for row in rows:
            status = (row.get("status") or "").lower()
            total_cost += _estimate_cost(row)

            try:
                dur = float(row.get("duration_sec") or 0)
            except (ValueError, TypeError):
                dur = 0.0

            all_durations.append(dur)
            project_durations[key].append(dur)

            if status == "keep":
                stories_passed += 1
            else:
                blocker_count += 1

    avg_phase_time = sum(all_durations) / len(all_durations) if all_durations else 0.0

    # Slowest sub-project = highest mean duration
    slowest = ""
    slowest_avg = -1.0
    for key, durs in project_durations.items():
        if durs:
            avg = sum(durs) / len(durs)
            if avg > slowest_avg:
                slowest_avg = avg
                slowest = key

    # Escalation % across all projects
    all_rows: list[dict[str, str]] = []
    for path in results_paths:
        all_rows.extend(_read_tsv(path))

    return {
        "totalCost": round(total_cost, 6),
        "storiesPassed": stories_passed,
        "avgPhaseTime": round(avg_phase_time, 3),
        "blockerCount": blocker_count,
        "slowestSubProject": slowest,
        "escalationPct": round(_escalation_pct(all_rows), 4),
        "subProjectCount": len(results_paths),
    }
