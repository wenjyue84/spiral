"""phase_m_federated_order.py — Topological sort for federated stories.

Scans story descriptions for cross-project story ID references (e.g., 'depends on US-B5')
and builds a dependency graph, returning a topologically sorted list of stories so that
dependency stories are merged before the stories that depend on them.

Story: US-617
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

# Import story_reorder from parent lib directory
_LIB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_LIB_DIR))
from story_reorder import build_dep_graph, topological_sort  # noqa: E402

# Pattern to detect cross-project story ID references in description text.
# Matches: "depends on US-123", "requires US-B5", "after US-42", etc.
_DEP_PATTERN = re.compile(
    r"(?:depends?\s+on|requires?|after|needs?)\s+((?:US|UT|FE|BE)-[A-Za-z0-9]+)",
    re.IGNORECASE,
)
# Also match bare "US-XYZ", "FE-XYZ", "BE-XYZ" references near dependency keywords.
_BARE_ID_PATTERN = re.compile(r"\b((?:US|UT|FE|BE)-[A-Za-z0-9]+)\b")


def _extract_referenced_ids(text: str) -> list[str]:
    """Extract story IDs referenced in a dependency context from text."""
    ids: list[str] = []
    for match in _DEP_PATTERN.finditer(text):
        ids.append(match.group(1))
    return ids


def _build_dep_graph_with_descriptions(stories: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build a dependency graph including description-based cross-story references.

    This extends the basic dependency graph by scanning descriptions for references
    like "depends on US-123" or "requires US-B5". Used for federated PRD scenarios
    where story IDs may be scattered across descriptions.

    Returns dict mapping story_id to list of dependency_ids.
    """
    # Start with the base graph from story_reorder
    graph: dict[str, list[str]] = build_dep_graph(stories)

    # Now enhance it by scanning descriptions for textual references
    known_ids = {s.get("id", "") for s in stories if s.get("id")}

    for story in stories:
        sid = story.get("id", "")
        if not sid or sid not in graph:
            continue

        # Scan description for textual references
        description = story.get("description", "")
        for ref_id in _extract_referenced_ids(description):
            if ref_id in known_ids and ref_id != sid and ref_id not in graph.get(sid, []):
                graph[sid].append(ref_id)

    return graph


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
                    'circular dependency: US-A1→US-B1→US-A1'.
    """
    if not stories:
        return []

    # Separate stories with and without IDs; only sort those with IDs.
    id_stories = [s for s in stories if s.get("id")]
    no_id_stories = [s for s in stories if not s.get("id")]

    if not id_stories:
        return list(stories)

    graph = _build_dep_graph_with_descriptions(id_stories)

    # Check for cycles before sorting
    known_ids = {s["id"] for s in id_stories}
    cycle = _detect_cycle(graph, known_ids)
    if cycle is not None:
        raise ValueError(f"circular dependency: {'\u2192'.join(cycle)}")

    sorted_stories = topological_sort(id_stories, graph)
    result: list[dict[str, Any]] = sorted_stories + no_id_stories
    return result


def _detect_cycle(
    graph: dict[str, list[str]],
    known_ids: set[str],
) -> list[str] | None:
    """Return cycle path if a circular dependency exists, else None."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {sid: WHITE for sid in known_ids}
    path: list[str] = []

    def dfs(u: str) -> list[str] | None:
        color[u] = GRAY
        path.append(u)
        for v in graph.get(u, []):
            if v not in known_ids:
                continue
            if color[v] == GRAY:
                cycle_start = path.index(v)
                return path[cycle_start:] + [v]
            if color[v] == WHITE:
                result = dfs(v)
                if result is not None:
                    return result
        path.pop()
        color[u] = BLACK
        return None

    for sid in sorted(known_ids):
        if color[sid] == WHITE:
            result = dfs(sid)
            if result is not None:
                return result
    return None
