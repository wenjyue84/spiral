#!/usr/bin/env python3
"""
rollback_story.py — Remove lowest-priority pending story from prd.json.

Implements story rollback for Phase I budget gate: when cost would exceed
ceiling, removes the lowest-priority pending story and re-estimates.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from core.spiral_io import atomic_write_json


PRIORITY_ORDER: Dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def find_lowest_priority_pending_story(prd_dict: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    """
    Find the lowest-priority pending story in prd.json.

    Returns:
        tuple of (index_in_userstories, story_dict) or None if no pending stories
    """
    pending_stories = [
        (i, s)
        for i, s in enumerate(prd_dict.get("userStories", []))
        if s.get("passes") != True
    ]

    if not pending_stories:
        return None

    # Sort by priority (critical > high > medium > low), then by id (for determinism)
    def priority_key(item: Tuple[int, Dict[str, Any]]) -> Tuple[int, str]:
        _, story = item
        priority = story.get("priority", "medium").lower()
        priority_val = PRIORITY_ORDER.get(priority, 999)
        story_id = story.get("id", "")
        return (priority_val, story_id)

    # Find the one with highest priority_val (lowest priority)
    lowest = max(pending_stories, key=priority_key)
    return lowest


def rollback_story(prd_file: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    Remove the lowest-priority pending story from prd.json.

    Args:
        prd_file: path to prd.json
        dry_run: if True, report what would be rolled back without modifying file

    Returns:
        dict with keys:
          - success: bool, whether rollback succeeded
          - removed_story_id: str or None, ID of story that was removed
          - removed_story_title: str or None, title of removed story
          - remaining_pending: int, count of pending stories after rollback
          - error: str or None, error message if failed
    """
    if not prd_file.exists():
        return {
            "success": False,
            "removed_story_id": None,
            "removed_story_title": None,
            "remaining_pending": 0,
            "error": f"prd.json not found: {prd_file}",
        }

    try:
        with open(prd_file, "r", encoding="utf-8") as f:
            prd_dict = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "removed_story_id": None,
            "removed_story_title": None,
            "remaining_pending": 0,
            "error": f"Invalid JSON in prd.json: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "removed_story_id": None,
            "removed_story_title": None,
            "remaining_pending": 0,
            "error": f"Error reading prd.json: {e}",
        }

    result = find_lowest_priority_pending_story(prd_dict)
    if not result:
        return {
            "success": False,
            "removed_story_id": None,
            "removed_story_title": None,
            "remaining_pending": 0,
            "error": "No pending stories to rollback",
        }

    idx, story = result
    removed_id = story.get("id", "unknown")
    removed_title = story.get("title", "")

    if dry_run:
        remaining = sum(1 for s in prd_dict.get("userStories", []) if s.get("passes") != True) - 1
        return {
            "success": True,
            "removed_story_id": removed_id,
            "removed_story_title": removed_title,
            "remaining_pending": remaining,
            "error": None,
            "dry_run": True,
        }

    # Remove the story from the list
    prd_dict["userStories"].pop(idx)

    # Write updated PRD back to file atomically
    try:
        atomic_write_json(str(prd_file), prd_dict)
    except Exception as e:
        return {
            "success": False,
            "removed_story_id": removed_id,
            "removed_story_title": removed_title,
            "remaining_pending": 0,
            "error": f"Failed to write prd.json: {e}",
        }

    remaining = sum(1 for s in prd_dict.get("userStories", []) if s.get("passes") != True)
    return {
        "success": True,
        "removed_story_id": removed_id,
        "removed_story_title": removed_title,
        "remaining_pending": remaining,
        "error": None,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rollback lowest-priority pending story from prd.json")
    parser.add_argument("--prd", type=Path, default="prd.json", help="Path to prd.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be rolled back without modifying",
    )
    args = parser.parse_args()

    result = rollback_story(args.prd, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))

    if not result["success"]:
        sys.exit(1)
