#!/usr/bin/env python3
"""
lib/impl/partial_victory.py — Phase I: Partial Victory Commit (US-787)

When a story fails overall but some acceptance criteria are met:
1. Identify which ACs passed vs. failed
2. Commit partial implementation with _partial: true flag
3. Decompose failing ACs into sub-stories with parent ID in dependencies
4. Log attribution: "US-XXX: 2/3 ACs passed, committing partial. Decomposing AC-3 into US-YYY"

Usage:
  python lib/impl/partial_victory.py --story-id US-XXX \
    --ac-report .spiral/ac_reports/US-XXX.json \
    --prd prd.json --model sonnet

Input AC Report JSON:
  {
    "story_id": "US-XXX",
    "ac_evaluation": [
      {"index": 0, "text": "AC 1", "passed": true},
      {"index": 1, "text": "AC 2", "passed": false},
      {"index": 2, "text": "AC 3", "passed": false}
    ]
  }

Output: Updated prd.json with:
  - _partial: true on parent story
  - New sub-stories created for failing ACs with _decomposedFrom parent_id
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")


def parse_ac_report(ac_report_path: str) -> dict[str, Any]:
    """
    Parse AC evaluation report from JSON file.
    Returns: {"story_id": "US-XXX", "ac_evaluation": [{"index": 0, "text": "...", "passed": bool}]}
    """
    if not Path(ac_report_path).exists():
        return {}

    try:
        with open(ac_report_path, encoding="utf-8") as f:
            data: Any = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def has_passing_acs(ac_evaluation: list[dict[str, Any]]) -> bool:
    """Check if at least one AC passed."""
    return any(ac.get("passed", False) for ac in ac_evaluation)


def count_passing_acs(ac_evaluation: list[dict[str, Any]]) -> int:
    """Count how many ACs passed."""
    return sum(1 for ac in ac_evaluation if ac.get("passed", False))


def get_failing_ac_indices(
    ac_evaluation: list[dict[str, Any]],
) -> list[int]:
    """Return list of indices for ACs that failed."""
    return [i for i, ac in enumerate(ac_evaluation) if not ac.get("passed", False)]


def find_next_id(stories: list[dict[str, Any]]) -> int:
    """Scan all PREFIX-NNN ids, return max+1. Handles gaps safely."""
    ids = []
    for s in stories:
        m = re.match(rf"{re.escape(STORY_PREFIX)}-(\d+)$", s.get("id", ""))
        if m:
            ids.append(int(m.group(1)))
    return max(ids, default=0) + 1


def create_ac_sub_stories(
    parent_id: str,
    parent_title: str,
    parent_description: str,
    failing_ac_indices: list[int],
    ac_evaluation: list[dict[str, Any]],
    stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Create sub-stories for failing ACs.
    Returns: list of new story objects to add to prd.json
    """
    sub_stories = []
    next_id_num = find_next_id(stories)

    for ac_idx in failing_ac_indices:
        if ac_idx >= len(ac_evaluation):
            continue

        ac_text = ac_evaluation[ac_idx].get("text", f"AC {ac_idx + 1}")
        sub_story_id = f"{STORY_PREFIX}-{next_id_num}"
        next_id_num += 1

        sub_story = {
            "id": sub_story_id,
            "title": f"[Sub] {parent_title} - AC {ac_idx + 1}",
            "description": f"Part of partially-implemented {parent_id}. Acceptance criterion: {ac_text}",
            "acceptanceCriteria": [ac_text],
            "technicalNotes": [
                f"This sub-story was decomposed from {parent_id} (partial victory)",
                f"The parent story passed {len(ac_evaluation) - len(failing_ac_indices)} of {len(ac_evaluation)} ACs",
            ],
            "dependencies": [],
            "estimatedComplexity": "small",
            "passes": False,
            "tags": ["partial-victory", "sub-story"],
            "model": "haiku",
            "_decomposedFrom": parent_id,
            "_source": "partial-victory",
        }
        sub_stories.append(sub_story)

    return sub_stories


