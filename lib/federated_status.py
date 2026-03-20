"""lib/federated_status.py — Federated multi-project status aggregation (US-629).

Aggregates story status, token usage, and costs across sub-project results.tsv files
in a federated PRD structure. Reads .spiral/prd.json sub_project entries, loads
corresponding .spiral-workers/worker-*/results.tsv files, and outputs unified health
dashboard in JSON or table format.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

# Cost per million tokens for each model
COST_PER_MTOK = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}


def calculate_project_metrics(
    project_name: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate metrics for a single project.

    Args:
        project_name: Name of the project.
        results: List of result rows from results.tsv.

    Returns:
        Dict with project metrics (passed, failed, pending, tokens, cost, etc).
    """
    passed = 0
    failed = 0
    pending = 0
    total_tokens = 0
    total_cost = 0.0
    total_duration = 0.0
    duration_count = 0
    total_stories = len(results)

    for row in results:
        status = row.get("status", "pending")
        if status == "pass":
            passed += 1
        elif status == "reject":
            failed += 1
        else:
            pending += 1

        tokens = 0
        try:
            tokens = int(row.get("cache_read_tokens", 0) or 0) + int(
                row.get("cache_creation_tokens", 0) or 0
            )
        except (ValueError, TypeError):
            pass

        model = row.get("model", "sonnet")
        total_tokens += tokens
        total_cost += _calc_cost(tokens, model)

        duration = 0.0
        try:
            duration = float(row.get("duration_sec", 0) or 0)
        except (ValueError, TypeError):
            pass
        total_duration += duration
        duration_count += 1

    avg_duration = total_duration / duration_count if duration_count > 0 else 0.0

    return {
        "project": project_name,
        "total_stories": total_stories,
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "tokens_used": total_tokens,
        "cost_usd": total_cost,
        "avg_duration_s": avg_duration,
    }


