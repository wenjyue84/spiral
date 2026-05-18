#!/usr/bin/env python3
"""
lib/story_inspector.py -- CLI command to inspect story metadata, blockers, and dependents.

Usage:
  python lib/story_inspector.py <prd_file> <story_id>

Displays:
  - Story title, description, and full AC list
  - Blockers (stories this story depends on)
  - Dependents (stories that depend on this story)
  - Estimated complexity band
"""

import json
import sys
from typing import Any, Optional


def load_story_by_id(prd_file: str, story_id: str) -> Optional[dict[str, Any]]:
    """Load and return a single story from prd.json by ID."""
    try:
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[spiral] ERROR: Failed to load {prd_file}: {e}", file=sys.stderr)
        return None

    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            return story

    print(f"[spiral] ERROR: Story {story_id} not found in {prd_file}", file=sys.stderr)
    return None


def find_blockers_and_dependents(
    prd_file: str, story_id: str
) -> tuple[list[str], list[str]]:
    """
    Find blockers (stories this story depends on) and dependents (stories that depend on this story).

    Returns:
      (blockers, dependents) where each is a list of story IDs
    """
    try:
        with open(prd_file, encoding="utf-8") as f:
            prd = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [], []

    blockers: list[str] = []
    dependents: list[str] = []

    # Build dependency graph
    for story in prd.get("userStories", []):
        deps = story.get("dependencies", [])

        if story.get("id") == story_id:
            # This story's dependencies are its blockers
            blockers = deps

        if story_id in deps:
            # This story is a dependency of another, so that story is a dependent
            dependents.append(story.get("id", ""))

    return blockers, dependents


def estimate_complexity(story: dict[str, Any]) -> str:
    """
    Estimate complexity band (small/medium/large) from AC word count.

    Heuristic:
      - small: < 30 words in AC combined
      - medium: 30-100 words
      - large: > 100 words
    """
    ac_list = story.get("acceptanceCriteria", [])
    total_words = sum(len(ac.split()) for ac in ac_list)

    if total_words < 30:
        return "small"
    elif total_words < 100:
        return "medium"
    else:
        return "large"


def format_inspect_output(
    story: dict[str, Any],
    blockers: list[str],
    dependents: list[str],
    complexity: str,
) -> str:
    """Format story inspection output as text."""
    lines = []

    # Title and ID
    story_id = story.get("id", "?")
    title = story.get("title", "?")
    lines.append(f"Story: {story_id} -- {title}")
    lines.append("")

    # Status
    status = "✓ PASSED" if story.get("passes") else "⏳ PENDING"
    lines.append(f"Status: {status}")
    lines.append("")

    # Complexity
    lines.append(f"Complexity: {complexity}")
    lines.append("")

    # Source
    source = story.get("_source", "seed")
    lines.append(f"Source: {source}")
    lines.append("")

    # Description
    description = story.get("description", "(no description)")
    lines.append("Description:")
    lines.append(f"  {description}")
    lines.append("")

    # Acceptance Criteria
    ac_list = story.get("acceptanceCriteria", [])
    lines.append("Acceptance Criteria:")
    if ac_list:
        for i, ac in enumerate(ac_list, 1):
            lines.append(f"  [{i}] {ac}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Blockers
    lines.append("Blockers (stories this depends on):")
    if blockers:
        for blocker_id in blockers:
            lines.append(f"  - {blocker_id}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Dependents
    lines.append("Dependents (stories that depend on this):")
    if dependents:
        for dependent_id in dependents:
            lines.append(f"  - {dependent_id}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def main() -> int:
    """Main entry point for CLI."""
    if len(sys.argv) < 3:
        print(
            "Usage: python lib/story_inspector.py <prd_file> <story_id>",
            file=sys.stderr,
        )
        return 1

    prd_file = sys.argv[1]
    story_id = sys.argv[2]

    story = load_story_by_id(prd_file, story_id)
    if not story:
        return 1

    blockers, dependents = find_blockers_and_dependents(prd_file, story_id)
    complexity = estimate_complexity(story)

    output = format_inspect_output(story, blockers, dependents, complexity)
    print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
