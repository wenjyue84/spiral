#!/usr/bin/env python3
"""DAG validator for story dependencies.

Detects circular dependencies and orphan references before Phase I.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def detect_cycles(stories: list[dict[str, Any]]) -> list[list[str]]:
    """Detect circular dependencies via topological sort (DFS).

    Args:
        stories: List of story dicts with id and optional dependencies field

    Returns:
        List of cycle chains, e.g. [['A', 'B', 'C', 'A'], ...]
    """
    cycles: list[list[str]] = []
    graph: dict[str, list[str]] = defaultdict(list)
    story_ids = {s["id"] for s in stories}

    # Build adjacency list
    for story in stories:
        deps = story.get("dependencies", []) or []
        for dep_id in deps:
            if dep_id in story_ids:  # Only add valid deps
                graph[story["id"]].append(dep_id)

    visited = set()
    rec_stack = set()

    def dfs(node: str, path: list[str]) -> None:
        """DFS to detect cycles; records all cycles found."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path[:])
            elif neighbor in rec_stack:
                # Found cycle: trace back to neighbor in path
                if neighbor in path:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

        rec_stack.discard(node)

    for story in stories:
        if story["id"] not in visited:
            dfs(story["id"], [])

    return cycles


def detect_orphans(stories: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Detect stories depending on non-existent IDs.

    Args:
        stories: List of story dicts

    Returns:
        List of (story_id, missing_dependency_id) tuples
    """
    story_ids = {s["id"] for s in stories}
    orphans: list[tuple[str, str]] = []

    for story in stories:
        deps = story.get("dependencies", []) or []
        for dep_id in deps:
            if dep_id not in story_ids:
                orphans.append((story["id"], dep_id))

    return orphans


def get_deadlock_ratio(stories: list[dict[str, Any]]) -> float:
    """Compute percentage of pending stories that are in cycles or orphaned.

    Args:
        stories: List of story dicts

    Returns:
        Float 0.0-1.0 representing ratio of deadlocked pending stories
    """
    cycles = detect_cycles(stories)
    orphans = detect_orphans(stories)

    # Stories in cycles
    story_ids_in_cycles = set()
    for cycle in cycles:
        story_ids_in_cycles.update(cycle[:-1])  # Exclude the repeated node

    # Stories with orphan deps
    story_ids_orphaned = {s for s, _ in orphans}

    # All deadlocked story IDs
    deadlocked = story_ids_in_cycles | story_ids_orphaned

    # Pending stories (passes != True)
    pending_stories = [s for s in stories if not s.get("passes", False)]
    if not pending_stories:
        return 0.0

    pending_ids = {s["id"] for s in pending_stories}
    deadlocked_pending = deadlocked & pending_ids

    return len(deadlocked_pending) / len(pending_ids) if pending_ids else 0.0


def validate_all(
    stories: list[dict[str, Any]],
) -> tuple[bool, list[list[str]], list[tuple[str, str]], float]:
    """Run all validations.

    Returns:
        (has_issues, cycles, orphans, deadlock_ratio)
    """
    cycles = detect_cycles(stories)
    orphans = detect_orphans(stories)
    ratio = get_deadlock_ratio(stories)
    has_issues = bool(cycles or orphans)

    return has_issues, cycles, orphans, ratio


def format_cycle_chain(cycle: list[str]) -> str:
    """Format a cycle chain as human-readable string (A->B->C->A)."""
    return "->".join(cycle)


def main() -> int:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m lib.dag_validator <prd.json>")
        return 1

    prd_path = Path(sys.argv[1])
    if not prd_path.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        return 1

    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    has_issues, cycles, orphans, ratio = validate_all(stories)

    # Output results as JSON for shell integration
    result = {
        "has_issues": has_issues,
        "cycles": [format_cycle_chain(c) for c in cycles],
        "orphans": [{"story_id": s, "missing_dep": d} for s, d in orphans],
        "deadlock_ratio": ratio,
        "skip_phase_i": ratio > 0.2,
    }

    print(json.dumps(result))
    return 0 if not has_issues else 1


if __name__ == "__main__":
    sys.exit(main())
