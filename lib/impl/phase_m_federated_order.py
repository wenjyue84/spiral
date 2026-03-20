"""phase_m_federated_order.py — Topological sort for federated stories.

Scans story descriptions for cross-project story ID references (e.g., 'depends on US-B5')
and builds a dependency graph, returning a topologically sorted list of stories so that
dependency stories are merged before the stories that depend on them.

Story: US-617
"""

from __future__ import annotations

import re
from typing import Any


# Pattern to detect cross-project story ID references in description text.
# Matches: "depends on US-123", "requires US-B5", "after US-42", etc.
_DEP_PATTERN = re.compile(
    r"(?:depends?\s+on|requires?|after|needs?)\s+((?:US|UT)-[A-Za-z0-9]+)",
    re.IGNORECASE,
)
# Also match bare "US-XYZ" references when they appear near dependency keywords.
_BARE_ID_PATTERN = re.compile(r"\b((?:US|UT)-[A-Za-z0-9]+)\b")


def _extract_referenced_ids(text: str) -> list[str]:
    """Extract story IDs referenced in a dependency context from text."""
    ids: list[str] = []
    for match in _DEP_PATTERN.finditer(text):
        ids.append(match.group(1))
    return ids


def _build_dep_graph(stories: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Build a dependency graph: story_id -> set of story_ids it depends on.

    Scans description and dependencies fields for cross-story references.
    Only includes dependencies that correspond to known story IDs in the list.
    """
    known_ids = {s.get("id", "") for s in stories if s.get("id")}

    graph: dict[str, set[str]] = {s["id"]: set() for s in stories if s.get("id")}

    for story in stories:
        sid = story.get("id", "")
        if not sid:
            continue

        # Check explicit dependencies field first
        explicit_deps = story.get("dependencies", [])
        for dep in explicit_deps:
            dep_str = str(dep).strip()
            if dep_str in known_ids and dep_str != sid:
                graph[sid].add(dep_str)

        # Scan description for textual references
        description = story.get("description", "")
        for ref_id in _extract_referenced_ids(description):
            if ref_id in known_ids and ref_id != sid:
                graph[sid].add(ref_id)

    return graph


def _topological_sort(
    stories: list[dict[str, Any]],
    graph: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Kahn's algorithm for topological sort with cycle detection.

    Raises ValueError with a cycle description if a circular dependency is detected.
    Returns stories in dependency-first order (dependencies before dependents).
    """
    story_map = {s["id"]: s for s in stories if s.get("id")}

    # Count in-degrees (how many stories depend ON each story — i.e., predecessors)
    # We want dependencies first, so edges go: "depends_on -> dependent"
    # In-degree of a node = number of its own dependencies that haven't been processed
    in_degree: dict[str, int] = {sid: len(deps) for sid, deps in graph.items()}

    # Reverse graph: for each dependency, which stories depend on it?
    reverse: dict[str, list[str]] = {sid: [] for sid in graph}
    for sid, deps in graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].append(sid)

    # Start with stories that have no unresolved dependencies
    queue = sorted(sid for sid, count in in_degree.items() if count == 0)
    result: list[dict[str, Any]] = []

    while queue:
        sid = queue.pop(0)
        result.append(story_map[sid])
        # Reduce in-degree for all stories that depended on this one
        for dependent in sorted(reverse.get(sid, [])):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(stories):
        # Find a cycle to report
        unprocessed = [sid for sid in in_degree if story_map.get(sid) not in result]
        cycle = _find_cycle(unprocessed, graph)
        raise ValueError(f"circular dependency: {cycle}")

    return result


def _find_cycle(candidates: list[str], graph: dict[str, set[str]]) -> str:
    """Find and format a cycle among the candidate story IDs."""
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> str | None:
        if node in path:
            cycle_start = path.index(node)
            return "\u2192".join(path[cycle_start:] + [node])
        if node in visited:
            return None
        visited.add(node)
        path.append(node)
        for neighbor in sorted(graph.get(node, [])):
            result = dfs(neighbor)
            if result:
                return result
        path.pop()
        return None

    for start in sorted(candidates):
        result = dfs(start)
        if result:
            return result

    return " -> ".join(candidates[:3]) + " (cycle)"


def order_federated_stories_by_dependency(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order federated stories so dependencies are merged before dependents.

    Scans story descriptions for cross-project story ID references and builds
    a dependency graph, then returns a topologically sorted list.

    Args:
        stories: List of story dicts from prd.json.

    Returns:
        Stories in topological order (dependency stories first).
        Stories without an 'id' field are appended at the end unchanged.

    Raises:
        ValueError: If a circular dependency is detected, with message like
                    'circular dependency: US-A1\u2192US-B1\u2192US-A1'.
    """
    if not stories:
        return []

    # Separate stories with and without IDs; only sort those with IDs.
    id_stories = [s for s in stories if s.get("id")]
    no_id_stories = [s for s in stories if not s.get("id")]

    if not id_stories:
        return list(stories)

    graph = _build_dep_graph(id_stories)
    sorted_stories = _topological_sort(id_stories, graph)
    return sorted_stories + no_id_stories
