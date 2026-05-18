"""federation_validator.py — Detect cross-subproject story ID namespace collisions.

Validates that federated sub-projects use consistent story ID namespace prefixes
(e.g., PAYMENTS-100, INVENTORY-50, US-100). Detects collisions where the same
story_id appears in multiple sub-projects with different or mismatched prefixes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ValidationResult:
    """Result of federation namespace validation."""

    collisions: list[dict[str, Any]]
    namespace_map: dict[str, dict[str, str]]  # story_id -> {project: prefix}
    suggestions: list[str]
    is_valid: bool


def extract_namespace_prefix(story_id: str) -> str:
    """Extract namespace prefix from a story ID.

    Examples:
        "US-100" -> "US"
        "PAYMENTS-50" -> "PAYMENTS"
        "US-100-v2" -> "US"
    """
    if not story_id or "-" not in story_id:
        return ""
    parts = story_id.split("-")
    return parts[0]


def build_story_id_map(
    prd_dict: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Build a map of story_id -> {project_name: namespace_prefix}.

    Args:
        prd_dict: The main PRD (possibly with sub_project fields on stories)

    Returns:
        Map like: {
            "US-100": {"main": "US", "payments": "PAYMENTS"},
            "US-50": {"main": "US"}
        }
    """
    story_id_map: dict[str, dict[str, str]] = {}

    for story in prd_dict.get("userStories", []):
        if not isinstance(story, dict):
            continue
        story_id = story.get("id", "")
        if not story_id:
            continue

        prefix = extract_namespace_prefix(story_id)
        project = story.get("sub_project", "main")

        if story_id not in story_id_map:
            story_id_map[story_id] = {}
        story_id_map[story_id][project] = prefix

    return story_id_map


def detect_collisions(
    namespace_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Detect namespace collisions in the namespace map.

    A collision occurs when:
    - The same story_id appears in multiple projects
    - The namespace prefixes differ across projects

    Args:
        namespace_map: Map from build_story_id_map

    Returns:
        List of collision dicts like:
        {
            "story_id": "US-100",
            "projects": {"main": "US", "payments": "PAYMENTS"},
            "conflict": True
        }
    """
    collisions: list[dict[str, Any]] = []

    for story_id, projects in namespace_map.items():
        if len(projects) <= 1:
            continue

        # Check if prefixes are consistent
        prefixes = set(projects.values())
        if len(prefixes) > 1:
            collisions.append(
                {
                    "story_id": story_id,
                    "projects": dict(projects),
                    "conflict": True,
                    "prefixes": list(prefixes),
                }
            )

    return collisions


def suggest_namespace_renames(
    collisions: list[dict[str, Any]],
) -> list[str]:
    """Generate suggestions for fixing namespace collisions.

    Args:
        collisions: List from detect_collisions

    Returns:
        List of suggestion strings like:
        "Rename US-100 to PAYMENTS-100 in payments project"
    """
    suggestions: list[str] = []

    for collision in collisions:
        story_id = collision["story_id"]
        projects = collision["projects"]
        prefixes = collision.get("prefixes", [])

        if len(prefixes) < 2:
            continue

        # Suggest keeping the main project's prefix, renaming others
        main_prefix = projects.get("main", list(prefixes)[0])

        for project, current_prefix in projects.items():
            if project == "main" or current_prefix == main_prefix:
                continue
            base_id_part = story_id[len(current_prefix) + 1 :]  # Skip prefix + dash
            new_id = f"{main_prefix}-{base_id_part}"
            suggestions.append(
                f"Rename {story_id} to {new_id} in {project} project"
            )

    return suggestions


def validate_federation_namespaces(
    prd_dict: dict[str, Any],
) -> ValidationResult:
    """Validate story ID namespace consistency across federated sub-projects.

    Args:
        prd_dict: The main PRD with stories (may have sub_project fields)

    Returns:
        ValidationResult with collisions, namespace_map, suggestions, is_valid
    """
    namespace_map = build_story_id_map(prd_dict)
    collisions = detect_collisions(namespace_map)
    suggestions = suggest_namespace_renames(collisions)
    is_valid = len(collisions) == 0

    return ValidationResult(
        collisions=collisions,
        namespace_map=namespace_map,
        suggestions=suggestions,
        is_valid=is_valid,
    )


def main() -> int:
    """CLI entry point for federation validation."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python federation_validator.py <prd.json>", file=sys.stderr)
        return 1

    prd_file = Path(sys.argv[1])
    if not prd_file.exists():
        print(f"Error: {prd_file} not found", file=sys.stderr)
        return 1

    with open(prd_file, encoding="utf-8") as f:
        prd_dict = json.load(f)

    result = validate_federation_namespaces(prd_dict)

    if result.is_valid:
        print("✓ No namespace collisions detected")
        return 0

    print(f"✗ Found {len(result.collisions)} namespace collision(s):")
    for collision in result.collisions:
        story_id = collision["story_id"]
        projects = collision["projects"]
        print(f"  {story_id}: {projects}")

    if result.suggestions:
        print("\nSuggestions:")
        for suggestion in result.suggestions:
            print(f"  • {suggestion}")

    return 1


if __name__ == "__main__":
    exit(main())
