"""CLI command: federation-health-check — Validate federated PRD structure.

Checks for:
- Unknown sub_project references (story references a sub_project that doesn't exist)
- Circular cross-project dependencies with cycle path reporting
- Story ID namespace matching sub_project field (e.g., PAYMENT-### for sub_project 'payment')
"""

import json
from pathlib import Path
from typing import Any


def _find_cycle_path(graph: dict[str, list[str]]) -> list[str] | None:
    """DFS to find a cycle. Returns cycle as [a, b, ..., a] or None."""
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> list[str] | None:
        if node in path_set:
            idx = path.index(node)
            return path[idx:] + [node]
        if node in visited:
            return None
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for neighbor in graph.get(node, []):
            result = dfs(neighbor)
            if result is not None:
                return result
        path.pop()
        path_set.discard(node)
        return None

    for node in list(graph.keys()):
        if node not in visited:
            result = dfs(node)
            if result is not None:
                return result
    return None


def _extract_referenced_projects(prd_dict: dict[str, Any]) -> set[str]:
    """Extract all sub_project values referenced in stories."""
    projects: set[str] = set()
    for story in prd_dict.get("userStories", []):
        if isinstance(story, dict) and "sub_project" in story:
            sub_proj = story.get("sub_project")
            if isinstance(sub_proj, str):
                projects.add(sub_proj)
    return projects


def _extract_configured_projects(prd_dict: dict[str, Any]) -> set[str]:
    """Extract configured sub_project namespaces from prd.json."""
    projects: set[str] = set()
    for sp in prd_dict.get("subProjects", []):
        if isinstance(sp, dict):
            namespace = sp.get("namespace")
            if namespace:
                projects.add(namespace)
        elif isinstance(sp, str):
            projects.add(sp)
    return projects


def check_unknown_sub_projects(
    prd_dict: dict[str, Any],
    prd_path: Path,
) -> list[str]:
    """Detect stories referencing non-existent sub_projects.

    Args:
        prd_dict: Parsed prd.json
        prd_path: Path to prd.json (for error messages)

    Returns:
        List of error strings (empty if all sub_project references are valid)
    """
    errors: list[str] = []

    # Get all unique sub_project values referenced
    referenced_projects = _extract_referenced_projects(prd_dict)

    # If no federated projects (default only), pass
    if referenced_projects == {"default"} or not referenced_projects:
        return errors

    # Get configured sub_projects from prd.json (if present)
    configured_projects = _extract_configured_projects(prd_dict)

    # Check each story's sub_project references
    for story in prd_dict.get("userStories", []):
        if not isinstance(story, dict):
            continue
        story_id = story.get("id", "<unknown>")
        sub_proj = story.get("sub_project")

        if sub_proj and isinstance(sub_proj, str) and sub_proj != "default":
            # If we have configured projects, verify the reference is valid
            if configured_projects and sub_proj not in configured_projects:
                valid_list = ", ".join(sorted(configured_projects))
                errors.append(
                    f"Story {story_id} references unknown sub_project: {sub_proj}. "
                    f"Valid sub_projects are: {valid_list}. "
                    f"Fix: Update story's sub_project field in {prd_path} or add '{sub_proj}' to subProjects array."
                )

    return errors


def detect_circular_dependencies(
    prd_dict: dict[str, Any],
) -> list[str]:
    """Detect circular cross-project story dependencies.

    Args:
        prd_dict: Parsed prd.json

    Returns:
        List of error strings with cycle paths (empty if no cycles)
    """
    errors: list[str] = []

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

    # Find cycle using DFS
    cycle = _find_cycle_path(graph)
    if cycle is not None:
        cycle_str = " → ".join(cycle)
        errors.append(f"Circular dependency detected: {cycle_str}")

    return errors


def validate_id_namespace(
    prd_dict: dict[str, Any],
    prd_path: Path,
) -> list[str]:
    """Validate story ID prefix matches sub_project field.

    For example, story with sub_project: 'payment' should have ID PAYMENT-###,
    not US-### or any other prefix.

    Args:
        prd_dict: Parsed prd.json
        prd_path: Path to prd.json (for error messages)

    Returns:
        List of error strings (empty if all namespaces are valid)
    """
    errors: list[str] = []

    for story in prd_dict.get("userStories", []):
        if not isinstance(story, dict):
            continue

        story_id = story.get("id", "")
        sub_project = story.get("sub_project")

        # Only validate if sub_project is specified and non-default
        if not sub_project or sub_project == "default":
            continue

        if not isinstance(story_id, str):
            continue

        # Extract prefix from story ID (everything before the dash)
        if "-" in story_id:
            id_prefix = story_id.split("-")[0]
        else:
            id_prefix = story_id

        # Expected prefix is sub_project in UPPERCASE
        expected_prefix = str(sub_project).upper()

        # Validate match
        if id_prefix != expected_prefix:
            errors.append(
                f"Story {story_id} has sub_project '{sub_project}' "
                f"but ID prefix '{id_prefix}' does not match (expected '{expected_prefix}'). "
                f"Fix: Rename story ID to {expected_prefix}-### or change sub_project field in {prd_path}."
            )

    return errors


def run_health_check(
    prd_dict: dict[str, Any],
    prd_path: Path,
) -> dict[str, Any]:
    """Run comprehensive federation health check.

    Args:
        prd_dict: Parsed prd.json
        prd_path: Path to prd.json file

    Returns:
        {"valid": bool, "errors": list[str]}
    """
    errors: list[str] = []

    # Check 1: Unknown sub_project references
    errors.extend(check_unknown_sub_projects(prd_dict, prd_path))

    # Check 2: Circular dependencies
    errors.extend(detect_circular_dependencies(prd_dict))

    # Check 3: ID namespace validation
    errors.extend(validate_id_namespace(prd_dict, prd_path))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def federation_health_check(prd_path: Path) -> dict[str, Any]:
    """Full federation health check from file path.

    Args:
        prd_path: Path to prd.json file

    Returns:
        Report dict with keys: valid (bool), errors (list)
    """
    if not prd_path.exists():
        return {
            "valid": False,
            "errors": [f"File not found: {prd_path}"],
        }

    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            prd_dict = json.load(f)
    except PermissionError:
        return {
            "valid": False,
            "errors": [f"Permission denied: cannot read {prd_path}"],
        }
    except OSError as e:
        return {
            "valid": False,
            "errors": [f"Cannot read file: {e}"],
        }
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "errors": [f"Invalid JSON: {e}"],
        }

    return run_health_check(prd_dict, prd_path)
