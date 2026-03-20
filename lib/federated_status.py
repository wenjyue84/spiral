"""federated_status.py — Aggregate story status across federated sub-projects.

Reads prd.json with sub_project field on stories, loads corresponding results.tsv
files, and aggregates story counts, tokens, and cost per sub-project.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


COST_PER_MTOK = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}


def aggregate_federated_status(
    prd_path: Path,
    results_globs: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate story status across federated sub-projects.

    Args:
        prd_path: Path to prd.json with sub_project field on stories.
        results_globs: Optional list of glob patterns to find results.tsv files.
                      Default: [".spiral-workers/worker-*/results.tsv", "results.tsv"]

    Returns:
        Dict with 'status' key (status per sub_project) and 'summary' key (totals).
    """
    if not prd_path.exists():
        return {
            "status": [],
            "summary": {
                "total_projects": 0,
                "total_stories": 0,
                "total_passed": 0,
                "total_failed": 0,
                "total_pending": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
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

    # Load results.tsv files to aggregate metrics
    if results_globs is None:
        results_globs = [".spiral-workers/worker-*/results.tsv", "results.tsv"]

    results_data = _load_all_results(prd_path.parent, results_globs)

    # Map story_id -> (status, tokens, duration) from results
    story_metrics: dict[str, dict[str, Any]] = {}
    for row in results_data:
        sid = row.get("story_id", "")
        if not sid:
            continue
        status = row.get("status", "pending")
        if status not in ["pass", "reject"]:
            status = "pending"

        tokens = 0
        try:
            tokens = int(row.get("cache_read_tokens", 0) or 0) + int(
                row.get("cache_creation_tokens", 0) or 0
            )
        except (ValueError, TypeError):
            pass

        duration = 0.0
        try:
            duration = float(row.get("duration_sec", 0) or 0)
        except (ValueError, TypeError):
            pass

        model = row.get("model", "sonnet")

        story_metrics[sid] = {
            "status": status,
            "tokens": tokens,
            "duration": duration,
            "model": model,
        }

    # Aggregate per sub_project
    status_rows: list[dict[str, Any]] = []
    total_stories = 0
    total_passed = 0
    total_failed = 0
    total_pending = 0
    total_tokens = 0
    total_cost = 0.0

    for sub_proj in sorted(sub_projects.keys()):
        proj_stories = sub_projects[sub_proj]
        passed = 0
        failed = 0
        pending = 0
        proj_tokens = 0
        proj_cost = 0.0
        proj_duration = 0.0
        duration_count = 0

        for story in proj_stories:
            sid = story.get("id", "")
            if sid in story_metrics:
                metric = story_metrics[sid]
                status = metric["status"]
                if status == "pass":
                    passed += 1
                elif status == "reject":
                    failed += 1
                else:
                    pending += 1

                tokens = metric["tokens"]
                model = metric["model"]
                proj_tokens += tokens
                proj_cost += _calc_cost(tokens, model)
                proj_duration += metric["duration"]
                duration_count += 1
            else:
                # No results yet = pending
                pending += 1

        avg_duration = (
            proj_duration / duration_count if duration_count > 0 else 0.0
        )
        total_stories += len(proj_stories)
        total_passed += passed
        total_failed += failed
        total_pending += pending
        total_tokens += proj_tokens
        total_cost += proj_cost

        status_rows.append(
            {
                "sub_project": sub_proj,
                "total_stories": len(proj_stories),
                "passed": passed,
                "failed": failed,
                "pending": pending,
                "tokens_used": proj_tokens,
                "estimated_cost_usd": round(proj_cost, 4),
                "avg_duration_sec": round(avg_duration, 1),
            }
        )

    return {
        "status": status_rows,
        "summary": {
            "total_projects": len(sub_projects),
            "total_stories": total_stories,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_pending": total_pending,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
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


def format_table(data: dict[str, Any]) -> str:
    """Format aggregated status as a human-readable table.

    Args:
        data: Output from aggregate_federated_status().

    Returns:
        Formatted table string.
    """
    lines = []
    lines.append(
        "Sub-Project | Total Stories | Passed | Failed | Pending | Tokens Used | Estimated Cost | Avg Duration (s)"
    )
    lines.append("-" * 120)

    for row in data.get("status", []):
        line = (
            f"{row['sub_project']:<20} | "
            f"{row['total_stories']:<13} | "
            f"{row['passed']:<6} | "
            f"{row['failed']:<6} | "
            f"{row['pending']:<7} | "
            f"{row['tokens_used']:<11} | "
            f"${row['estimated_cost_usd']:<14.4f} | "
            f"{row['avg_duration_sec']:<18.1f}"
        )
        lines.append(line)

    summary = data.get("summary", {})
    lines.append("-" * 120)
    line = (
        f"{'TOTAL':<20} | "
        f"{summary.get('total_stories', 0):<13} | "
        f"{summary.get('total_passed', 0):<6} | "
        f"{summary.get('total_failed', 0):<6} | "
        f"{summary.get('total_pending', 0):<7} | "
        f"{summary.get('total_tokens', 0):<11} | "
        f"${summary.get('total_cost_usd', 0):<14.4f} | "
        f"{0:<18.1f}"
    )
    lines.append(line)

    return "\n".join(lines)