def aggregate_federated_stories(
    prd_path: Path,
    results_globs: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate story status across federated sub-projects.

    Args:
        prd_path: Path to prd.json with sub_project field on stories.
        results_globs: Optional list of glob patterns to find results.tsv files.
                      Default: [".spiral-workers/worker-*/results.tsv", "results.tsv"]

    Returns:
        Dict with 'projects' key (list of per-project metrics) and 'summary' key (totals).
    """
    if not prd_path.exists():
        return {
            "projects": [],
            "summary": {
                "total_projects": 0,
                "total_stories": 0,
                "passed": 0,
                "failed": 0,
                "pending": 0,
                "tokens_used": 0,
                "cost_usd": 0.0,
                "avg_duration_s": 0.0,
            },
        }

    with open(prd_path, encoding="utf-8") as f:
        prd_data = json.load(f)

    stories = prd_data.get("userStories", [])

    # Group stories by sub_project
    sub_projects: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        if not isinstance(story, dict):
            continue
        sub_proj = story.get("sub_project", "default")
        if sub_proj not in sub_projects:
            sub_projects[sub_proj] = []
        sub_projects[sub_proj].append(story)

    # Load results.tsv files
    if results_globs is None:
        results_globs = [".spiral-workers/worker-*/results.tsv", "results.tsv"]

    results_data = _load_all_results(prd_path.parent, results_globs)

    # Map story_id -> results row(s)
    story_results: dict[str, dict[str, Any]] = {}
    for row in results_data:
        sid = row.get("story_id", "")
        if sid and sid not in story_results:
            story_results[sid] = row

    # Calculate metrics per sub-project
    projects_metrics: list[dict[str, Any]] = []
    total_passed = 0
    total_failed = 0
    total_pending = 0
    total_tokens = 0
    total_cost = 0.0
    total_duration = 0.0
    total_count = 0

    for sub_proj in sorted(sub_projects.keys()):
        proj_stories = sub_projects[sub_proj]
        proj_results: list[dict[str, Any]] = []

        for story in proj_stories:
            sid = story.get("id", "")
            if sid in story_results:
                proj_results.append(story_results[sid])
            else:
                # Story with no results yet
                proj_results.append({"status": "pending"})

        metrics = calculate_project_metrics(sub_proj, proj_results)
        projects_metrics.append(metrics)

        total_passed += metrics["passed"]
        total_failed += metrics["failed"]
        total_pending += metrics["pending"]
        total_tokens += metrics["tokens_used"]
        total_cost += metrics["cost_usd"]
        total_duration += metrics["avg_duration_s"]
        total_count += 1

    avg_duration = total_duration / total_count if total_count > 0 else 0.0

    return {
        "projects": projects_metrics,
        "summary": {
            "total_projects": len(sub_projects),
            "total_stories": sum(m["total_stories"] for m in projects_metrics),
            "passed": total_passed,
            "failed": total_failed,
            "pending": total_pending,
            "tokens_used": total_tokens,
            "cost_usd": total_cost,
            "avg_duration_s": avg_duration,
        },
    }


def aggregate_federated_status(
    prd_path: Path,
    results_globs: list[str] | None = None,
) -> dict[str, Any]:
    """Backward compatibility wrapper for aggregate_federated_stories.

    Converts output to older 'status' and 'summary' format.
    """
    result = aggregate_federated_stories(prd_path, results_globs)

    # Convert 'projects' to 'status' format for backward compatibility
    status_rows: list[dict[str, Any]] = []
    for proj in result.get("projects", []):
        status_rows.append({
            "sub_project": proj["project"],
            "total_stories": proj["total_stories"],
            "passed": proj["passed"],
            "failed": proj["failed"],
            "pending": proj["pending"],
            "tokens_used": proj["tokens_used"],
            "estimated_cost_usd": round(proj["cost_usd"], 4),
            "avg_duration_sec": round(proj["avg_duration_s"], 1),
        })

    summary = result.get("summary", {})
    return {
        "status": status_rows,
        "summary": {
            "total_projects": summary.get("total_projects", 0),
            "total_stories": summary.get("total_stories", 0),
            "total_passed": summary.get("passed", 0),
            "total_failed": summary.get("failed", 0),
            "total_pending": summary.get("pending", 0),
            "total_tokens": summary.get("tokens_used", 0),
            "total_cost_usd": round(summary.get("cost_usd", 0.0), 4),
        },
    }


def _load_all_results(
    base_dir: Path, globs: list[str]
) -> list[dict[str, Any]]:
    """Load all results.tsv files matching the glob patterns.

    Args:
        base_dir: Base directory to search from.
        globs: List of glob patterns (e.g., "results.tsv", ".spiral-workers/*/results.tsv").

    Returns:
        List of rows from all matching TSV files.
    """
    all_rows: list[dict[str, Any]] = []
    seen_rows = set()

    for glob_pattern in globs:
        for tsv_file in base_dir.glob(glob_pattern):
            if not tsv_file.exists():
                continue
            try:
                with open(tsv_file, encoding="utf-8") as f:
                    reader = csv.DictReader(f, delimiter="\t")
                    for row in reader:
                        if not row:
                            continue
                        row_key = (row.get("story_id", ""), row.get("spiral_iter", ""))
                        if row_key not in seen_rows:
                            all_rows.append(row)
                            seen_rows.add(row_key)
            except (IOError, csv.Error):
                continue

    return all_rows


def _calc_cost(tokens: int, model: str = "sonnet") -> float:
    """Calculate estimated cost for tokens used.

    Args:
        tokens: Total tokens (combined input + output).
        model: Model name (haiku, sonnet, opus).

    Returns:
        Estimated cost in USD, assuming 50/50 split between input and output.
    """
    model = (model or "sonnet").lower()
    if model not in COST_PER_MTOK:
        model = "sonnet"

    rates = COST_PER_MTOK[model]
    avg_rate = (rates["input"] + rates["output"]) / 2.0
    cost_usd = (tokens / 1_000_000) * avg_rate
    return cost_usd


def format_json_output(data: dict[str, Any]) -> str:
    """Format aggregated data as JSON.

    Args:
        data: Output from aggregate_federated_stories() or similar.

    Returns:
        JSON string.
    """
    return json.dumps(data, indent=2)


def format_table_output(data: dict[str, Any]) -> str:
    """Format aggregated status as a human-readable table.

    Args:
        data: Output from aggregate_federated_stories() or similar.

    Returns:
        Formatted table string.
    """
    lines = []
    lines.append(
        "Sub-Project | Total Stories | Passed | Failed | Pending | Tokens Used | Estimated Cost | Avg Duration (s)"
    )
    lines.append("-" * 120)

    total_stories = 0
    total_passed = 0
    total_failed = 0
    total_pending = 0
    total_tokens = 0
    total_cost = 0.0

    for proj in data.get("projects", []):
        total_stories += proj["total_stories"]
        total_passed += proj["passed"]
        total_failed += proj["failed"]
        total_pending += proj["pending"]
        total_tokens += proj["tokens_used"]
        total_cost += proj["cost_usd"]

        line = (
            f"{proj['project']:<20} | "
            f"{proj['total_stories']:<13} | "
            f"{proj['passed']:<6} | "
            f"{proj['failed']:<6} | "
            f"{proj['pending']:<7} | "
            f"{proj['tokens_used']:<11} | "
            f"${proj['cost_usd']:<14.4f} | "
            f"{proj['avg_duration_s']:<18.1f}"
        )
        lines.append(line)

    lines.append("-" * 120)
    line = (
        f"{'TOTAL':<20} | "
        f"{total_stories:<13} | "
        f"{total_passed:<6} | "
        f"{total_failed:<6} | "
        f"{total_pending:<7} | "
        f"{total_tokens:<11} | "
        f"${total_cost:<14.4f} | "
        f"{0:<18.1f}"
    )
    lines.append(line)

    return "\n".join(lines)


# Backward compatibility alias
format_table = format_table_output
