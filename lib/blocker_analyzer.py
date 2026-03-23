#!/usr/bin/env python3
"""lib/blocker_analyzer.py — Analyze blocked stories due to unmet dependencies (US-1071).

Functions
---------
analyze_blocked_stories(prd_path, results_tsv_path) -> list[dict]
    Return list of blocked stories with {id, reason, blocking_story_ids, estimated_unblock_hours}.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median
from typing import Any


def analyze_blocked_stories(
    prd_path: str | Path = "prd.json",
    results_tsv_path: str | Path = ".spiral/results.tsv",
) -> list[dict[str, Any]]:
    """Analyze blocked stories based on dependency graph and completion times.

    Args:
        prd_path: Path to prd.json file
        results_tsv_path: Path to results.tsv file

    Returns:
        List of blocked story dicts: {id, reason, blocking_story_ids, estimated_unblock_hours}
    """
    prd_path = Path(prd_path)
    results_tsv_path = Path(results_tsv_path)

    # Load PRD and extract stories
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        stories = prd.get("userStories", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    # Build status map from results.tsv
    passed_stories = _get_passed_stories(results_tsv_path)

    # Calculate median completion time for ETA estimation
    completion_times = _get_story_completion_times(results_tsv_path)
    median_completion_hours = median(completion_times) if completion_times else 1.0

    # Find blocked stories
    blocked = []
    for story in stories:
        story_id = story.get("id", "")
        deps = story.get("dependencies", [])

        if not deps:
            continue

        # Check if all dependencies are passed
        unmet_deps = [d for d in deps if d not in passed_stories]

        if unmet_deps:
            blocked.append(
                {
                    "id": story_id,
                    "reason": f"{len(unmet_deps)} unmet dependencies",
                    "blocking_story_ids": unmet_deps,
                    "estimated_unblock_hours": round(median_completion_hours, 2),
                }
            )

    return blocked


def _get_passed_stories(results_tsv_path: Path) -> set[str]:
    """Extract set of story IDs with status='passed' from results.tsv."""
    if not results_tsv_path.exists():
        return set()

    passed = set()
    try:
        with open(results_tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("status") == "passed":
                    story_id = row.get("story_id", "")
                    if story_id:
                        passed.add(story_id)
    except (OSError, ValueError):
        pass

    return passed


def _get_story_completion_times(results_tsv_path: Path) -> list[float]:
    """Extract list of story completion times in hours from results.tsv.

    Returns list of duration_sec / 3600 for all passing stories.
    """
    if not results_tsv_path.exists():
        return []

    times = []
    try:
        with open(results_tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row.get("status") == "passed":
                    try:
                        duration_sec = float(row.get("duration_sec", "0"))
                        times.append(duration_sec / 3600.0)
                    except (ValueError, TypeError):
                        pass
    except (OSError, ValueError):
        pass

    return times
