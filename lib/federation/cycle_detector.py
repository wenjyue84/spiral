"""Detect and report all circular story dependencies with cycle paths (US-1047).

Returns list of cycle paths for federated PRD cycle detection and debugging.
"""

from __future__ import annotations

from typing import Any


def find_cycles(prd_dict: dict[str, Any]) -> list[list[str]]:
    """Find all circular dependency cycles in story dependencies.

    Args:
      prd_dict: Parsed prd.json with userStories array

    Returns:
      List of cycle paths, where each path is [a, b, ..., a] (closed loop).
      Empty list if no cycles found.
    """
    # Build graph of story dependencies
    stories = prd_dict.get("userStories", [])
    all_ids: set[str] = set()
    for story in stories:
        if isinstance(story, dict):
            sid = story.get("id")
            if isinstance(sid, str):
                all_ids.add(sid)

    graph: dict[str, list[str]] = {}
    for story in stories:
        if not isinstance(story, dict):
            continue
        sid = story.get("id")
        if not isinstance(sid, str) or sid not in all_ids:
            continue
        deps_raw = story.get("dependencies", [])
        deps: list[str] = [
            d for d in (deps_raw if isinstance(deps_raw, list) else []) if isinstance(d, str) and d in all_ids
        ]
        graph[sid] = deps

    # Find all cycles using DFS
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        """DFS to find cycles. When we encounter a node in rec_stack, we found a cycle."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                # Found a cycle: extract from neighbor onwards and close it
                idx = path.index(neighbor)
                cycle = path[idx:] + [neighbor]
                # Only add if not already found (avoid duplicate cycles)
                if cycle not in cycles:
                    cycles.append(cycle)

        path.pop()
        rec_stack.discard(node)

    # Run DFS from all unvisited nodes
    for node in all_ids:
        if node not in visited:
            dfs(node, [])

    return cycles
