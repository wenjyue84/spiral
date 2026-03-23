"""lib/rejected_pattern_cache.py — Cross-iteration rejected story pattern caching.

Tracks fingerprints of rejected stories across iterations to avoid re-suggesting
similar candidates that failed Phase S validation in the past. Implements US-771.

When Phase S rejects a story, this module records its fingerprint. When Phase A
generates new candidates, this module filters them to skip patterns with >80%
Jaccard similarity to previously rejected patterns.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class StoryFingerprint:
    """Compact representation of a story for similarity matching."""

    story_id: str
    title: str
    description: str
    tags: list[str]
    rejection_reason: str
    rejection_iteration: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoryFingerprint:
        """Create from dictionary."""
        return cls(
            story_id=data.get("story_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            rejection_reason=data.get("rejection_reason", ""),
            rejection_iteration=data.get("rejection_iteration", 0),
        )


def tokenize(text: str) -> set[str]:
    """Tokenize text into words (lowercase, alphanumeric only)."""
    import re

    # Split on non-alphanumeric characters and lowercase
    words = re.findall(r"\b\w+\b", text.lower())
    return set(words)


def jaccard_similarity(set1: set[str], set2: set[str]) -> float:
    """Calculate Jaccard similarity between two sets."""
    if not set1 and not set2:
        return 1.0  # Both empty = identical
    if not set1 or not set2:
        return 0.0  # One empty, one not = no similarity
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    if union == 0:
        return 0.0
    return intersection / union


def extract_story_features(story: dict[str, Any]) -> set[str]:
    """Extract identifying features from a story for fingerprinting.

    Combines title, description, and tags into a single set of tokens.
    """
    features: set[str] = set()

    # Add title tokens (high weight)
    if "title" in story:
        features.update(tokenize(story["title"]))

    # Add description tokens
    if "description" in story:
        features.update(tokenize(story["description"]))

    # Add tags as-is (whole tags, not tokenized)
    if "tags" in story and isinstance(story.get("tags"), list):
        features.update(str(t).lower() for t in story["tags"])

    return features


def fingerprint_story(
    story: dict[str, Any], rejection_reason: str = "", iteration: int = 0
) -> StoryFingerprint:
    """Create a fingerprint of a story for rejection tracking."""
    return StoryFingerprint(
        story_id=story.get("id", ""),
        title=story.get("title", ""),
        description=story.get("description", ""),
        tags=story.get("tags", []),
        rejection_reason=rejection_reason,
        rejection_iteration=iteration,
    )


def load_rejected_patterns(cache_path: Path) -> list[StoryFingerprint]:
    """Load rejected story fingerprints from cache file."""
    if not cache_path.exists():
        return []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        patterns = data.get("rejected_patterns", [])
        return [StoryFingerprint.from_dict(p) for p in patterns]
    except (json.JSONDecodeError, KeyError):
        return []


def save_rejected_patterns(
    patterns: list[StoryFingerprint], cache_path: Path, max_entries: int = 100
) -> None:
    """Save rejected patterns to cache file, pruning to max_entries."""
    # Keep only the most recent max_entries patterns
    pruned = patterns[-max_entries:]
    data = {
        "rejected_patterns": [p.to_dict() for p in pruned],
        "total_tracked": len(patterns),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def should_skip_candidate(
    candidate: dict[str, Any], rejected_patterns: list[StoryFingerprint], threshold: float = 0.8
) -> tuple[bool, str]:
    """Check if a candidate matches a rejected pattern (>threshold similarity).

    Returns:
        (should_skip, rejection_reason): True if candidate should be skipped
    """
    candidate_features = extract_story_features(candidate)
    if not candidate_features:
        return False, ""

    for pattern in rejected_patterns:
        pattern_features = extract_story_features(
            {
                "title": pattern.title,
                "description": pattern.description,
                "tags": pattern.tags,
            }
        )
        similarity = jaccard_similarity(candidate_features, pattern_features)
        if similarity >= threshold:
            return True, f"Matches rejected pattern {pattern.story_id} ({similarity:.1%} similar)"

    return False, ""


def record_rejected_story(
    story: dict[str, Any],
    rejection_reason: str,
    cache_path: Path,
    iteration: int = 0,
    max_entries: int = 100,
) -> None:
    """Record a rejected story's fingerprint to the cache.

    Args:
        story: The story that was rejected
        rejection_reason: Why it was rejected (from Phase S)
        cache_path: Path to .spiral/rejected_patterns.json
        iteration: Current SPIRAL iteration
        max_entries: Max patterns to keep (older ones pruned)
    """
    patterns = load_rejected_patterns(cache_path)
    fingerprint = fingerprint_story(story, rejection_reason, iteration)
    patterns.append(fingerprint)
    save_rejected_patterns(patterns, cache_path, max_entries)


def filter_candidates_by_rejected_patterns(
    candidates: list[dict[str, Any]],
    cache_path: Path,
    similarity_threshold: float = 0.8,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Filter out candidates that match rejected patterns.

    Returns:
        (kept_candidates, skipped_reasons): Candidates that passed filter and their skip reasons
    """
    rejected_patterns = load_rejected_patterns(cache_path)
    if not rejected_patterns:
        return candidates, {}

    kept = []
    skipped = {}

    for candidate in candidates:
        should_skip, reason = should_skip_candidate(candidate, rejected_patterns, similarity_threshold)
        if should_skip:
            skipped[candidate.get("id", "unknown")] = reason
        else:
            kept.append(candidate)

    return kept, skipped
