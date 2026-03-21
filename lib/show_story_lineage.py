"""lib/show_story_lineage.py — Story decomposition lineage tree (US-671).

Recursively traverses story decomposition hierarchy to print ASCII tree showing
parent→children relationships with status emoji and token counts.

Usage (Python API):
    from show_story_lineage import build_lineage_tree, format_tree, to_json_output

    stories_by_id = {s["id"]: s for s in prd["userStories"]}
    results_by_story_id = {...}  # from results.tsv
    root = build_lineage_tree("US-528", stories_by_id, results_by_story_id)
    print(format_tree(root))
    print(json.dumps(to_json_output(root), indent=2))

CLI usage (via main.py):
    spiral show-story-lineage US-528
    spiral show-story-lineage US-528 --json
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LineageNode:
    """A node in the story decomposition tree."""

    story_id: str
    title: str
    passes: bool | None  # None if not run, True if passed, False if failed
    tokens: int  # Total tokens from results.tsv
    children: list[LineageNode] = field(default_factory=list)


def _load_token_counts(results_tsv: Path) -> dict[str, int]:
    """Load token counts from results.tsv.

    Returns mapping of story_id -> cache_read_tokens (summed across retries).
    Prioritizes cache_read_tokens, falls back to cache_creation_tokens if zero.
    """
    tokens: dict[str, int] = {}
    if not results_tsv.exists():
        return tokens

    try:
        with open(results_tsv, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                story_id: str = row.get("story_id", "")
                if not story_id:
                    continue
                try:
                    read_tokens = int(row.get("cache_read_tokens", 0) or 0)
                    creation_tokens = int(row.get("cache_creation_tokens", 0) or 0)
                    # Use read tokens if available, else creation tokens
                    total = read_tokens if read_tokens > 0 else creation_tokens
                    if story_id not in tokens:
                        tokens[story_id] = 0
                    tokens[story_id] += total
                except (ValueError, TypeError):
                    pass
    except (OSError, csv.Error):
        pass

    return tokens


def build_lineage_tree(
    story_id: str,
    stories_by_id: dict[str, dict[str, Any]],
    token_counts: dict[str, int] | None = None,
) -> LineageNode:
    """Recursively build decomposition lineage tree.

    Args:
        story_id: Root story ID.
        stories_by_id: Mapping of story_id -> story dict from prd.json.
        token_counts: Optional mapping of story_id -> total tokens from results.tsv.

    Returns:
        LineageNode with fully resolved children hierarchy.
    """
    if token_counts is None:
        token_counts = {}

    story = stories_by_id.get(story_id, {})
    title = story.get("title", "")
    passes = story.get("passes")  # None, True, or False
    tokens = token_counts.get(story_id, 0)

    node = LineageNode(
        story_id=story_id,
        title=title,
        passes=passes,
        tokens=tokens,
    )

    # Find all direct children (stories with _decomposedFrom == story_id)
    for potential_child in stories_by_id.values():
        if potential_child.get("_decomposedFrom") == story_id:
            child_id = potential_child.get("id", "")
            if child_id:
                child = build_lineage_tree(child_id, stories_by_id, token_counts)
                node.children.append(child)

    return node


def _status_emoji(passes: bool | None) -> str:
    """Return status emoji for story pass status.

    ✓ = passed, ✗ = failed, ⏳ = not run yet (None).
    """
    if passes is True:
        return "✓"
    elif passes is False:
        return "✗"
    else:
        return "⏳"


def format_tree(node: LineageNode, prefix: str = "", is_last: bool = True) -> str:
    """Render the lineage tree as a human-readable ASCII tree.

    Example output:
        ✓ US-528 (45000 tokens)
        ├── ✓ US-529 (30000 tokens)
        └── ✗ US-530 (15000 tokens)
    """
    connector = "└── " if is_last else "├── "
    emoji = _status_emoji(node.passes)
    title_tag = f" {node.title}" if node.title else ""
    tokens_tag = f" ({node.tokens} tokens)" if node.tokens > 0 else ""

    if prefix == "":
        # Root node (no prefix)
        line = f"{emoji} {node.story_id}{title_tag}{tokens_tag}\n"
    else:
        # Child node
        line = f"{prefix}{connector}{emoji} {node.story_id}{title_tag}{tokens_tag}\n"

    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(node.children):
        is_child_last = i == len(node.children) - 1
        line += format_tree(child, child_prefix, is_child_last)

    return line


def _collect_children(
    node: LineageNode,
) -> list[dict[str, Any]]:
    """Collect all child nodes into a flat list for JSON output."""
    result: list[dict[str, Any]] = []
    for child in node.children:
        entry: dict[str, Any] = {
            "id": child.story_id,
            "title": child.title,
            "status": "passed" if child.passes is True else ("failed" if child.passes is False else "pending"),
            "tokens": child.tokens,
        }
        if child.children:
            entry["children"] = _collect_children(child)
        result.append(entry)
    return result


def to_json_output(node: LineageNode) -> dict[str, Any]:
    """Convert a LineageNode tree to JSON-serialisable dict.

    Schema matches acceptance criteria:
    {
        "id": "US-528",
        "title": "Cost Predictor CLI: ...",
        "status": "passed",
        "tokens": 45000,
        "children": [
            {"id": "US-529", "title": "...", "status": "passed", "tokens": 30000},
        ]
    }
    """
    output: dict[str, Any] = {
        "id": node.story_id,
        "title": node.title,
        "status": "passed" if node.passes is True else ("failed" if node.passes is False else "pending"),
        "tokens": node.tokens,
    }
    if node.children:
        output["children"] = _collect_children(node)
    return output
