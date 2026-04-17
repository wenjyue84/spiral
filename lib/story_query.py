"""story_query.py — Query prd.json + results.tsv for filtered/sorted story reporting.

CLI: spiral query stories [--status pass|fail|pending] [--complexity small|medium|large]
     [--by-project] [--format table|json|csv]

Called from lib/cli_subcommands.sh via: python story_query.py <prd> <tsv> [flags...]
"""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any


def _load_results(tsv_path: str) -> dict[str, dict[str, str]]:
    """Return latest row per story_id from results.tsv."""
    latest: dict[str, dict[str, str]] = {}
    try:
        with open(tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                sid = row.get("story_id", "")
                if not sid:
                    continue
                # Keep the latest timestamp row per story
                existing = latest.get(sid)
                if existing is None or row.get("timestamp", "") > existing.get("timestamp", ""):
                    latest[sid] = dict(row)
    except FileNotFoundError:
        pass
    return latest


def _status_of(story: dict[str, Any], tsv_row: dict[str, str] | None) -> str:
    """Derive status: pass / fail / pending."""
    if story.get("passes") is True:
        return "pass"
    if tsv_row and tsv_row.get("status") in ("reject", "fail", "error"):
        return "fail"
    return "pending"


def query_stories(
    prd_path: str,
    results_tsv_path: str,
    filters: dict[str, str],
) -> list[dict[str, Any]]:
    """Load prd.json + results.tsv, merge, filter, and return matching stories.

    filters keys: status, complexity, project (prefix match on story id)
    """
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    tsv_rows = _load_results(results_tsv_path)
    stories: list[dict[str, Any]] = []

    for story in prd.get("userStories", []):
        sid: str = story.get("id", "")
        tsv = tsv_rows.get(sid)
        status = _status_of(story, tsv)
        complexity: str = story.get("estimatedComplexity", "small")
        tokens = int(tsv.get("cache_read_tokens", 0) or 0) + int(
            tsv.get("cache_creation_tokens", 0) or 0
        ) if tsv else 0
        model = tsv.get("model") or story.get("model") or ""
        last_failure = (
            tsv.get("status", "") if tsv and tsv.get("status") in ("reject", "fail", "error") else ""
        )

        # Derive project prefix (e.g. "US", "UT", or custom namespace)
        project = sid.split("-")[0] if "-" in sid else "UNKNOWN"

        record: dict[str, Any] = {
            "ID": sid,
            "Title": story.get("title", ""),
            "Status": status,
            "Project": project,
            "Complexity": complexity,
            "Tokens": tokens,
            "Cost": "",
            "Model": model,
            "Last_Failure_Reason": last_failure,
        }
        stories.append(record)

    # Apply filters
    status_filter = filters.get("status", "").lower()
    complexity_filter = filters.get("complexity", "").lower()
    project_filter = filters.get("project", "").lower()

    if status_filter:
        stories = [s for s in stories if s["Status"] == status_filter]
    if complexity_filter:
        stories = [s for s in stories if s["Complexity"].lower() == complexity_filter]
    if project_filter:
        stories = [s for s in stories if s["Project"].lower() == project_filter]

    return stories


def format_table(stories: list[dict[str, Any]]) -> str:
    """Render stories as ASCII table."""
    if not stories:
        return "(no stories match the given filters)"

    cols = ["ID", "Title", "Status", "Project", "Complexity", "Tokens", "Model"]
    widths = {c: len(c) for c in cols}
    for s in stories:
        for c in cols:
            widths[c] = max(widths[c], len(str(s.get(c, ""))))

    sep = "+" + "+".join("-" * (widths[c] + 2) for c in cols) + "+"
    header = "|" + "|".join(f" {c:<{widths[c]}} " for c in cols) + "|"
    lines = [sep, header, sep]
    for s in stories:
        row = "|" + "|".join(f" {str(s.get(c, '')):<{widths[c]}} " for c in cols) + "|"
        lines.append(row)
    lines.append(sep)
    return "\n".join(lines)


def format_json(stories: list[dict[str, Any]]) -> str:
    """Render stories as JSON array."""
    return json.dumps(stories, indent=2, ensure_ascii=False)


def format_csv(stories: list[dict[str, Any]]) -> str:
    """Render stories as CSV."""
    cols = ["ID", "Title", "Status", "Project", "Complexity", "Tokens", "Cost", "Model", "Last_Failure_Reason"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(stories)
    return buf.getvalue()


def group_by_project(stories: list[dict[str, Any]]) -> str:
    """Group stories by project prefix, showing count and pass rate."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in stories:
        proj = s["Project"]
        groups.setdefault(proj, []).append(s)

    lines = []
    for proj, group in sorted(groups.items()):
        total = len(group)
        passed = sum(1 for s in group if s["Status"] == "pass")
        rate = f"{passed / total * 100:.0f}%" if total else "0%"
        lines.append(f"  {proj:<12} {total:>5} stories  {passed:>4} passed  {rate:>5} pass rate")

    if not lines:
        return "(no stories found)"
    header = f"  {'Project':<12} {'Total':>5} stories  {'Pass':>4} passed  {'Rate':>5}"
    sep = "  " + "-" * 42
    return "\n".join([header, sep] + lines)


def main(argv: list[str]) -> None:
    """Entry point when called from cli_subcommands.sh."""
    if len(argv) < 3:
        print("Usage: story_query.py <prd.json> <results.tsv> [--status S] [--complexity C] [--project P] [--by-project] [--format table|json|csv]", file=sys.stderr)
        sys.exit(1)

    prd_path = argv[1]
    tsv_path = argv[2]
    args = argv[3:]

    filters: dict[str, str] = {}
    fmt = "table"
    by_project = False

    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            filters["status"] = args[i + 1]
            i += 2
        elif args[i] == "--complexity" and i + 1 < len(args):
            filters["complexity"] = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            filters["project"] = args[i + 1]
            i += 2
        elif args[i] == "--by-project":
            by_project = True
            i += 1
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        else:
            i += 1

    stories = query_stories(prd_path, tsv_path, filters)

    if by_project:
        print(group_by_project(stories))
        return

    if fmt == "json":
        print(format_json(stories))
    elif fmt == "csv":
        print(format_csv(stories), end="")
    else:
        print(format_table(stories))


if __name__ == "__main__":
    main(sys.argv)
