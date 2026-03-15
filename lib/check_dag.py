#!/usr/bin/env python3
"""
SPIRAL — Dependency DAG Validator
Checks prd.json dependency graph for cycles using topological sort.
Exit 0 = valid DAG, Exit 1 = cycles detected (prints cycle members).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import configure_utf8_stdout
configure_utf8_stdout()


def find_cycles(stories: list[dict]) -> list[str]:
    """Return list of story IDs involved in dependency cycles, or [] if DAG is valid."""
    story_ids = {s["id"] for s in stories if isinstance(s, dict) and "id" in s}

    # Build adjacency: id → set of deps that are also in story_ids
    deps: dict[str, set[str]] = {}
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid = s.get("id", "")
        if sid:
            deps[sid] = {d for d in s.get("dependencies", []) if d in story_ids}

    # Kahn's algorithm: topological sort to detect cycles
    in_degree: dict[str, int] = {sid: 0 for sid in story_ids}
    for sid, dep_set in deps.items():
        for dep in dep_set:
            if dep in in_degree:
                in_degree[sid] = in_degree.get(sid, 0)  # ensure exists

    # Recompute in_degree properly: count how many stories depend on each
    in_degree = {sid: 0 for sid in story_ids}
    for sid in story_ids:
        for dep in deps.get(sid, set()):
            pass  # dep is a prerequisite OF sid

    # Actually: in_degree[sid] = number of unresolved deps sid has
    remaining = dict(deps)
    resolved: set[str] = set()
    queue = [sid for sid in story_ids if not remaining.get(sid)]

    while queue:
        batch = list(queue)
        queue = []
        for sid in batch:
            resolved.add(sid)
        # Find newly unblocked
        for sid in story_ids - resolved:
            if remaining.get(sid, set()) <= resolved:
                queue.append(sid)

    cycle_members = sorted(story_ids - resolved)
    return cycle_members


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check prd.json dependencies for cycles")
    parser.add_argument("prd", help="Path to prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[dag] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[dag] ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    stories = prd.get("userStories", [])
    cycles = find_cycles(stories)

    if cycles:
        print(f"[dag] ERROR: Dependency cycle detected involving {len(cycles)} stories:", file=sys.stderr)
        for sid in cycles:
            title = ""
            for s in stories:
                if isinstance(s, dict) and s.get("id") == sid:
                    title = s.get("title", "")
                    deps_str = ", ".join(s.get("dependencies", []))
                    break
            print(f"  - {sid}: {title} (deps: {deps_str})", file=sys.stderr)
        return 1

    print(f"[dag] {args.prd} — no cycles ({len(stories)} stories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
