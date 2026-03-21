"""lib/trace_dependencies.py — Federated cross-project dependency resolver (US-675).

Recursively resolves a story's full dependency chain across federated sub-projects.
Detects circular dependencies, displays file paths, and marks sub-project boundaries.

Usage (Python API):
    from trace_dependencies import trace_deps, format_tree, to_json_output

    stories_by_id = {s["id"]: s for s in prd["userStories"]}
    result = trace_deps("US-001", stories_by_id)
    print(format_tree(result))
    print(json.dumps(to_json_output(result), indent=2))

CLI usage (via main.py):
    spiral trace-dependencies US-001
    spiral trace-dependencies US-001 --json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DependencyNode:
    """A node in the resolved dependency tree."""

    story_id: str
    sub_project: str
    depth: int
    files: list[str]
    children: list[DependencyNode] = field(default_factory=list)
    has_cycle: bool = False
    cycle_path: list[str] = field(default_factory=list)


def _infer_sub_project(story: dict[str, Any]) -> str:
    """Infer sub-project label from story dict.

    Checks explicit 'sub_project' or '_project' fields first, then infers
    from the story ID prefix (e.g., 'PROJECT-B-US-005' -> 'PROJECT-B').
    """
    if story.get("sub_project"):
        return str(story["sub_project"])
    if story.get("_project"):
        return str(story["_project"])
    sid: str = story.get("id", "")
    # IDs like PROJECT-B-US-005: prefix before last hyphen-word-hyphendigits
    parts = sid.split("-")
    # If the ID has a US/UT marker, prefix is everything before it
    for i, part in enumerate(parts):
        if part in ("US", "UT") and i > 0:
            return "-".join(parts[:i])
    return ""


def _find_cycle(
    story_id: str,
    stories_by_id: dict[str, dict[str, Any]],
    path: list[str],
    visited: set[str],
) -> list[str]:
    """DFS cycle detector. Returns cycle path if a cycle is found, else []."""
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
        result = _find_cycle(dep_id, stories_by_id, new_path, visited)
        if result:
            return result
    return []


def detect_cycle(
    story_id: str,
    stories_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    """Return cycle path like ['US-001', 'US-002', 'US-001'] or [] if no cycle."""
    return _find_cycle(story_id, stories_by_id, [], set())


def trace_deps(
    story_id: str,
    stories_by_id: dict[str, dict[str, Any]],
    depth: int = 0,
    _ancestors: frozenset[str] | None = None,
) -> DependencyNode:
    """Recursively resolve a story's full dependency tree.

    Handles federated sub-projects (PROJECT-B-US-005 style IDs).
    Circular dependencies are detected and marked on the node without recursing further.

    Args:
        story_id: The story ID to resolve.
        stories_by_id: Mapping of story_id -> story dict from prd.json.
        depth: Current recursion depth (internal).
        _ancestors: Set of ancestor story IDs to detect cycles (internal).

    Returns:
        DependencyNode with fully resolved children.
    """
    if _ancestors is None:
        _ancestors = frozenset()

    story = stories_by_id.get(story_id, {})
    sub_project = _infer_sub_project(story) if story else ""
    files: list[str] = story.get("filesTouch", story.get("files", []))

    node = DependencyNode(
        story_id=story_id,
        sub_project=sub_project,
        depth=depth,
        files=list(files) if isinstance(files, list) else [],
    )

    if story_id in _ancestors:
        # Cycle detected — mark and stop recursion
        cycle_list = list(_ancestors) + [story_id]
        # Trim to the shortest cycle starting at story_id
        if story_id in cycle_list[:-1]:
            start = cycle_list.index(story_id)
            cycle_list = cycle_list[start:]
        node.has_cycle = True
        node.cycle_path = cycle_list
        return node

    if not story:
        return node

    new_ancestors = _ancestors | {story_id}
    for dep_id in story.get("dependencies", []):
        child = trace_deps(dep_id, stories_by_id, depth + 1, new_ancestors)
        node.children.append(child)
        if child.has_cycle:
            node.has_cycle = True
            node.cycle_path = child.cycle_path

    return node


def format_tree(node: DependencyNode, prefix: str = "", is_last: bool = True) -> str:
    """Render the dependency tree as a human-readable ASCII tree.

    Example output:
        US-001
        ├── [project-b] US-005 (src/auth.py)
        │   └── [project-c] US-008
        └── US-003
    """
    connector = "└── " if is_last else "├── "
    sub_tag = f"[{node.sub_project}] " if node.sub_project else ""
    files_tag = f" ({', '.join(node.files)})" if node.files else ""
    cycle_tag = " *** CYCLE ***" if node.has_cycle else ""

    if node.depth == 0:
        line = f"{node.story_id}{files_tag}{cycle_tag}\n"
    else:
        line = f"{prefix}{connector}{sub_tag}{node.story_id}{files_tag}{cycle_tag}\n"

    child_prefix = prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(node.children):
        is_child_last = i == len(node.children) - 1
        line += format_tree(child, child_prefix, is_child_last)

    return line


def _collect_deps(
    node: DependencyNode,
) -> list[dict[str, Any]]:
    """Collect all dependency nodes into a flat list for JSON output."""
    result: list[dict[str, Any]] = []
    for child in node.children:
        entry: dict[str, Any] = {
            "story_id": child.story_id,
            "sub_project": child.sub_project,
            "depth": child.depth,
            "files": child.files,
        }
        if child.has_cycle:
            entry["cycle"] = True
            entry["cycle_path"] = child.cycle_path
        result.append(entry)
        result.extend(_collect_deps(child))
    return result


def to_json_output(node: DependencyNode) -> dict[str, Any]:
    """Convert a DependencyNode tree to JSON-serialisable dict.

    Schema matches acceptance criteria:
    {
        "story_id": "US-001",
        "dependencies": [
            {"story_id": "PROJECT-B-US-005", "sub_project": "project-b",
             "depth": 1, "files": ["src/auth.py"]},
        ],
        "has_cycle": false
    }
    If a cycle exists, also includes "cycle_path".
    """
    output: dict[str, Any] = {
        "story_id": node.story_id,
        "dependencies": _collect_deps(node),
        "has_cycle": node.has_cycle,
    }
    if node.has_cycle:
        output["cycle_path"] = node.cycle_path
    return output
