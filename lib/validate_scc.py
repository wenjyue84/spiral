"""validate_scc.py — Detect circular dependencies in prd.json using Tarjan's SCC algorithm.

Reads story._dependencies (not story.dependencies) to build the directed graph.

Output schema:
    {
        "acyclic": true | false,
        "cycles": [[story_id, ...], ...],   # one list per SCC with size > 1 or self-loop
        "cycle_paths": ["US-101 → US-102 → US-103 → US-101", ...]  # human-readable
    }
"""

from __future__ import annotations

from typing import Any


def build_graph(stories: list[Any]) -> dict[str, list[str]]:
    """Build directed adjacency list from story._dependencies field.

    Only includes edges where both endpoints are known story IDs.
    """
    known_ids: set[str] = {
        str(s["id"]) for s in stories if isinstance(s, dict) and "id" in s and isinstance(s["id"], str)
    }
    graph: dict[str, list[str]] = {sid: [] for sid in known_ids}
    for story in stories:
        if not isinstance(story, dict):
            continue
        sid = story.get("id", "")
        if not isinstance(sid, str) or not sid or sid not in known_ids:
            continue
        for dep in story.get("_dependencies", []):
            if isinstance(dep, str) and dep in known_ids:
                graph[sid].append(dep)
    return graph


def tarjan_scc(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's strongly connected components algorithm.

    Returns a list of SCCs. Each SCC is a list of node IDs.
    SCCs with size > 1, or size 1 with a self-loop, are cycles.
    """
    index_counter = [0]
    stack: list[str] = []
    on_stack: dict[str, bool] = {}
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w, False):
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in graph:
        if v not in index:
            strongconnect(v)

    return sccs


def _find_cycle_path(scc: list[str], graph: dict[str, list[str]]) -> list[str]:
    """Return an ordered cycle path within the given SCC.

    For a self-loop (single-node SCC), returns [node, node].
    For multi-node SCCs, does a DFS to find a cycle and returns it as an ordered path.
    """
    scc_set = set(scc)

    # Self-loop case
    if len(scc) == 1:
        return [scc[0], scc[0]]

    # DFS within SCC subgraph to find a cycle path
    start = scc[0]
    path: list[str] = []
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        visited.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in scc_set:
                continue
            if neighbor == start and len(path) > 1:
                path.append(start)  # close the cycle
                return True
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
        path.pop()
        return False

    dfs(start)
    return path if len(path) > 1 else scc + [scc[0]]


def find_cycles(prd_dict: dict[str, Any]) -> dict[str, Any]:
    """Detect circular dependencies in prd.json using Tarjan's SCC algorithm.

    Args:
        prd_dict: Parsed prd.json dict with 'userStories' key.

    Returns:
        {
            "acyclic": bool,
            "cycles": [[story_id, ...], ...],
            "cycle_paths": ["US-A → US-B → US-A", ...]
        }
    """
    stories: list[Any] = prd_dict.get("userStories", [])
    graph = build_graph(stories)
    sccs = tarjan_scc(graph)

    cycles: list[list[str]] = []
    cycle_paths: list[str] = []

    for scc in sccs:
        is_cycle = len(scc) > 1 or (len(scc) == 1 and scc[0] in graph.get(scc[0], []))
        if is_cycle:
            cycles.append(sorted(scc))
            path = _find_cycle_path(scc, graph)
            cycle_paths.append(" \u2192 ".join(path))

    return {
        "acyclic": len(cycles) == 0,
        "cycles": cycles,
        "cycle_paths": cycle_paths,
    }
