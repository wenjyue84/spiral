"""merge_dry_run.py — File-collision and dependency-order detection.

Reads _validated_stories.json and detects:
  - File collisions: 2+ stories editing the same file
  - Ordering violations: dependencies on missing story IDs in prd.json

Story: US-1045
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    """Load JSON file safely; return empty dict if file missing."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _extract_files_from_technical_notes(technical_notes: list[str]) -> list[str]:
    """Extract file paths from 'File to edit:' and 'File to create:' lines."""
    files = []
    for note in technical_notes:
        # Match "File to edit: <path>" or "File to create: <path>"
        match = re.search(r"File to (?:edit|create):\s*(\S+)", note)
        if match:
            files.append(match.group(1))
    return files


def run_dry_run(validated_path: str) -> dict[str, Any]:
    """Run dry-run conflict detection on _validated_stories.json.

    Args:
        validated_path: Path to _validated_stories.json

    Returns:
        Dict with keys:
          - conflict_detected: bool (True if any collisions or violations)
          - file_collisions: list of file paths edited by 2+ stories
          - ordering_violations: list of missing dependency IDs
    """
    # Load validated stories
    validated_data = _load_json(validated_path)
    stories = validated_data.get("stories", [])

    # Load prd.json to check dependencies
    prd_data = _load_json("prd.json")
    prd_stories = prd_data.get("userStories", [])
    prd_story_ids = {s.get("id") for s in prd_stories}

    # ─ Detect file collisions ─────────────────────────────────────────────────
    file_to_stories: dict[str, list[str]] = {}
    for story in stories:
        story_id = story.get("id") or ""
        technical_notes = story.get("technicalNotes", [])
        files = _extract_files_from_technical_notes(technical_notes)
        for file_path in files:
            if file_path not in file_to_stories:
                file_to_stories[file_path] = []
            file_to_stories[file_path].append(story_id)

    file_collisions = [f for f, story_ids in file_to_stories.items() if len(story_ids) > 1]

    # ─ Detect ordering violations ────────────────────────────────────────────
    ordering_violations: list[str] = []
    for story in stories:
        dependencies = story.get("dependencies", [])
        for dep_id in dependencies:
            if dep_id and dep_id not in prd_story_ids:
                ordering_violations.append(dep_id)

    # Remove duplicates, keep sorted
    file_collisions = sorted(set(file_collisions))
    ordering_violations = sorted(set(ordering_violations))

    conflict_detected = bool(file_collisions or ordering_violations)

    return {
        "conflict_detected": conflict_detected,
        "file_collisions": file_collisions,
        "ordering_violations": ordering_violations,
    }
