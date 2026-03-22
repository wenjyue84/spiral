#!/usr/bin/env python3
"""
lib/commands/show_slowest_stories.py — Identify bottleneck stories by total duration (US-712).

Reads results.tsv and identifies stories with the longest cumulative duration across all
iterations. Groups stories by story_id, sums duration_sec, and outputs a sorted table
showing story_id, total_duration_sec, and iteration_breakdown (max duration iteration).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class StoryDuration:
    """Aggregated story duration across all iterations."""

    story_id: str
    story_title: str
    total_duration_sec: float
    max_duration_iteration: int  # The iteration with the longest single duration
    max_iteration_duration: float  # The duration of that longest iteration


def load_results_tsv(path: Path | str) -> list[dict[str, str]]:
    """Load results.tsv into a list of row dicts.

    Args:
        path: Path to results.tsv file

    Returns:
        List of row dicts from the TSV file, or empty list if file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        return []

    records = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return []
            records = list(reader)
    except (FileNotFoundError, ValueError):
        return []

    return records


def aggregate_by_story(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Aggregate durations by story_id.

    For each story_id, tracks:
        - total_duration_sec: sum of all duration_sec values
        - story_title: the story title (from last occurrence)
        - durations: list of individual iteration durations (for finding max)

    Args:
        rows: List of result rows from results.tsv

    Returns:
        Dict mapping story_id to aggregated data
    """
    aggregated: dict[str, dict[str, Any]] = {}

    for row in rows:
        story_id = (row.get("story_id") or "").strip()
        story_title = (row.get("story_title") or "").strip()
        duration_str = (row.get("duration_sec") or "").strip()

        if not story_id:
            continue

        # Parse duration as float, default to 0 if invalid
        try:
            duration = float(duration_str) if duration_str else 0.0
        except (ValueError, TypeError):
            duration = 0.0

        if story_id not in aggregated:
            aggregated[story_id] = {
                "story_title": story_title,
                "total_duration_sec": 0.0,
                "durations": [],
            }

        aggregated[story_id]["total_duration_sec"] += duration
        aggregated[story_id]["durations"].append(duration)
        if story_title:
            aggregated[story_id]["story_title"] = story_title

    return aggregated


def compute_slowest_stories(
    aggregated: dict[str, dict[str, Any]],
) -> list[StoryDuration]:
    """Compute slowest stories with max iteration duration.

    Args:
        aggregated: Dict from aggregate_by_story()

    Returns:
        List of StoryDuration objects sorted by total_duration_sec descending
    """
    stories: list[StoryDuration] = []

    for story_id, data in aggregated.items():
        durations = data["durations"]
        max_iteration_duration = max(durations) if durations else 0.0
        # Iteration number is index + 1
        max_duration_iteration = durations.index(max_iteration_duration) + 1 if durations else 0

        story = StoryDuration(
            story_id=story_id,
            story_title=data["story_title"],
            total_duration_sec=data["total_duration_sec"],
            max_duration_iteration=max_duration_iteration,
            max_iteration_duration=max_iteration_duration,
        )
        stories.append(story)

    # Sort by total_duration_sec descending
    stories.sort(key=lambda s: s.total_duration_sec, reverse=True)

    return stories


def format_slowest_stories(stories: list[StoryDuration], limit: int = 5) -> str:
    """Format slowest stories as a human-readable table.

    Args:
        stories: List of StoryDuration objects
        limit: Number of top stories to show (default 5)

    Returns:
        Formatted table string
    """
    lines = []
    lines.append("Story ID         Total Duration  Longest Iteration  Duration")
    lines.append("-" * 70)

    for story in stories[:limit]:
        # Format: story_id (15 chars), total duration (15 chars), iteration (18 chars), duration (15 chars)
        line = (
            f"{story.story_id:<15} "
            f"{story.total_duration_sec:>14.1f}s "
            f"{story.max_duration_iteration:>17} "
            f"{story.max_iteration_duration:>14.1f}s"
        )
        lines.append(line)

    if len(stories) > limit:
        lines.append(f"\n... and {len(stories) - limit} more")

    return "\n".join(lines)


def show_slowest_stories(
    results_tsv_path: Path | str = "results.tsv",
    limit: int = 5,
) -> str:
    """Main entry point: read results.tsv and return formatted slowest stories table.

    Args:
        results_tsv_path: Path to results.tsv file
        limit: Number of slowest stories to display (default 5)

    Returns:
        Formatted table string
    """
    rows = load_results_tsv(results_tsv_path)
    aggregated = aggregate_by_story(rows)
    stories = compute_slowest_stories(aggregated)
    return format_slowest_stories(stories, limit=limit)
