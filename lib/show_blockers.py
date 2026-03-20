"""lib/show_blockers.py — Story dependency graph analysis (US-538).

Functions
---------
get_story_blockers(story_id, stories) -> dict
    Return blocked_by, blocks, transitive_closure_depth, circular_path for one story.

build_dot_graph(stories) -> str
    Return a Graphviz DOT representation of all story dependencies.
"""

from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_graph(
    stories: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build forward (blocked_by) and reverse (blocks) adjacency maps.

    forward[A] = list of story IDs that A depends on  (i.e. A is blocked by them)
    reverse[B] = list of story IDs that depend on B    (i.e. B blocks them)
    """
    all_ids = {s["id"] for s in stories}

    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {s["id"]: [] for s in stories}

    for story in stories:
        sid = story["id"]
        deps = [d for d in story.get("dependencies", []) if d in all_ids]
        forward[sid] = deps
        for dep in deps:
            if dep not in reverse:
                reverse[dep] = []
            reverse[dep].append(sid)

    return forward, reverse


def _transitive_depth(story_id: str, forward: dict[str, list[str]]) -> int:
    """Return the length of the longest dependency chain reachable from story_id.

    Uses iterative DFS with memoisation; returns 0 when there are no deps.
    Stops early on cycles to avoid infinite loops.
    """
    memo: dict[str, int] = {}
    in_stack: set[str] = set()

    def dfs(sid: str) -> int:
        if sid in memo:
            return memo[sid]
        if sid in in_stack:
            # Cycle — cap depth here to avoid infinite recursion
            return 0
        in_stack.add(sid)
        max_d = 0
        for dep in forward.get(sid, []):
            max_d = max(max_d, 1 + dfs(dep))
        in_stack.discard(sid)
        memo[sid] = max_d
        return max_d

    return dfs(story_id)


def _find_cycle(story_id: str, forward: dict[str, list[str]]) -> Optional[list[str]]:
    """Return the first cycle path reachable from *story_id*, or None.

    The returned list starts and ends with the repeated node so the cycle is
    self-evident, e.g. ["US-001", "US-002", "US-001"].
    """
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(sid: str) -> Optional[list[str]]:
        if sid in path_set:
            # Cycle detected — extract the repeating segment
            idx = path.index(sid)
            return path[idx:] + [sid]
        path.append(sid)
        path_set.add(sid)
        for dep in forward.get(sid, []):
            result = dfs(dep)
            if result is not None:
                return result
        path.pop()
        path_set.discard(sid)
        return None

    return dfs(story_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_story_blockers(story_id: str, stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a blocker summary dict for *story_id*.

    Keys
    ----
    story_id             : str  — echoes back the requested ID
    blocked_by           : list[str]  — direct dependencies (IDs)
    blocks               : list[str]  — stories that depend on this one
    transitive_closure_depth : int   — length of longest dep chain
    circular_path        : list[str] | None — cycle path if found, else None
    """
    forward, reverse = _build_graph(stories)

    blocked_by = forward.get(story_id, [])
    blocks = reverse.get(story_id, [])
    depth = _transitive_depth(story_id, forward)
    cycle = _find_cycle(story_id, forward)

    return {
        "story_id": story_id,
        "blocked_by": blocked_by,
        "blocks": blocks,
        "transitive_closure_depth": depth,
        "circular_path": cycle,
    }


def build_dot_graph(stories: list[dict[str, Any]]) -> str:
    """Return a Graphviz DOT graph of all dependency edges in *stories*.

    Usable with: ``dot -Tpng graph.dot -o graph.png``
    """
    forward, _ = _build_graph(stories)

    lines: list[str] = [
        "digraph spiral_deps {",
        '  rankdir="LR";',
        "  node [shape=box, style=rounded];",
    ]

    for sid in sorted(forward):
        deps = forward[sid]
        # Always emit the node (even if isolated)
        label = sid.replace('"', '\\"')
        lines.append(f'  "{label}";')
        for dep in sorted(deps):
            dep_label = dep.replace('"', '\\"')
            lines.append(f'  "{label}" -> "{dep_label}";')

    lines.append("}")
    return "\n".join(lines)
