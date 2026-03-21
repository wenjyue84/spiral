"""lib/phase_s_dep_check.py — Phase S circular dependency checker (US-673).

Validates that dependency chains across federated sub-projects do not form
cycles before Phase M merges new stories into prd.json.

Usage (Python API):
    from phase_s_dep_check import detect_circular_deps, validate_prd_for_merge

    result = validate_prd_for_merge(prd)
    if result.has_error:
        # halt Phase M merge
        raise SystemExit(1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of a Phase S dependency graph validation check."""

    error: str | None = None
    cycle_path: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def has_error(self) -> bool:
        """Return True if validation found an error."""
        return self.error is not None


def find_cycle_path(stories: list[dict[str, Any]]) -> list[str]:
    """Return a cycle path like ['US-100', 'US-101', 'US-100'] or [] if no cycle.

    Uses iterative DFS with gray/black coloring. If a back edge is found,
    extracts the cycle path and returns it with the start node repeated at
    the end to show the cycle closes.

    Args:
        stories: List of story dicts, each with 'id' and 'dependencies' keys.

    Returns:
        List of story IDs forming the cycle (empty list if no cycle).
    """
    story_ids: set[str] = {s["id"] for s in stories if isinstance(s, dict) and "id" in s}
    deps: dict[str, list[str]] = {}
    for s in stories:
        if not isinstance(s, dict):
            continue
        sid: str = s.get("id", "")
        if sid:
            deps[sid] = [d for d in s.get("dependencies", []) if d in story_ids]

    color: dict[str, int] = {}  # 0=white, 1=gray, 2=black

    def _dfs(node: str, path: list[str]) -> list[str]:
        color[node] = 1
        for dep in deps.get(node, []):
            dep_color = color.get(dep, 0)
            if dep_color == 1:
                # Back edge found — extract the cycle segment
                cycle_start = path.index(dep)
                return path[cycle_start:] + [dep]
            if dep_color == 0:
                inner = _dfs(dep, path + [dep])
                if inner:
                    return inner
        color[node] = 2
        return []

    for sid in story_ids:
        if color.get(sid, 0) == 0:
            result = _dfs(sid, [sid])
            if result:
                return result
    return []


def detect_circular_deps(stories: list[dict[str, Any]]) -> ValidationResult:
    """Check a list of stories for circular dependency chains.

    Returns a ValidationResult with error='CIRCULAR_DEPENDENCY' and the
    cycle_path if a cycle is found, or an empty ValidationResult if the
    dependency graph is a valid DAG.

    The cycle_path is a list of story IDs showing the cycle, e.g.:
    ['US-100', 'US-101', 'US-100'] — the last element repeats the first
    to show the cycle closes.

    Args:
        stories: List of story dicts with 'id' and 'dependencies' fields.

    Returns:
        ValidationResult with error='CIRCULAR_DEPENDENCY' if a cycle exists.
    """
    cycle_path = find_cycle_path(stories)
    if not cycle_path:
        return ValidationResult()

    cycle_str = " -> ".join(cycle_path)
    message = f"[S] CIRCULAR_DEPENDENCY detected: {cycle_str}"
    print(message)

    return ValidationResult(
        error="CIRCULAR_DEPENDENCY",
        cycle_path=cycle_path,
        message=message,
    )


def validate_prd_for_merge(prd: dict[str, Any]) -> ValidationResult:
    """Validate a PRD's stories for circular dependencies before Phase M merge.

    If circular dependencies are detected, Phase M merge must be halted
    until the dependency chain is resolved.

    Args:
        prd: Full prd.json dict with a 'userStories' key.

    Returns:
        ValidationResult — if has_error is True, Phase M merge must be halted.
    """
    stories: list[dict[str, Any]] = prd.get("userStories", [])
    result = detect_circular_deps(stories)
    if result.has_error:
        cycle_str = " -> ".join(result.cycle_path)
        print(f"[S] Phase M merge HALTED: circular dependency detected — resolve before merging: {cycle_str}")
    return result
