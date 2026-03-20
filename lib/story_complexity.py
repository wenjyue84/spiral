#!/usr/bin/env python3
"""
story_complexity.py — Story complexity scorer for SPIRAL worker load balancing.

Computes a 1-10 complexity score for a story based on:
  - 40% description token count (word count proxy)
  - 30% dependency count (pending deps in the PRD)
  - 20% changed_files count (filesTouch hint from last attempt)
  - 10% past_retry_count (retry_num from story metadata)

Usage as module:
    from story_complexity import compute_story_complexity
    score = compute_story_complexity(story, prd)

Usage as CLI:
    python lib/story_complexity.py --story-id US-001 --prd prd.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any


# ── Scoring calibration constants ─────────────────────────────────────────────
# These thresholds are tuned to map typical SPIRAL stories onto the 1-10 scale.

# Description length: 100 words → score ~5, 200+ words → max component
_DESC_WORDS_MAX = 200

# Dependency count: 5+ deps → max component
_DEP_COUNT_MAX = 5

# Changed files: 10+ files → max component
_FILES_COUNT_MAX = 10

# Past retry count: 3+ retries → max component
_RETRY_COUNT_MAX = 3

# Weights must sum to 1.0
_W_DESC = 0.40
_W_DEPS = 0.30
_W_FILES = 0.20
_W_RETRIES = 0.10


def compute_story_complexity(story: dict[str, Any], prd: dict[str, Any]) -> float:
    """Return a complexity score between 1.0 and 10.0.

    Weights:
        40% — description token count (word count of description field)
        30% — dependency count (count of entries in dependencies[] list)
        20% — changed_files count (filesTouch hint, 0 if not present)
        10% — past_retry_count (retry_num field, 0 if absent)

    Args:
        story: A single story dict from prd.json.
        prd: The full PRD dict (used to resolve pending deps, currently unused
             but kept for future graph-aware scoring).

    Returns:
        Float in [1.0, 10.0].
    """
    # ── Description word count component ──────────────────────────────────────
    description = story.get("description", "") or ""
    desc_words = len(description.split())
    desc_component = min(desc_words / _DESC_WORDS_MAX, 1.0)

    # ── Dependency count component ─────────────────────────────────────────────
    deps = story.get("dependencies", []) or []
    dep_count = len(deps)
    dep_component = min(dep_count / _DEP_COUNT_MAX, 1.0)

    # ── Changed files component ────────────────────────────────────────────────
    # filesTouch may live at top level or inside technicalHints
    files_touch: list[str] = story.get("filesTouch", []) or []
    if not files_touch:
        hints = story.get("technicalHints", {})
        if isinstance(hints, dict):
            files_touch = hints.get("filesTouch", []) or []
    files_component = min(len(files_touch) / _FILES_COUNT_MAX, 1.0)

    # ── Past retry count component ─────────────────────────────────────────────
    retry_count = int(story.get("retry_num", 0) or 0)
    retry_component = min(retry_count / _RETRY_COUNT_MAX, 1.0)

    # ── Weighted composite [0.0, 1.0] → rescale to [1.0, 10.0] ──────────────
    raw = (
        _W_DESC * desc_component
        + _W_DEPS * dep_component
        + _W_FILES * files_component
        + _W_RETRIES * retry_component
    )
    score = 1.0 + raw * 9.0  # maps [0,1] → [1,10]
    return round(min(max(score, 1.0), 10.0), 2)


def complexity_band(score: float) -> str:
    """Return 'low' (1-3), 'medium' (4-6), or 'high' (7-10) band label."""
    if score <= 3.0:
        return "low"
    if score <= 6.0:
        return "medium"
    return "high"


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Compute story complexity score")
    parser.add_argument("--story-id", required=True, help="Story ID to score")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    story = next((s for s in stories if s["id"] == args.story_id), None)
    if story is None:
        print(f"ERROR: story {args.story_id} not found in {args.prd}", file=sys.stderr)
        return 1

    score = compute_story_complexity(story, prd)
    print(
        json.dumps(
            {
                "story_id": args.story_id,
                "complexity_score": score,
                "band": complexity_band(score),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