def mark_story_as_partial(prd_file: str, story_id: str, ac_count: int, failing_count: int) -> bool:
    """
    Mark story with _partial: true and record AC counts.
    Returns: True on success, False on error.
    """
    try:
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ERROR] Failed to read prd.json: {e}", file=sys.stderr)
        return False

    # Find and update the story
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            story["_partial"] = True
            story["_ac_total"] = ac_count
            story["_ac_failed"] = failing_count
            story["_ac_passed"] = ac_count - failing_count
            break

    # Write back
    try:
        atomic_write_json(prd_file, prd)
        return True
    except OSError as e:
        print(f"[ERROR] Failed to write prd.json: {e}", file=sys.stderr)
        return False


def add_sub_stories(prd_file: str, sub_stories: list[dict[str, Any]]) -> bool:
    """
    Add sub-stories to prd.json.
    Returns: True on success, False on error.
    """
    if not sub_stories:
        return True

    try:
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ERROR] Failed to read prd.json: {e}", file=sys.stderr)
        return False

    # Add sub-stories
    prd["userStories"].extend(sub_stories)

    try:
        atomic_write_json(prd_file, prd)
        return True
    except OSError as e:
        print(f"[ERROR] Failed to write prd.json: {e}", file=sys.stderr)
        return False


def handle_partial_victory(
    story_id: str,
    ac_report_path: str,
    prd_file: str,
) -> bool:
    """
    Main orchestration function for partial victory handling.
    1. Parse AC report
    2. Check if at least 1 AC passed
    3. If yes: mark story as partial, create sub-stories for failing ACs
    4. If no: return False (no partial victory)

    Returns: True if partial victory was processed, False if no partial victory or error.
    """
    # Parse AC report
    ac_report = parse_ac_report(ac_report_path)
    if not ac_report or "ac_evaluation" not in ac_report:
        return False

    ac_evaluation = ac_report.get("ac_evaluation", [])
    if not ac_evaluation:
        return False

    # Check if at least one AC passed
    if not has_passing_acs(ac_evaluation):
        print("  [partial-victory] No passing ACs found — cannot process partial victory")
        return False

    # Get counts
    passing_count = count_passing_acs(ac_evaluation)
    failing_count = len(ac_evaluation) - passing_count
    failing_indices = get_failing_ac_indices(ac_evaluation)

    print(
        f"  [partial-victory] {passing_count}/{len(ac_evaluation)} ACs passed — "
        f"committing partial, decomposing {failing_count} ACs"
    )

    # Read PRD to get story details and existing stories
    try:
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [ERROR] Failed to read prd.json: {e}", file=sys.stderr)
        return False

    # Find parent story
    parent_story = None
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            parent_story = story
            break

    if not parent_story:
        print(f"  [ERROR] Parent story {story_id} not found in prd.json")
        return False

    # Create sub-stories for failing ACs
    parent_title = parent_story.get("title", story_id)
    parent_description = parent_story.get("description", "")
    sub_stories = create_ac_sub_stories(
        story_id,
        parent_title,
        parent_description,
        failing_indices,
        ac_evaluation,
        prd.get("userStories", []),
    )

    # Mark parent story as partial
    if not mark_story_as_partial(prd_file, story_id, len(ac_evaluation), failing_count):
        return False

    # Add sub-stories
    if not add_sub_stories(prd_file, sub_stories):
        return False

    # Log the partial victory
    sub_story_ids = [s["id"] for s in sub_stories]
    print(f"  [partial-victory] {story_id}: {passing_count}/{len(ac_evaluation)} ACs passed")
    for sub_id in sub_story_ids:
        print(f"  [partial-victory]   Decomposed: {sub_id}")

    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Phase I: Partial Victory Handler")
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., US-XXX)")
    parser.add_argument(
        "--ac-report",
        required=True,
        help="Path to AC evaluation report JSON",
    )
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")

    args = parser.parse_args()

    # Check if report exists
    if not Path(args.ac_report).exists():
        # No report = no partial victory processing
        return 0

    # Handle partial victory
    if handle_partial_victory(args.story_id, args.ac_report, args.prd):
        return 0  # Partial victory processed
    else:
        return 1  # No partial victory or error


if __name__ == "__main__":
    sys.exit(main())
