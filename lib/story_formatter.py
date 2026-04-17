"""story_formatter.py — Format a single story for `spiral explain <story-id>`.

CLI: Called from lib/cli_subcommands.sh via:
  python story_formatter.py <prd_path> <story_id> [--format text|markdown|json] [--results <tsv>]
"""

from __future__ import annotations

import csv
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
                existing = latest.get(sid)
                if existing is None or row.get("timestamp", "") > existing.get("timestamp", ""):
                    latest[sid] = dict(row)
    except FileNotFoundError:
        pass
    return latest


def _load_story(prd_path: str, story_id: str) -> dict[str, Any] | None:
    """Find and return a single story from prd.json."""
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            return dict(story)
    return None


def _source_badge(source: str) -> str:
    badges = {
        "test-fix": "[test-fix]",
        "research": "[research]",
        "ai-example": "[ai-example]",
        "seed": "[seed]",
    }
    return badges.get(source, f"[{source}]") if source else "[unknown]"


def _credibility_label(domain: str) -> str:
    high = {"arxiv.org", "github.com", "stackoverflow.com", "docs.python.org"}
    low = {"reddit.com", "quora.com", "medium.com"}
    if any(h in domain for h in high):
        return "high"
    if any(lw in domain for lw in low):
        return "low"
    return "medium"


def _format_text(story: dict[str, Any], tsv: dict[str, str] | None) -> str:
    lines: list[str] = []
    sid = story.get("id", "")
    title = story.get("title", "")
    source = story.get("_source", "")
    lines.append(f"┌─ {sid} {'─' * max(0, 60 - len(sid))}")
    lines.append(f"│  Title  : {title}")
    lines.append(f"│  Source : {_source_badge(source)}")
    lines.append(f"│  Status : {'PASSED' if story.get('passes') else 'PENDING'}")
    lines.append("└" + "─" * 63)
    lines.append("")

    desc = story.get("description", "")
    if desc:
        lines.append("Description")
        lines.append(f"  {desc}")
        lines.append("")

    ac = story.get("acceptanceCriteria", [])
    if ac:
        lines.append("Acceptance Criteria")
        for i, criterion in enumerate(ac, 1):
            lines.append(f"  {i}. {criterion}")
        lines.append("")

    notes = story.get("technicalNotes", [])
    if notes:
        lines.append("Technical Notes")
        for note in notes:
            lines.append(f"  • {note}")
        lines.append("")

    files = story.get("filesTouch", [])
    if files:
        lines.append("Files to Touch")
        for f in files:
            lines.append(f"  • {f}")
        lines.append("")

    research = story.get("research_summary", "")
    research_urls = story.get("research_urls", [])
    if source == "research" and (research or research_urls):
        lines.append("Research Context")
        if research:
            lines.append(f"  {research}")
        for url in research_urls:
            domain = url.split("/")[2] if url.startswith("http") else url
            credibility = _credibility_label(domain)
            lines.append(f"  • [{credibility}] {url}")
        lines.append("")

    if tsv:
        model = tsv.get("model") or story.get("model") or ""
        tokens_r = int(tsv.get("cache_read_tokens", 0) or 0)
        tokens_c = int(tsv.get("cache_creation_tokens", 0) or 0)
        tokens = tokens_r + tokens_c
        lines.append("Run Metadata")
        if model:
            lines.append(f"  Model     : {model}")
        if tokens:
            lines.append(f"  Tokens    : {tokens:,}")
        lines.append("")

    return "\n".join(lines)


def _format_markdown(story: dict[str, Any], tsv: dict[str, str] | None) -> str:
    lines: list[str] = []
    sid = story.get("id", "")
    title = story.get("title", "")
    source = story.get("_source", "")
    lines.append(f"# {sid}: {title}")
    lines.append("")
    badges = [f"`{_source_badge(source)}`"]
    if story.get("passes"):
        badges.append("`PASSED`")
    else:
        badges.append("`PENDING`")
    lines.append(" ".join(badges))
    lines.append("")

    desc = story.get("description", "")
    if desc:
        lines.append("## Description")
        lines.append("")
        lines.append(desc)
        lines.append("")

    ac = story.get("acceptanceCriteria", [])
    if ac:
        lines.append("## Acceptance Criteria")
        lines.append("")
        for i, criterion in enumerate(ac, 1):
            lines.append(f"{i}. {criterion}")
        lines.append("")

    notes = story.get("technicalNotes", [])
    if notes:
        lines.append("## Technical Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    files = story.get("filesTouch", [])
    if files:
        lines.append("## Files to Touch")
        lines.append("")
        for f in files:
            lines.append(f"- `{f}`")
        lines.append("")

    research = story.get("research_summary", "")
    research_urls = story.get("research_urls", [])
    if source == "research" and (research or research_urls):
        lines.append("## Research Context")
        lines.append("")
        if research:
            lines.append(research)
            lines.append("")
        for url in research_urls:
            domain = url.split("/")[2] if url.startswith("http") else url
            credibility = _credibility_label(domain)
            lines.append(f"- [{domain}]({url}) — credibility: **{credibility}**")
        lines.append("")

    if tsv:
        model = tsv.get("model") or story.get("model") or ""
        tokens_r = int(tsv.get("cache_read_tokens", 0) or 0)
        tokens_c = int(tsv.get("cache_creation_tokens", 0) or 0)
        tokens = tokens_r + tokens_c
        lines.append("## Run Metadata")
        lines.append("")
        if model:
            lines.append(f"- **Model**: {model}")
        if tokens:
            lines.append(f"- **Tokens**: {tokens:,}")
        lines.append("")

    return "\n".join(lines)


def _format_json(story: dict[str, Any], tsv: dict[str, str] | None) -> str:
    merged: dict[str, Any] = dict(story)
    if tsv:
        merged["_results"] = tsv
    return json.dumps(merged, indent=2)


def format_story_explain(
    story: dict[str, Any],
    results_row: dict[str, str] | None = None,
    fmt: str = "text",
) -> str:
    if fmt == "markdown":
        return _format_markdown(story, results_row)
    if fmt == "json":
        return _format_json(story, results_row)
    return _format_text(story, results_row)


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print(
            "Usage: story_formatter.py <prd_path> <story_id> [--format text|markdown|json] [--results <tsv>]",
            file=sys.stderr,
        )
        sys.exit(1)

    prd_path = args[0]
    story_id = args[1]
    fmt = "text"
    results_tsv = ""

    i = 2
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--results" and i + 1 < len(args):
            results_tsv = args[i + 1]
            i += 2
        else:
            i += 1

    story = _load_story(prd_path, story_id)
    if story is None:
        print(f"[spiral] ERROR: Story '{story_id}' not found in {prd_path}", file=sys.stderr)
        sys.exit(1)

    tsv: dict[str, str] | None = None
    if results_tsv:
        rows = _load_results(results_tsv)
        tsv = rows.get(story_id)

    print(format_story_explain(story, tsv, fmt))


if __name__ == "__main__":
    main()
