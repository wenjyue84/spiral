#!/usr/bin/env python3
"""
meta_harness.py — Success-Pattern Library for Phase L and Phase A.

US-1225: Meta-Harness: Success-Pattern Library with Phase L to Phase A Feedback Loop

Extracts characteristics from stories that pass with 0 retries and stores them
in _success_patterns.jsonl for Phase A to use when scoring candidate stories.

Usage:
    # Phase L — extract success patterns from passed stories
    from lib.meta_harness import extract_success_pattern, append_success_pattern
    pattern = extract_success_pattern(story_dict)
    append_success_pattern(pattern, path_to_patterns_file)

    # Phase A — score candidates using success patterns
    from lib.meta_harness import score_candidate_from_patterns
    score = score_candidate_from_patterns(candidate_story, path_to_patterns_file)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def extract_success_pattern(story: dict[str, Any]) -> dict[str, Any]:
    """Extract success pattern characteristics from a passed story (0 retries).

    Extracts:
    - file_count: Number of files touched
    - ac_count: Number of acceptance criteria
    - keywords: Top keywords from title + description (stemmed, lowercased)

    Args:
        story: Story dict from prd.json with passes=True and 0 retries

    Returns:
        Pattern dict with keys: file_count, ac_count, keywords, story_id
    """
    story_id = story.get("id", "unknown")

    # Count files touched
    files_touch = story.get("filesTouch", [])
    file_count = len(files_touch) if isinstance(files_touch, list) else 0

    # Count acceptance criteria
    ac_list = story.get("acceptanceCriteria", [])
    ac_count = len(ac_list) if isinstance(ac_list, list) else 0

    # Extract keywords from title + description
    title = story.get("title", "")
    desc = story.get("description", "")
    combined_text = f"{title} {desc}".lower()

    # Simple tokenization: split on non-alphanumeric, filter short tokens and common words
    tokens = re.findall(r"\b[a-z0-9]{3,}\b", combined_text)
    stopwords = {"the", "and", "for", "with", "from", "test", "story", "phase"}
    keywords = sorted(list(set(t for t in tokens if t not in stopwords)))[:10]

    return {
        "file_count": file_count,
        "ac_count": ac_count,
        "keywords": keywords,
        "story_id": story_id,
    }


def append_success_pattern(pattern: dict[str, Any], path: Path | str) -> dict[str, Any]:
    """Append a success pattern to _success_patterns.jsonl, deduplicating on story_id.

    If a pattern with the same story_id already exists, skip the append.

    Args:
        pattern: Pattern dict from extract_success_pattern()
        path: Path to _success_patterns.jsonl file

    Returns:
        The pattern dict (new or existing)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing patterns
    existing = load_success_patterns(path)
    story_id = pattern.get("story_id")

    # Check if this story_id is already recorded
    for existing_pattern in existing:
        if existing_pattern.get("story_id") == story_id:
            return existing_pattern

    # Append new pattern
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(pattern, ensure_ascii=False) + "\n")

    return pattern


def load_success_patterns(path: Path | str) -> list[dict[str, Any]]:
    """Load all success patterns from _success_patterns.jsonl.

    Args:
        path: Path to _success_patterns.jsonl file

    Returns:
        List of pattern dicts, empty list if file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        return []

    patterns: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                patterns.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return patterns


def _keywords_overlap(keywords_a: list[str], keywords_b: list[str]) -> float:
    """Calculate Jaccard similarity between two keyword lists (0.0 to 1.0)."""
    if not keywords_a or not keywords_b:
        return 0.0
    set_a = set(keywords_a)
    set_b = set(keywords_b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def score_candidate_from_patterns(candidate: dict[str, Any], patterns_path: Path | str) -> float:
    """Score a candidate story based on similarity to success patterns.

    Scores are based on:
    - Matching file_count and ac_count ranges (±1)
    - Keyword overlap with stored patterns (Jaccard similarity)

    A candidate with no matches gets score 0.0.
    A candidate matching 1+ patterns gets boosted by the highest keyword overlap.

    Args:
        candidate: Story dict to score
        patterns_path: Path to _success_patterns.jsonl

    Returns:
        Score between 0.0 (no match) and 1.0 (perfect match)
    """
    patterns = load_success_patterns(patterns_path)
    if not patterns:
        return 0.0

    candidate_files = len(candidate.get("filesTouch", []) or [])
    candidate_acs = len(candidate.get("acceptanceCriteria", []) or [])
    candidate_title = candidate.get("title", "")
    candidate_desc = candidate.get("description", "")
    candidate_text = f"{candidate_title} {candidate_desc}".lower()
    candidate_keywords = sorted(list(set(re.findall(r"\b[a-z0-9]{3,}\b", candidate_text))))[:10]

    best_score = 0.0
    for pattern in patterns:
        pattern_files = pattern.get("file_count", 0)
        pattern_acs = pattern.get("ac_count", 0)
        pattern_keywords = pattern.get("keywords", [])

        # Check if file count and AC count are in reasonable range (±1)
        file_match = abs(candidate_files - pattern_files) <= 1
        ac_match = abs(candidate_acs - pattern_acs) <= 1

        # If structural properties match, score by keyword overlap
        if file_match and ac_match:
            keyword_score = _keywords_overlap(candidate_keywords, pattern_keywords)
            best_score = max(best_score, keyword_score)

    return best_score
