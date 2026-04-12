"""Validate story ID namespace prefixes match sub-project folder names.

Scans repos/ directory structure and enforces that story IDs in each
sub-project folder match the folder's prefix. E.g., repos/makan/
requires story IDs to start with MAKAN-.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def get_story_line_number(prd_path: Path, story_id: str) -> int:
    """Find the line number of a story ID in a prd.json file.

    Args:
        prd_path: Path to prd.json file.
        story_id: Story ID to find.

    Returns:
        Line number (1-indexed) where "id": "story_id" appears,
        or -1 if not found.
    """
    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                # Look for the story ID in the line
                if f'"{story_id}"' in line or f"'{story_id}'" in line:
                    # Double-check this is the actual story ID field
                    if '"id"' in line:
                        return line_num
    except (IOError, OSError):
        pass
    return -1


def infer_prefix_from_folder(folder_path: Path) -> str:
    """Infer namespace prefix from folder name.

    Args:
        folder_path: Path to sub-project folder (e.g., Path('repos/makan')).

    Returns:
        Uppercase prefix (e.g., 'MAKAN' from 'makan').
    """
    folder_name = folder_path.name.strip()
    # Convert folder name to uppercase prefix
    # Replace hyphens with underscores if needed, but mostly just uppercase
    return folder_name.upper()


def validate_story_id_prefix(story_id: str, expected_prefix: str) -> bool:
    """Check if story ID starts with expected prefix.

    Args:
        story_id: The story ID (e.g., 'MAKAN-100' or 'US-100').
        expected_prefix: Expected prefix (e.g., 'MAKAN').

    Returns:
        True if story_id starts with expected_prefix + '-',
        False otherwise.
    """
    return story_id.startswith(f"{expected_prefix}-")


def validate_namespace_prefix(
    repos_path: Path | str = "repos",
) -> dict[str, Any]:
    """Validate story ID prefixes across all sub-projects.

    Scans repos/ directory for sub-project folders, loads each prd.json,
    and validates that story IDs match the folder prefix.

    Args:
        repos_path: Path to repos directory (default: 'repos').

    Returns:
        Dict with:
        - valid: bool (True if all pass)
        - errors: list[dict] with 'file', 'story_id', 'expected', 'got', 'line'
        - total_stories: int (total stories checked)
        - passed_count: int (stories matching prefix)
        - failed_count: int (stories not matching prefix)
    """
    repos_path = Path(repos_path)
    errors: list[dict[str, Any]] = []
    total_stories = 0
    passed_count = 0
    failed_count = 0

    # Check if repos directory exists
    if not repos_path.exists():
        return {
            "valid": True,
            "errors": [],
            "total_stories": 0,
            "passed_count": 0,
            "failed_count": 0,
            "message": f"repos/ directory not found at {repos_path} (optional for single-project)",
        }

    # Scan each sub-project folder
    for sub_project_path in sorted(repos_path.iterdir()):
        if not sub_project_path.is_dir():
            continue

        # Skip hidden directories and system directories
        if sub_project_path.name.startswith("."):
            continue

        prd_json_path = sub_project_path / "prd.json"
        if not prd_json_path.exists():
            # Skip folders without prd.json
            continue

        # Infer expected prefix from folder name
        expected_prefix = infer_prefix_from_folder(sub_project_path)

        # Load and validate prd.json
        try:
            with open(prd_json_path, "r", encoding="utf-8") as f:
                prd_data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            errors.append(
                {
                    "file": str(prd_json_path),
                    "error": f"Failed to parse prd.json: {e}",
                    "line": -1,
                }
            )
            continue

        # Validate each story in this sub-project
        stories = prd_data.get("userStories", [])
        for story in stories:
            if not isinstance(story, dict):
                continue

            story_id = story.get("id", "")
            if not story_id:
                continue

            total_stories += 1

            # Check if story ID matches expected prefix
            if validate_story_id_prefix(story_id, expected_prefix):
                passed_count += 1
            else:
                failed_count += 1
                line_num = get_story_line_number(prd_json_path, story_id)
                errors.append(
                    {
                        "file": str(prd_json_path),
                        "story_id": story_id,
                        "expected": f"{expected_prefix}-*",
                        "got": story_id,
                        "line": line_num,
                        "remediation": f"Rename story ID to start with '{expected_prefix}-' "
                        f"(e.g., '{expected_prefix}-001')",
                    }
                )

    return {
        "valid": failed_count == 0,
        "errors": errors,
        "total_stories": total_stories,
        "passed_count": passed_count,
        "failed_count": failed_count,
    }
