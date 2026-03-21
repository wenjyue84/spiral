"""lib/check_federated_deps.py — Federated dependency graph validator (US-685).

Validates prd.json for:
- Circular dependencies (A→B→C→A cycles with full path)
- Orphan stories (missing dependency references)
- Namespace conflicts (story ID prefix validation)

Returns JSON with {cycles, orphans, namespaces, valid}.

Usage (Python API):
    from check_federated_deps import validate
    result = validate(prd)
    if not result["valid"]:
        print(f"Cycles: {result['cycles']}")
        print(f"Orphans: {result['orphans']}")

CLI usage (via main.py):
    spiral check-federated-deps prd.json --strict
"""

from typing import Any


def _infer_from_id(story: dict[str, Any]) -> str:
    """Infer sub-project prefix from story ID only.

    e.g., 'PROJECT-B-US-005' -> 'PROJECT-B'
    """
    sid: str = story.get("id", "")
    # Split ID to find US/UT marker
    parts = sid.split("-")
    for i, part in enumerate(parts):
        if part in ("US", "UT") and i > 0:
            return "-".join(parts[:i])
    return ""


def _infer_sub_project(story: dict[str, Any]) -> str:
    """Infer sub-project from story dict.

    Uses explicit 'sub_project' field first, falls back to ID prefix
    (e.g., 'PROJECT-B-US-005' -> 'PROJECT-B').
    """
    if story.get("sub_project"):
        return str(story["sub_project"])
    return _infer_from_id(story)


def _find_cycle_from(
    story_id: str,
    stories_by_id: dict[str, dict[str, Any]],
    path: list[str],
    visited: set[str],
) -> list[str]:
    """DFS cycle detector. Returns cycle path if found, else []."""
    if story_id in path:
        cycle_start = path.index(story_id)
        return path[cycle_start:] + [story_id]
    if story_id in visited:
        return []
    story = stories_by_id.get(story_id)
    if not story:
        return []
    visited.add(story_id)
    new_path = path + [story_id]
    for dep_id in story.get("dependencies", []):
        result = _find_cycle_from(dep_id, stories_by_id, new_path, visited)
        if result:
            return result
    return []


def find_all_cycles(stories: list[dict[str, Any]]) -> list[list[str]]:
    """Find all cycles in the dependency graph.

    Returns list of cycle paths, e.g. [['US-001', 'US-002', 'US-001'], ...].
    Empty list if no cycles.
    """
    stories_by_id = {s["id"]: s for s in stories if isinstance(s, dict) and "id" in s}
    cycles: list[list[str]] = []
    visited_global: set[str] = set()

    for story_id in stories_by_id:
        if story_id not in visited_global:
            cycle = _find_cycle_from(story_id, stories_by_id, [], set())
            if cycle:
                # Deduplicate cycles (same cycle may be found from different starts)
                cycle_set = frozenset(cycle[:-1])  # Exclude the repeated final node
                if not any(frozenset(c[:-1]) == cycle_set for c in cycles):
                    cycles.append(cycle)
                visited_global.update(cycle[:-1])
            else:
                visited_global.add(story_id)

    return cycles


def find_orphans(stories: list[dict[str, Any]]) -> list[str]:
    """Find stories with missing dependencies (orphans).

    Returns list of missing story IDs that are referenced but don't exist.
    """
    stories_by_id = {s["id"]: s for s in stories if isinstance(s, dict) and "id" in s}
    missing: set[str] = set()

    for story in stories:
        if not isinstance(story, dict):
            continue
        for dep_id in story.get("dependencies", []):
            if dep_id not in stories_by_id:
                missing.add(dep_id)

    return sorted(missing)


def check_namespaces(stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate story ID namespace consistency.

    Returns {valid: bool, conflicts: [list of issues], namespaces: {namespace: [story_ids]}}.
    """
    namespaces: dict[str, set[str]] = {}
    conflicts: list[str] = []

    for story in stories:
        if not isinstance(story, dict):
            continue
        story_id = story.get("id", "")
        if not story_id:
            continue

        sub_project = _infer_sub_project(story)
        if sub_project not in namespaces:
            namespaces[sub_project] = set()
        namespaces[sub_project].add(story_id)

        # Check if story_id prefix (if present) matches explicitly set sub_project
        explicit_sub = story.get("sub_project")
        if explicit_sub:
            inferred = _infer_from_id(story)
            # Only flag conflict if ID has a project prefix that differs from explicit sub_project
            if inferred and inferred != explicit_sub:
                conflicts.append(
                    f"Story {story_id}: explicit sub_project='{explicit_sub}' "
                    f"conflicts with inferred prefix '{inferred}'"
                )

    return {
        "valid": len(conflicts) == 0,
        "conflicts": conflicts,
        "namespaces": {k: sorted(v) for k, v in namespaces.items()},
    }


def validate(prd: dict[str, Any], strict: bool = False) -> dict[str, Any]:
    """Validate entire federated prd.json.

    Args:
        prd: Full prd.json dict with userStories key.
        strict: If True, treat namespace conflicts as errors.

    Returns:
        {
            "valid": bool,
            "cycles": list[list[str]],
            "orphans": list[str],
            "namespaces": {namespace: [story_ids]},
            "namespace_valid": bool
        }
    """
    stories = prd.get("userStories", [])

    cycles = find_all_cycles(stories)
    orphans = find_orphans(stories)
    namespace_info = check_namespaces(stories)

    has_namespace_issues = not namespace_info["valid"] and strict

    return {
        "valid": len(cycles) == 0 and len(orphans) == 0 and not has_namespace_issues,
        "cycles": cycles,
        "orphans": orphans,
        "namespaces": namespace_info["namespaces"],
        "namespace_valid": namespace_info["valid"],
    }
