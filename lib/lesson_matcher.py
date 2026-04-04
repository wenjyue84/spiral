#!/usr/bin/env python3
"""
lesson_matcher.py — Match candidate stories against learned lessons.

Scores lessons by pattern similarity, filesTouch overlap, and title keyword overlap.
Filters by confidence threshold (default >70%) and returns top-k matched lessons.

Used by Phase E enrichment to inject prior learnings into new story candidates.
"""

from __future__ import annotations

import re
from typing import Any

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase alpha-numeric tokens, excluding short tokens."""
    return {t for t in _SPLIT_RE.split(text.lower()) if len(t) > 2}


def _file_path_overlap(files_a: list[str], files_b: list[str]) -> float:
    """Jaccard similarity between two file path lists (token-level).

    Tokenizes each file path and computes overlap. For example:
    - ["lib/foo.py", "tests/test_foo.py"] vs ["lib/foo.py", "tests/other.py"]
    - Would have overlap on "lib", "foo", "tests" tokens
    """
    if not files_a or not files_b:
        return 0.0

    tokens_a = set()
    for f in files_a:
        tokens_a.update(_tokenize(f))

    tokens_b = set()
    for f in files_b:
        tokens_b.update(_tokenize(f))

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def _keyword_overlap(story_text: str, lesson_text: str) -> float:
    """Jaccard similarity between story and lesson text (token-level)."""
    tokens_story = _tokenize(story_text)
    tokens_lesson = _tokenize(lesson_text)

    if not tokens_story or not tokens_lesson:
        return 0.0

    intersection = len(tokens_story & tokens_lesson)
    union = len(tokens_story | tokens_lesson)
    return intersection / union if union > 0 else 0.0


def match_lessons(
    story: dict[str, Any],
    lessons: list[dict[str, Any]],
    confidence_threshold: float = 0.7,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Match a story against learned lessons by pattern, filesTouch, and title overlap.

    Args:
        story: Candidate story with title, description, filesTouch, technicalNotes
        lessons: List of learned lessons from .spiral/learned_lessons.jsonl
        confidence_threshold: Minimum confidence to include (default 0.7 = 70%)
        top_k: Maximum number of lessons to return

    Returns:
        List of matched lessons with scores, sorted by descending score.
        Each lesson includes original fields + "_match_score" field.
    """
    if not lessons:
        return []

    # Build story search text from all available fields
    story_parts = [
        story.get("title", ""),
        story.get("description", ""),
    ]
    if story.get("tags"):
        story_parts.extend(str(t) for t in story["tags"])
    if story.get("technicalNotes"):
        story_parts.extend(str(n) for n in story["technicalNotes"])
    story_text = " ".join(story_parts)

    scored: list[tuple[float, dict[str, Any]]] = []

    for lesson in lessons:
        # Skip if below confidence threshold
        lesson_conf = lesson.get("confidence", 0.5)
        if lesson_conf < confidence_threshold:
            continue

        # Build lesson text: pattern, fix, error_category, story_title
        lesson_parts = [
            lesson.get("pattern", ""),
            lesson.get("fix", ""),
            lesson.get("error_category", ""),
            lesson.get("story_title", ""),
        ]
        lesson_text = " ".join(lesson_parts)

        # Compute three similarity scores
        # 1. Pattern similarity (error pattern keyword overlap)
        pattern_sim = _keyword_overlap(story_text, lesson_text)

        # 2. File overlap (lesson's original story files vs this story's files)
        # Note: lessons don't store original filesTouch, so file matching not available
        # This is placeholder for future enhancement

        # 3. Title/description keyword overlap
        title_desc = " ".join([story.get("title", ""), story.get("description", "")])
        lesson_title = lesson.get("story_title", "")
        title_sim = _keyword_overlap(title_desc, lesson_title)

        # Weighted average: pattern=50%, title=50%
        # (files=0% because not available in lesson store)
        combined_score = (pattern_sim * 0.5) + (title_sim * 0.5)

        # Boost by lesson confidence and seen_count
        seen_count = lesson.get("seen_count", 1)
        boosted_score = combined_score * (lesson_conf * seen_count)

        if boosted_score > 0.0:
            matched_lesson = dict(lesson)  # Copy lesson
            matched_lesson["_match_score"] = boosted_score
            scored.append((boosted_score, matched_lesson))

    # Sort by descending score
    scored.sort(key=lambda x: x[0], reverse=True)

    # Return top-k lessons without the sort tuple
    return [lesson for _, lesson in scored[:top_k]]
