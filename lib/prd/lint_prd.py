#!/usr/bin/env python3
"""lib/prd/lint_prd.py — Comprehensive prd.json linter (US-639).

Validates prd.json against prd.schema.json, detects duplicate story IDs,
checks US-NNN naming conventions, and detects circular dependencies via
topological sort (with DFS cycle-path extraction).

Output format:
  {"valid": bool, "errors": [
    {"type": "schema", "message": "Missing field: acceptanceCriteria"},
    {"type": "duplicate_id", "story_id": "US-123"},
    {"type": "naming", "story_id": "US123", "message": "..."},
    {"type": "circular_dep", "cycle": ["US-45", "US-67", "US-45"]},
  ]}
"""

import json
import os
import re
import sys
from pathlib import Path

STORY_ID_PATTERN = re.compile(r"^(US|UT)-\d{3,}$")


def _find_cycle_path(graph: dict[str, list[str]]) -> list[str] | None:
    """DFS to find a cycle.  Returns cycle as [a, b, ..., a] or None."""
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> list[str] | None:
        if node in path_set:
            idx = path.index(node)
            return path[idx:] + [node]
        if node in visited:
            return None
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for neighbor in graph.get(node, []):
            result = dfs(neighbor)
            if result is not None:
                return result
        path.pop()
        path_set.discard(node)
        return None

    for node in list(graph.keys()):
        if node not in visited:
            result = dfs(node)
            if result is not None:
                return result
    return None


def lint_prd(prd: object, schema_path: str | None = None) -> dict[str, object]:
    """Lint a prd.json dict and return a structured report.

    Args:
        prd: Parsed prd.json content (should be a dict).
        schema_path: Optional path to prd.schema.json (currently unused;
                     reserved for future JSON Schema integration).

    Returns:
        {"valid": bool, "errors": list[dict]}
    """
    errors: list[dict[str, object]] = []

    if not isinstance(prd, dict):
        errors.append({"type": "schema", "message": "Root must be a JSON object"})
        return {"valid": False, "errors": errors}

    # ── Top-level required fields ─────────────────────────────────────────────
    for field in ("productName", "branchName", "userStories"):
        if field not in prd:
            errors.append({"type": "schema", "message": f"Missing required field: {field}"})

    stories_raw = prd.get("userStories")
    if not isinstance(stories_raw, list):
        errors.append({"type": "schema", "message": "userStories must be a list"})
        return {"valid": len(errors) == 0, "errors": errors}

    stories: list[dict[str, object]] = [s for s in stories_raw if isinstance(s, dict)]

    # ── Story-level required fields ───────────────────────────────────────────
    for i, story in enumerate(stories_raw):
        if not isinstance(story, dict):
            errors.append({"type": "schema", "message": f"userStories[{i}] must be an object"})
            continue
        sid = story.get("id", f"index-{i}")
        for field in ("id", "title", "passes", "acceptanceCriteria", "dependencies"):
            if field not in story:
                errors.append(
                    {
                        "type": "schema",
                        "message": f"Story {sid}: missing required field: {field}",
                    }
                )

    # ── Duplicate ID detection ────────────────────────────────────────────────
    seen: dict[str, int] = {}
    for i, story in enumerate(stories_raw):
        if not isinstance(story, dict):
            continue
        sid = story.get("id")
        if not isinstance(sid, str):
            continue
        if sid in seen:
            errors.append({"type": "duplicate_id", "story_id": sid})
        else:
            seen[sid] = i

    # ── Naming convention (US-NNN / UT-NNN) ──────────────────────────────────
    for story in stories:
        sid = story.get("id")
        if not isinstance(sid, str):
            continue
        if not STORY_ID_PATTERN.match(sid):
            errors.append(
                {
                    "type": "naming",
                    "story_id": sid,
                    "message": f"ID '{sid}' does not match pattern (US|UT)-NNN",
                }
            )

    # ── Circular dependency detection (topological sort + DFS path) ───────────
    all_ids: set[str] = set()
    for story in stories:
        sid = story.get("id")
        if isinstance(sid, str):
            all_ids.add(sid)

    graph: dict[str, list[str]] = {}
    for story in stories:
        sid = story.get("id")
        if not isinstance(sid, str) or sid not in all_ids:
            continue
        deps_raw = story.get("dependencies", [])
        deps: list[str] = [
            d for d in (deps_raw if isinstance(deps_raw, list) else []) if isinstance(d, str) and d in all_ids
        ]
        graph[sid] = deps

    cycle = _find_cycle_path(graph)
    if cycle is not None:
        errors.append({"type": "circular_dep", "cycle": cycle})

    return {"valid": len(errors) == 0, "errors": errors}


def main() -> int:
    import argparse

    # Add lib/ to path so spiral_io is importable when run as a script
    sys.path.insert(0, str(Path(__file__).parent.parent))
    try:
        from spiral_io import configure_utf8_stdout

        configure_utf8_stdout()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Lint prd.json for schema, IDs, naming, and circular deps")
    parser.add_argument("prd", help="Path to prd.json")
    parser.add_argument("--schema", default="", help="Path to prd.schema.json (optional)")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(json.dumps({"valid": False, "errors": [{"type": "schema", "message": f"File not found: {args.prd}"}]}))
        return 1

    try:
        with open(args.prd, encoding="utf-8") as fh:
            prd = json.load(fh)
    except json.JSONDecodeError as exc:
        print(json.dumps({"valid": False, "errors": [{"type": "schema", "message": f"Invalid JSON: {exc}"}]}))
        return 1

    schema_path: str | None = args.schema if args.schema else None
    report = lint_prd(prd, schema_path)
    print(json.dumps(report, indent=2))
    return 0 if report.get("valid") else 1


if __name__ == "__main__":
    sys.exit(main())
