"""Shared story helpers for SPIRAL -- imports only from constants."""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from constants import PRIORITY_SCORE_DEFAULT


def get_files_to_touch(story: dict[str, Any]) -> set[str]:
    """Extract filesTouch from story, checking both top-level and technicalHints."""
    files: set[str] = set(story.get("filesTouch", []))
    if not files:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files = set(hints.get("filesTouch", []))
    return files


def priority_key(story: dict[str, Any]) -> int:
    """Return numeric sort key (lower = higher priority).

    Uses priorityScore (0-100) when present; falls back to text priority via
    PRIORITY_SCORE_DEFAULT.  A priorityScore of 100 returns 0 (highest rank);
    a priorityScore of 0 returns 100 (lowest rank).
    """
    if "priorityScore" in story:
        return 100 - int(story["priorityScore"])
    score = PRIORITY_SCORE_DEFAULT.get(story.get("priority", "medium"), 40)
    return 100 - score
