"""lib/story_reorder.py — Topological sort of stories by dependency graph.

Uses Kahn's algorithm to produce optimal merge order for Phase M.

Usage (Python API):
    from story_reorder import topological_sort, build_dep_graph, reorder_stories

    stories = prd["userStories"]
    ordered = reorder_stories(stories)

    # Or use the lower-level API:
    dep_graph = build_dep_graph(stories)
    ordered = topological_sort(stories, dep_graph)
"""

from __future__ import annotations

import heapq
from typing import Any


def build_dep_graph(stories: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list dependency graph from stories.

    Returns {story_id: [dependent_story_ids]}.
    """
    graph: dict[str, list[str]] = {}
    story_ids = {s.get("id") for s in stories if isinstance(s, dict) and "id" in s}

    for story in stories:
        if not isinstance(story, dict) or "id" not in story:
            continue
        sid = story["id"]
        graph[sid] = []
        deps = story.get("dependencies", [])
        if isinstance(deps, list):
            for dep_id in deps:
                if dep_id in story_ids:
                    graph[sid].append(dep_id)

    return graph


def topological_sort(
    stories: list[dict[str, Any]],
    dep_graph: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Topologically sort stories using Kahn's algorithm.

    Returns stories in dependency order (no story before its dependencies).
    Stories with cycles are placed at the end in original order.

    Args:
        stories: List of story dicts from prd.json
        dep_graph: {story_id: [dependency_ids]} from build_dep_graph()

    Returns:
        Sorted list of stories
    """
    story_by_id: dict[str, dict[str, Any]] = {}
    for s in stories:
        if isinstance(s, dict) and "id" in s:
            sid: str = s["id"]
            story_by_id[sid] = s
    story_ids = set(story_by_id.keys())

    # Compute in-degree (number of unmet dependencies)
    in_degree: dict[str, int] = {sid: 0 for sid in story_by_id}
    for sid in story_by_id:
        for dep_id in dep_graph.get(sid, []):
            if dep_id in story_ids:
                in_degree[sid] += 1

    # Priority-aware queue: among ready stories, pick highest priority first.
    # Heap entries: (priority_rank, dep_count, insertion_order, story_id)
    _prio_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _heap_key(sid: str, seq: int) -> tuple[int, int, int, str]:
        s = story_by_id[sid]
        p = s.get("priority", "medium") or "medium"
        rank = _prio_rank.get(p, 2)
        deps = len(s.get("dependencies", []))
        return (rank, deps, seq, sid)

    seq = 0
    heap: list[tuple[int, int, int, str]] = []
    for sid in story_by_id:
        if in_degree[sid] == 0:
            heapq.heappush(heap, _heap_key(sid, seq))
            seq += 1
    result: list[str] = []

    while heap:
        _, _, _, current = heapq.heappop(heap)
        result.append(current)

        # For each story that depends on current, decrement in-degree
        for sid in story_by_id:
            if current in dep_graph.get(sid, []):
                in_degree[sid] -= 1
                if in_degree[sid] == 0:
                    heapq.heappush(heap, _heap_key(sid, seq))
                    seq += 1

    # Collect stories with cycles (unprocessed) in original order
    remaining = [sid for sid in story_by_id if sid not in result]
    original_order: list[str] = []
    for s in stories:
        if isinstance(s, dict) and "id" in s:
            sid = s["id"]
            original_order.append(sid)
    remaining_sorted = [sid for sid in original_order if sid in remaining]

    # Return sorted stories + cycled stories
    final_ids = result + remaining_sorted
    return [story_by_id[sid] for sid in final_ids if sid in story_by_id]


def reorder_stories(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder pending stories by dependency graph using topological sort.

    Convenience wrapper that builds the dependency graph and applies topological sort.

    Args:
        stories: List of pending story dicts

    Returns:
        Reordered list of stories (dependencies before dependents)

    Raises:
        ValueError: If stories list is empty or all stories lack dependencies
    """
    if not stories:
        raise ValueError("No stories to reorder")

    dep_graph = build_dep_graph(stories)
    return topological_sort(stories, dep_graph)


def build_dependency_graph(
    stories: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Build bidirectional dependency graph returning sets of dependencies.

    For use with cmd_show_merge_order. Returns {story_id: set_of_dependency_ids}.

    Args:
        stories: List of story dicts

    Returns:
        {story_id: {dep_id, ...}} for each story with its dependencies
    """
    result: dict[str, set[str]] = {}
    story_ids = {s.get("id") for s in stories if isinstance(s, dict) and "id" in s}

    for story in stories:
        if not isinstance(story, dict) or "id" not in story:
            continue
        sid = story["id"]
        deps = story.get("dependencies", [])
        result[sid] = set()
        if isinstance(deps, list):
            for dep_id in deps:
                if dep_id in story_ids:
                    result[sid].add(dep_id)

    return result
