#!/usr/bin/env python3
"""
SPIRAL — Mermaid Dependency Graph Generator
Reads prd.json and emits a Mermaid flowchart showing story dependency edges.

Usage:
    python lib/dependency_graph.py prd.json
    python lib/dependency_graph.py prd.json --output docs/dependency-graph.md
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import configure_utf8_stdout
configure_utf8_stdout()

_TITLE_MAX = 40


def _truncate(title: str, max_len: int = _TITLE_MAX) -> str:
    if len(title) <= max_len:
        return title
    return title[: max_len - 1] + "…"


def _escape_mermaid(text: str) -> str:
    """Escape characters that break Mermaid node labels."""
    return text.replace('"', "#quot;").replace("(", "#40;").replace(")", "#41;")


def _find_cycle_edges(stories: list[dict[str, Any]], cycle_members: set[str]) -> set[tuple[str, str]]:
    """Return edges (from, to) where both endpoints are in a cycle."""
    edges: set[tuple[str, str]] = set()
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if sid not in cycle_members:
            continue
        for dep in s.get("dependencies", []):
            if dep in cycle_members:
                edges.add((dep, sid))
    return edges


def find_cycles(stories: list[dict[str, Any]]) -> list[str]:
    """Return sorted list of story IDs involved in dependency cycles, or [] if DAG is valid."""
    story_ids = {s["id"] for s in stories if isinstance(s, dict) and "id" in s}

    deps: dict[str, set[str]] = {}
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if sid:
            deps[sid] = {d for d in s.get("dependencies", []) if d in story_ids}

    remaining = dict(deps)
    resolved: set[str] = set()
    queue = [sid for sid in story_ids if not remaining.get(sid)]

    while queue:
        batch = list(queue)
        queue = []
        for sid in batch:
            resolved.add(sid)
        for sid in story_ids - resolved:
            if remaining.get(sid, set()) <= resolved:
                queue.append(sid)

    return sorted(story_ids - resolved)


def generate_graph(stories: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Generate a Mermaid flowchart string and return (mermaid_text, cycle_ids).

    - Nodes without dependencies use stadium shape (([...])).
    - Nodes with dependencies use rectangle ([...]).
    - Cycle edges are rendered with a red style link.
    """
    story_ids = {s["id"] for s in stories if isinstance(s, dict) and "id" in s}
    cycle_ids = find_cycles(stories)
    cycle_set = set(cycle_ids)

    # Build safe node ID mapping (Mermaid IDs must be alphanumeric+underscore)
    def node_id(sid: str) -> str:
        return sid.replace("-", "_")

    lines: list[str] = ["```mermaid", "flowchart LR"]

    # Node declarations
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if not sid:
            continue
        label = _escape_mermaid(_truncate(s.get("title", sid)))
        full_label = f"{sid}: {label}"
        nid = node_id(sid)
        has_deps = bool([d for d in s.get("dependencies", []) if d in story_ids])
        if has_deps:
            lines.append(f"    {nid}[{full_label!r}]")
        else:
            # Stadium shape — visually distinct for root/independent nodes
            lines.append(f"    {nid}([{full_label!r}])")

    # Edge declarations — collect cycle edges separately
    cycle_edge_indices: list[int] = []
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if not sid:
            continue
        for dep in s.get("dependencies", []):
            if dep not in story_ids:
                continue
            edge_line = f"    {node_id(dep)} --> {node_id(sid)}"
            if dep in cycle_set and sid in cycle_set:
                cycle_edge_indices.append(len(lines))
            lines.append(edge_line)

    # Style cycle nodes in red
    if cycle_set:
        cycle_node_ids = ",".join(node_id(sid) for sid in sorted(cycle_set))
        lines.append(f"    style {cycle_node_ids} fill:#ff6b6b,stroke:#c0392b,color:#fff")

    lines.append("```")
    return "\n".join(lines), cycle_ids


def cmd_graph(prd_path: Path, output: Optional[Path]) -> int:
    if not prd_path.exists():
        print(f"[graph] ERROR: {prd_path} not found", file=sys.stderr)
        return 1

    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[graph] ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    stories = prd.get("userStories", [])
    mermaid_text, cycle_ids = generate_graph(stories)

    # Report cycles as errors
    if cycle_ids:
        print(
            f"[graph] ERROR: Dependency cycle detected involving {len(cycle_ids)} stories:",
            file=sys.stderr,
        )
        story_map = {s["id"]: s for s in stories if isinstance(s, dict) and "id" in s}
        for sid in cycle_ids:
            s = story_map.get(sid, {})
            title = s.get("title", "")
            deps_str = ", ".join(s.get("dependencies", []))
            print(f"  - {sid}: {title} (deps: {deps_str})", file=sys.stderr)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        header = "# SPIRAL Story Dependency Graph\n\n_Auto-generated by `spiral graph`. Do not edit manually._\n\n"
        output.write_text(header + mermaid_text + "\n", encoding="utf-8")
        print(f"[graph] Written to {output}")
    else:
        print(mermaid_text)

    return 1 if cycle_ids else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Mermaid dependency graph from prd.json")
    parser.add_argument("prd", nargs="?", default="prd.json", help="Path to prd.json (default: prd.json)")
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Write graph to FILE instead of stdout (e.g. docs/dependency-graph.md)",
    )
    args = parser.parse_args()

    prd_path = Path(args.prd)
    output = Path(args.output) if args.output else None
    return cmd_graph(prd_path, output)


if __name__ == "__main__":
    sys.exit(main())
