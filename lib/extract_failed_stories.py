"""extract_failed_stories.py — Generate triage report from results.tsv.

Identifies stories with high retry counts, extracts failure patterns,
and generates recommendations (decompose / scope / research).

Story: US-613
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _load_results_tsv(path: Path) -> list[dict[str, str]]:
    """Load results.tsv into a list of row dicts."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _safe_int(val: str | None, default: int = 0) -> int:
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def _safe_float(val: str | None, default: float = 0.0) -> float:
    try:
        return float(val or default)
    except (ValueError, TypeError):
        return default


def _token_burn(row: dict[str, str]) -> int:
    """Total tokens consumed in a single attempt."""
    return (
        _safe_int(row.get("cache_read_tokens"))
        + _safe_int(row.get("cache_creation_tokens"))
        + _safe_int(row.get("review_tokens"))
    )


def _has_exponential_token_growth(attempts: list[dict[str, str]]) -> bool:
    """Check if token burn roughly doubles across attempts (exponential)."""
    burns = [_token_burn(a) for a in attempts]
    burns = [b for b in burns if b > 0]
    if len(burns) < 2:
        return False
    # Check if later attempts are significantly larger than earlier ones
    ratios = [burns[i + 1] / burns[i] for i in range(len(burns) - 1) if burns[i] > 0]
    if not ratios:
        return False
    avg_ratio = sum(ratios) / len(ratios)
    return avg_ratio > 1.3


def _has_increasing_token_drift(attempts: list[dict[str, str]]) -> bool:
    """Check if token usage is steadily increasing (scope drift)."""
    burns = [_token_burn(a) for a in attempts]
    burns = [b for b in burns if b > 0]
    if len(burns) < 2:
        return False
    # Monotonically increasing (allowing small dips)
    increases = sum(1 for i in range(len(burns) - 1) if burns[i + 1] > burns[i])
    return increases >= len(burns) - 1


def _suggest(
    story_id: str,
    attempts: list[dict[str, str]],
    retry_count: int,
    source: str,
) -> str:
    """Generate per-story suggestion based on patterns."""
    if retry_count > 3 and _has_exponential_token_growth(attempts):
        return "decompose"
    if _has_increasing_token_drift(attempts):
        return "scope"
    if source == "test-fix" and retry_count >= 2:
        return "research"
    if retry_count > 3:
        return "decompose"
    return "investigate"


def extract_failed_stories(
    results_path: str | Path = "results.tsv",
    min_retries: int = 1,
) -> dict[str, Any]:
    """Extract failed stories from results.tsv and generate triage report.

    Returns a dict with:
      - stories: list of per-story triage entries sorted by retry count desc
      - summary: counts and totals
    """
    path = Path(results_path)
    rows = _load_results_tsv(path)

    # Group attempts by story_id
    by_story: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        sid = row.get("story_id", "").strip()
        if not sid:
            continue
        by_story.setdefault(sid, []).append(row)

    triage_entries: list[dict[str, Any]] = []

    for story_id, attempts in by_story.items():
        # Sort attempts by retry_num
        attempts.sort(key=lambda r: _safe_int(r.get("retry_num")))

        # Count rejections (failed attempts)
        rejects = [a for a in attempts if a.get("status") == "reject"]
        retry_count = len(rejects)

        if retry_count < min_retries:
            continue

        # Model escalation pattern
        models_used = [a.get("model", "unknown") for a in attempts]
        model_escalation = " -> ".join(dict.fromkeys(models_used))  # ordered unique

        # Token burn per attempt
        token_burns = [
            {
                "retry": _safe_int(a.get("retry_num")),
                "tokens": _token_burn(a),
                "model": a.get("model", "unknown"),
                "status": a.get("status", "unknown"),
                "duration_sec": _safe_int(a.get("duration_sec")),
            }
            for a in attempts
        ]

        # Total token burn
        total_tokens = sum(tb["tokens"] for tb in token_burns)

        # Determine source from story_id prefix or first attempt
        source = ""
        if story_id.startswith("UT-"):
            source = "test-fix"

        # Latest failure reason (from failure_root_cause column if present)
        failure_reasons = [
            a.get("failure_root_cause", "").strip()
            for a in rejects
            if a.get("failure_root_cause", "").strip()
        ]

        suggestion = _suggest(story_id, attempts, retry_count, source)

        title = attempts[0].get("story_title", "") if attempts else ""

        triage_entries.append(
            {
                "story_id": story_id,
                "title": title,
                "retry_count": retry_count,
                "model_escalation": model_escalation,
                "token_burns": token_burns,
                "total_tokens": total_tokens,
                "failure_reasons": failure_reasons,
                "suggestion": suggestion,
            }
        )

    # Sort by retry count descending
    triage_entries.sort(key=lambda e: e["retry_count"], reverse=True)

    return {
        "stories": triage_entries,
        "summary": {
            "total_stories_analyzed": len(by_story),
            "stories_with_failures": len(triage_entries),
            "total_token_burn": sum(e["total_tokens"] for e in triage_entries),
        },
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format the triage report as markdown."""
    lines: list[str] = []
    lines.append("# Failed Stories Triage Report")
    lines.append("")

    summary = report["summary"]
    lines.append(f"**Stories analyzed:** {summary['total_stories_analyzed']}")
    lines.append(f"**Stories with failures:** {summary['stories_with_failures']}")
    lines.append(f"**Total token burn:** {summary['total_token_burn']:,}")
    lines.append("")

    if not report["stories"]:
        lines.append("No failed stories found.")
        return "\n".join(lines)

    lines.append("## Stories by Retry Count")
    lines.append("")

    for entry in report["stories"]:
        lines.append(f"### {entry['story_id']}: {entry['title']}")
        lines.append(f"- **Retries:** {entry['retry_count']}")
        lines.append(f"- **Model escalation:** {entry['model_escalation']}")
        lines.append(f"- **Total tokens:** {entry['total_tokens']:,}")
        lines.append(f"- **Suggestion:** `{entry['suggestion']}`")

        if entry["failure_reasons"]:
            lines.append(f"- **Failure reasons:** {', '.join(entry['failure_reasons'])}")

        lines.append("")
        lines.append("| Retry | Model | Status | Tokens | Duration (s) |")
        lines.append("|-------|-------|--------|--------|--------------|")
        for tb in entry["token_burns"]:
            lines.append(
                f"| {tb['retry']} | {tb['model']} | {tb['status']} "
                f"| {tb['tokens']:,} | {tb['duration_sec']} |"
            )
        lines.append("")

    return "\n".join(lines)
