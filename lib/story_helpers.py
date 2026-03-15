"""Shared story helpers for SPIRAL -- imports only from constants."""
from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from constants import PRIORITY_RANK


def get_files_to_touch(story: dict[str, Any]) -> set[str]:
    """Extract filesTouch from story, checking both top-level and technicalHints."""
    files: set[str] = set(story.get("filesTouch", []))
    if not files:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files = set(hints.get("filesTouch", []))
    return files


def priority_key(story: dict[str, Any]) -> int:
    """Return numeric priority rank (lower = higher priority)."""
    return PRIORITY_RANK.get(story.get("priority", "medium"), 2)
