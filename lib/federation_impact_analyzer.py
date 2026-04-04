"""lib/federation_impact_analyzer.py — Federation Blast Radius Analyzer.

Computes which stories in other sub-projects are transitively affected when
a given sub-project changes. Uses reverse dependency graph + BFS traversal.
Detects cycles in the story dependency DAG using iterative DFS (safe for large graphs).
"""

from __future__ import annotations

from typing import Any


def _build_dependents_graph(stories: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build reverse dependency graph: story_id -> list of story_ids that depend on it."""
    dependents: dict[str, list[str]] = {s["id"]: [] for s in stories}
    for story in stories:
        for dep in story.get("dependencies", []):
            if dep not in dependents:
                dependents[dep] = []
            dependents[dep].append(story["id"])
    return dependents


def _detect_cycles(forward_deps: dict[str, list[str]]) -> bool:
    """Return True if any cycle exists in the directed graph.

    Uses iterative DFS with three-colour marking (WHITE=0, GRAY=1, BLACK=2).
    Iterative to avoid Python recursion limit on large graphs.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    for start in forward_deps:
        if color.get(start, WHITE) != WHITE:
            continue
        # Stack items: (node, iterator_over_children)
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, idx = stack[-1]
            children = forward_deps.get(node, [])
            if idx < len(children):
                stack[-1] = (node, idx + 1)
                child = children[idx]
                child_color = color.get(child, WHITE)
                if child_color == GRAY:
                    return True
                if child_color == WHITE:
                    color[child] = GRAY
                    stack.append((child, 0))
            else:
                color[node] = BLACK
                stack.pop()
    return False


def transitive_closure(
    sub_project_id: str,
    stories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute blast radius: stories/sub-projects transitively affected by a change.

    Args:
        sub_project_id: The sub-project that is changing (e.g. "auth-service")
        stories: List of story dicts from prd.json

    Returns:
        {
            "affected_sub_projects": [str, ...],  # other sub-projects impacted
            "critical_stories": [str, ...],       # story IDs on the critical path
            "cycle_detected": bool,
        }
    """
    story_map: dict[str, dict[str, Any]] = {s["id"]: s for s in stories}

    # Build forward deps for cycle detection
    forward_deps: dict[str, list[str]] = {s["id"]: list(s.get("dependencies", [])) for s in stories}
    cycle_detected = _detect_cycles(forward_deps)

    # Build reverse graph: node -> stories that depend on it
    dependents = _build_dependents_graph(stories)

    # Stories owned by the target sub-project
    source_ids: set[str] = {s["id"] for s in stories if s.get("sub_project", "") == sub_project_id}

    # BFS to find all transitively affected story IDs
    visited: set[str] = set()
    queue = list(source_ids)
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for dependent in dependents.get(current, []):
            if dependent not in visited:
                queue.append(dependent)

    # Affected = visited minus source stories
    affected_ids = visited - source_ids

    # Critical stories: affected stories outside the source sub-project
    critical_stories = sorted(
        sid for sid in affected_ids if story_map.get(sid, {}).get("sub_project", "") != sub_project_id
    )

    # Affected sub-projects: distinct sub-project values of affected stories (excluding source)
    affected_sub_projects = sorted(
        {
            story_map[sid]["sub_project"]
            for sid in affected_ids
            if story_map.get(sid, {}).get("sub_project") and story_map[sid]["sub_project"] != sub_project_id
        }
    )

    return {
        "affected_sub_projects": affected_sub_projects,
        "critical_stories": critical_stories,
        "cycle_detected": cycle_detected,
    }
