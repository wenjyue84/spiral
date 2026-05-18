#!/usr/bin/env python3
"""
story_renamer.py -- Safely rename story IDs across prd.json, results.tsv, and dependency refs.

Ensures atomic writes, collision detection, and full history preservation.

Usage:
  python lib/story_renamer.py <old_id> <new_id> [--prd prd.json] [--results results.tsv]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from core.spiral_io import atomic_write_json


def validate_rename(
    old_id: str, new_id: str, prd_path: str
) -> tuple[bool, str]:
    """
    Validate that rename is safe.

    Returns (is_valid, error_message).
    """
    if not os.path.isfile(prd_path):
        return False, f"PRD file not found: {prd_path}"

    with open(prd_path, "r", encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    story_ids = {s.get("id") for s in stories}

    # Check if old_id exists
    if old_id not in story_ids:
        return False, f"Story {old_id} not found in {prd_path}"

    # Check if new_id already exists
    if new_id in story_ids:
        return False, f"Story {new_id} already exists in {prd_path}"

    return True, ""


def update_dependencies(stories: list[dict[str, object]], old_id: str, new_id: str) -> None:
    """Update all dependency references from old_id to new_id in-place."""
    for story in stories:
        deps = story.get("dependencies", [])
        if isinstance(deps, list):
            for i, dep_id in enumerate(deps):
                if dep_id == old_id:
                    deps[i] = new_id


def update_results_tsv(results_path: str, old_id: str, new_id: str) -> None:
    """Rewrite results.tsv, replacing old_id with new_id in story_id column.

    Uses atomic write pattern: read all lines, modify, write to temp, replace.
    """
    if not os.path.isfile(results_path):
        return  # No results file yet — nothing to update

    with open(results_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        return

    # Parse header
    header_parts = lines[0].rstrip("\n").split("\t")
    if "story_id" not in header_parts:
        return  # No story_id column — nothing to update

    story_id_idx = header_parts.index("story_id")

    # Rewrite lines
    updated_lines = [lines[0]]  # Keep header unchanged
    for line in lines[1:]:
        parts = line.rstrip("\n").split("\t")
        if len(parts) > story_id_idx:
            if parts[story_id_idx] == old_id:
                parts[story_id_idx] = new_id
        updated_lines.append("\t".join(parts) + "\n")

    # Atomic write
    parent = os.path.dirname(os.path.abspath(results_path)) or "."
    os.makedirs(parent, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(updated_lines)
        os.replace(tmp, results_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def rename_story(
    old_id: str, new_id: str, prd_path: str, results_path: str
) -> None:
    """
    Rename a story from old_id to new_id.

    Updates:
    - prd.json: story.id and all dependency references
    - results.tsv: story_id column

    Raises ValueError if validation fails or if rename is unsafe.
    """
    # Validate
    is_valid, error_msg = validate_rename(old_id, new_id, prd_path)
    if not is_valid:
        raise ValueError(error_msg)

    # Load and update prd.json
    with open(prd_path, "r", encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])

    # Update story ID
    for story in stories:
        if story.get("id") == old_id:
            story["id"] = new_id

    # Update all dependency references
    update_dependencies(stories, old_id, new_id)

    # Atomic write prd.json
    atomic_write_json(prd_path, prd)

    # Update results.tsv
    update_results_tsv(results_path, old_id, new_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename a story ID across prd.json, results.tsv, and dependencies"
    )
    parser.add_argument("old_id", help="Old story ID (e.g., US-001)")
    parser.add_argument("new_id", help="New story ID (e.g., US-999)")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    args = parser.parse_args()

    try:
        rename_story(args.old_id, args.new_id, args.prd, args.results)
        print(f"[rename-story] Successfully renamed {args.old_id} → {args.new_id}")
    except ValueError as e:
        print(f"[rename-story] ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
