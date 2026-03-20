"""federated_merge_prd.py — Merge sub-project PRD files with namespace validation.

Combines multiple prd.json files from federated sub-projects into a single
master PRD. Detects duplicate story IDs across projects and preserves the
sub_project field on each story.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_sub_project_prd(project_dir: Path, project_name: str) -> dict[str, Any]:
    """Load a prd.json from a sub-project directory.

    Raises FileNotFoundError if prd.json doesn't exist in the directory.
    """
    prd_path = project_dir / "prd.json"
    if not prd_path.exists():
        msg = f"prd.json not found in sub-project '{project_name}' at {prd_path}"
        raise FileNotFoundError(msg)
    with open(prd_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        msg = f"prd.json in '{project_name}' is not a JSON object"
        raise ValueError(msg)
    return data


def merge_prds(
    project_dirs: dict[str, Path],
) -> tuple[dict[str, Any], list[str]]:
    """Merge multiple sub-project PRDs into one master PRD.

    Args:
        project_dirs: Mapping of project_name -> directory containing prd.json

    Returns:
        Tuple of (merged_prd, errors).
        If errors is non-empty, the merge failed due to duplicate IDs.
    """
    all_stories: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}  # story_id -> project_name
    duplicates: list[str] = []

    for project_name, project_dir in project_dirs.items():
        prd_data = load_sub_project_prd(project_dir, project_name)
        stories = prd_data.get("userStories", [])

        for story in stories:
            if not isinstance(story, dict):
                continue
            sid = story.get("id", "")
            if not sid:
                continue

            if sid in seen_ids:
                duplicates.append(f"Duplicate story ID '{sid}' in projects '{seen_ids[sid]}' and '{project_name}'")
            else:
                seen_ids[sid] = project_name

            # Set sub_project field
            story_copy = dict(story)
            story_copy["sub_project"] = project_name
            all_stories.append(story_copy)

    if duplicates:
        return {}, duplicates

    merged: dict[str, Any] = {
        "userStories": all_stories,
    }
    return merged, []


def run_federated_merge(
    project_names: list[str],
    output_path: Path,
    base_dir: Path | None = None,
) -> int:
    """CLI entry point for federated-merge-prd.

    Args:
        project_names: List of sub-project directory names
        output_path: Where to write the merged prd.json
        base_dir: Base directory containing sub-project directories (default: cwd)

    Returns:
        Exit code: 0 on success, 1 on duplicate IDs or errors
    """
    if base_dir is None:
        base_dir = Path.cwd()

    project_dirs: dict[str, Path] = {}
    for name in project_names:
        project_dir = base_dir / name
        if not project_dir.is_dir():
            print(f"Error: sub-project directory '{name}' not found at {project_dir}", file=sys.stderr)
            return 1
        project_dirs[name] = project_dir

    try:
        merged, errors = merge_prds(project_dirs)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if errors:
        print("Error: Duplicate story IDs detected:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")

    story_count = len(merged.get("userStories", []))
    print(f"Merged {story_count} stories from {len(project_names)} projects -> {output_path}")
    return 0
