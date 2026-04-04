#!/usr/bin/env python3
"""Compute implementation velocity scores for story candidates."""

from __future__ import annotations

from typing import Any


def compute_velocity_score(
    story: dict[str, Any],
    velocity_model: dict[str, Any] | None = None,
    results_tsv_path: str = "results.tsv",
) -> float:
    """
    Compute velocity score (0-100) for a story candidate.

    Scoring: 100 baseline - 5pts/file beyond 3 (capped -40) - 15pts per
    complexity keyword (capped -50) + bonus for historical fast patterns.

    Args:
        story: Story dict with title, description, filesTouch
        velocity_model: Velocity model (optional)
        results_tsv_path: Path to results.tsv (optional)

    Returns:
        Velocity score 0-100 (higher = faster expected implementation)
    """
    score = 100.0

    # Penalty: file count (beyond 3)
    file_count = len(story.get("filesTouch", []))
    if file_count > 3:
        file_penalty = min(40, (file_count - 3) * 5)
        score -= file_penalty

    # Penalty: complexity keywords
    text = f"{story.get('title', '')} {story.get('description', '')}".lower()
    arch_keywords = [
        "architecture",
        "refactor",
        "migration",
        "redesign",
        "overhaul",
        "legacy",
        "framework",
        "infrastructure",
        "api",
        "protocol",
        "schema",
        "database",
        "restructure",
    ]
    keyword_count = sum(1 for kw in arch_keywords if kw in text)
    keyword_penalty = min(50, keyword_count * 15)
    score -= keyword_penalty

    # Bonus: if model shows high pass rates
    if velocity_model and velocity_model.get("story_types"):
        types = velocity_model.get("story_types", {})
        high_pass = sum(1 for st in types.values() if st.get("pass_rate", 0) > 0.75)
        if high_pass / max(1, len(types)) > 0.6:
            score += 10

    return max(0.0, min(100.0, score))


def sort_candidates_by_velocity(
    candidates: list[dict[str, Any]],
    velocity_model: dict[str, Any] | None = None,
    results_tsv_path: str = "results.tsv",
    reverse: bool = True,
) -> list[dict[str, Any]]:
    """Sort candidates by velocity score (highest first by default)."""
    scored = [(story, compute_velocity_score(story, velocity_model, results_tsv_path)) for story in candidates]
    scored.sort(key=lambda x: x[1], reverse=reverse)
    return [story for story, _score in scored]
