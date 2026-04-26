"""
Research quality checker for Phase R.

Computes quality scores for research results based on citation count, source
diversity, and TF-IDF relevance, and determines whether research should be
replayed based on score thresholds and attempt limits.

Acceptance Criteria (US-1281):
- compute_quality_score returns a float in [0.0, 1.0]
- should_replay returns True when score < 0.7 and attempt < 3
- should_replay returns False when attempt_count >= 3
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResearchResult:
    """Represents a research result with citations and sources."""

    citations: list[str]
    sources: list[str]
    content: str


def compute_quality_score(
    research_result: ResearchResult | dict[str, Any],
    story_title: str,
) -> float:
    """
    Compute a quality score for a research result.

    Scoring factors:
    - Citation count (0.0-0.4): more citations = higher score
    - Source diversity (0.0-0.3): more unique sources = higher score
    - TF-IDF relevance (0.0-0.3): content matches story title = higher score

    Args:
        research_result: ResearchResult object or dict with keys:
            citations (list), sources (list), content (str)
        story_title: The story title to check relevance against

    Returns:
        A float in [0.0, 1.0] representing the quality score
    """
    # Convert dict to ResearchResult if needed
    if isinstance(research_result, dict):
        result = ResearchResult(
            citations=research_result.get("citations", []),
            sources=research_result.get("sources", []),
            content=research_result.get("content", ""),
        )
    else:
        result = research_result

    # Citation score (0.0-0.4)
    # Normalized by assuming 10+ citations is excellent
    citation_count = len(result.citations)
    citation_score = min(citation_count / 10.0 * 0.4, 0.4)

    # Source diversity score (0.0-0.3)
    # Normalized by assuming 5+ unique sources is excellent
    unique_sources = len(set(result.sources))
    diversity_score = min(unique_sources / 5.0 * 0.3, 0.3)

    # TF-IDF relevance score (0.0-0.3)
    # Simple cosine similarity between story title and content
    relevance_score = _compute_tfidf_relevance(result.content, story_title)

    # Combine scores
    total_score = citation_score + diversity_score + relevance_score

    # Ensure within bounds [0.0, 1.0]
    return max(0.0, min(total_score, 1.0))


def should_replay(score: float, attempt_count: int) -> bool:
    """
    Determine whether research should be replayed.

    Replay rules:
    - Return False if attempt_count >= 3 (max attempts reached)
    - Return True if score < 0.7 and attempt_count < 3 (quality below threshold)
    - Return False otherwise

    Args:
        score: The quality score (0.0-1.0)
        attempt_count: The current attempt number (0-indexed)

    Returns:
        True if research should be replayed, False otherwise
    """
    # Max attempts is 3, so if attempt_count >= 3, don't replay
    if attempt_count >= 3:
        return False

    # If score is below threshold, replay
    if score < 0.7:
        return True

    # Otherwise, don't replay
    return False


def _compute_tfidf_relevance(content: str, story_title: str) -> float:
    """
    Compute TF-IDF based relevance score using simple cosine similarity.

    Uses term frequency to score how much the story title words appear
    in the content, normalized by content length.

    Args:
        content: The research content text
        story_title: The story title to check relevance against

    Returns:
        A float in [0.0, 0.3] representing the relevance component
    """
    if not content or not story_title:
        return 0.0

    # Convert to lowercase and split into words
    title_words = set(story_title.lower().split())
    content_lower = content.lower()

    # Count how many title words appear in content
    matching_words = sum(1 for word in title_words if word in content_lower)

    # Score is ratio of matching words to total title words
    # normalized to max 0.3
    relevance_ratio = matching_words / len(title_words) if title_words else 0.0

    return min(relevance_ratio * 0.3, 0.3)
