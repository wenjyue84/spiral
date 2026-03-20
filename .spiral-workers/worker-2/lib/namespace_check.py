"""Namespace validation for federated prd.json with sub-project story namespacing."""

import json
from pathlib import Path
from typing import Any


def load_federated_slices(prd_path: Path) -> dict[str, Any]:
    """Load federated prd.json and group stories by sub-project prefix.

    Args:
        prd_path: Path to the main prd.json file

    Returns:
        Dict mapping sub-project name to list of story IDs in that namespace

    Raises:
        FileNotFoundError: If prd.json doesn't exist
        json.JSONDecodeError: If prd.json is malformed
    """
    if not prd_path.exists():
        raise FileNotFoundError(f"prd.json not found at {prd_path}")

    with open(prd_path, "r", encoding="utf-8") as f:
        prd_dict = json.load(f)

    # Group stories by namespace (prefix before /)
    slices: dict[str, list[str]] = {}

    for story in prd_dict.get("userStories", []):
        story_id = story.get("id", "")

        # Check if story_id has namespace prefix (format: namespace/US-NNN)
        if "/" in story_id:
            namespace, _ = story_id.split("/", 1)
            if namespace not in slices:
                slices[namespace] = []
            slices[namespace].append(story_id)

    return slices


def validate_namespaces(prd_dict: dict[str, Any]) -> dict[str, Any]:
    """Validate story ID namespacing rules in a prd.json dict.

    Validation rules:
    1. All stories in a sub-project namespace must have the <namespace>/<id> format
    2. No story can have mismatched namespace (e.g., <bad-namespace>/US-123 in sub-project <good-namespace>)
    3. Stories without namespace (e.g., US-123) are allowed in the main project

    Args:
        prd_dict: Parsed prd.json dictionary

    Returns:
        {
            "pass": bool,
            "sub_projects": {
                "<namespace>": {
                    "pass": bool,
                    "violations": [...],
                    "story_count": int
                }
            }
        }
    """
    violations: list[dict[str, Any]] = []
    sub_projects: dict[str, dict[str, Any]] = {}

    # Get stories grouped by namespace
    stories = prd_dict.get("userStories", [])

    # Track which namespaces are mentioned in subProjects array
    configured_namespaces = set()
    sub_projects_array = prd_dict.get("subProjects", [])
    for sp in sub_projects_array:
        if isinstance(sp, dict):
            namespace = sp.get("namespace")
            if namespace:
                configured_namespaces.add(namespace)
        elif isinstance(sp, str):
            # Simple string namespace
            configured_namespaces.add(sp)

    # Group stories by detected namespace
    stories_by_namespace: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        story_id = story.get("id", "")
        if "/" in story_id:
            namespace, _ = story_id.split("/", 1)
            if namespace not in stories_by_namespace:
                stories_by_namespace[namespace] = []
            stories_by_namespace[namespace].append(story)

    # Validate each namespace
    for namespace, ns_stories in stories_by_namespace.items():
        ns_violations = []

        # Check that all stories in this namespace have the correct prefix
        for story in ns_stories:
            story_id = story.get("id", "")
            if not story_id.startswith(f"{namespace}/"):
                ns_violations.append(
                    {
                        "type": "mismatched_namespace",
                        "story_id": story_id,
                        "expected_prefix": f"{namespace}/",
                        "message": f"Story {story_id} has incorrect namespace prefix (expected {namespace}/)",
                    }
                )

        ns_pass = len(ns_violations) == 0
        sub_projects[namespace] = {"pass": ns_pass, "violations": ns_violations, "story_count": len(ns_stories)}

        if not ns_pass:
            violations.extend([{"namespace": namespace, **v} for v in ns_violations])

    # Check for stories in main namespace (no /)
    main_stories = [s for s in stories if "/" not in s.get("id", "")]
    if main_stories:
        sub_projects["main"] = {"pass": True, "violations": [], "story_count": len(main_stories)}

    return {"pass": len(violations) == 0, "violations": violations, "sub_projects": sub_projects}


def check_namespaces(prd_path: Path) -> dict[str, Any]:
    """Full namespace check: load prd.json and validate.

    Args:
        prd_path: Path to prd.json

    Returns:
        Validation result dict with pass/fail status
    """
    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            prd_dict = json.load(f)
    except FileNotFoundError:
        return {"pass": False, "error": f"prd.json not found at {prd_path}", "sub_projects": {}}
    except json.JSONDecodeError as e:
        return {"pass": False, "error": f"Invalid JSON in prd.json: {e}", "sub_projects": {}}

    return validate_namespaces(prd_dict)
