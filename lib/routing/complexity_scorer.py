"""Complexity scoring for stories based on semantic similarity and historical patterns.

US-642: Predict story complexity by analyzing semantic similarity to past stories
and deriving a complexity score (1-10) from retry patterns and token usage.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def compute_embedding(text: str) -> list[float]:
    """Compute embedding vector for a text string using simple word frequency.

    Uses a simple TF-based approach to avoid heavy dependencies.
    Returns a normalized vector of word frequencies.

    Args:
        text: Text to embed

    Returns:
        Embedding vector as list of floats (length = number of unique words seen)
    """
    if not text or not text.strip():
        # Return a 10-element zero vector for empty text
        return [0.0] * 10

    # Split into words and normalize
    words = text.lower().split()
    # Create a simple word frequency vector (limited to 50 most common patterns)
    word_freq: dict[str, int] = {}
    for word in words:
        # Simple word normalization
        clean_word = "".join(c for c in word if c.isalnum() or c in "-_")
        if clean_word and len(clean_word) > 2:  # Skip very short words
            word_freq[clean_word] = word_freq.get(clean_word, 0) + 1

    # Normalize to get a fixed-size vector (use first 384 dimensions like sentence-transformers)
    max_dim = 384
    embedding: list[float] = [0.0] * max_dim

    # Distribute word frequencies across dimensions using hash-based bucketing
    for idx, (word, freq) in enumerate(sorted(word_freq.items(), key=lambda x: x[1], reverse=True)):
        bucket_idx = hash(word) % max_dim
        # Normalize frequency: max 1.0 per dimension
        embedding[bucket_idx] = min(1.0, freq / max(1, len(words)))

    return embedding


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors.

    Args:
        vec_a: First embedding vector
        vec_b: Second embedding vector

    Returns:
        Cosine similarity score (0.0 to 1.0)
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    # Compute dot product
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))

    # Compute magnitudes
    mag_a = sum(a * a for a in vec_a) ** 0.5
    mag_b = sum(b * b for b in vec_b) ** 0.5

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return float(dot_product / (mag_a * mag_b))


def load_story_history(results_tsv_path: Path) -> list[dict[str, Any]]:
    """Load story history from results.tsv.

    Args:
        results_tsv_path: Path to results.tsv

    Returns:
        List of story dicts with: story_id, story_title, retry_num, status
    """
    stories: list[dict[str, Any]] = []

    if not results_tsv_path.exists():
        return stories

    try:
        with open(results_tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if row and row.get("story_id"):
                    stories.append({
                        "story_id": row.get("story_id", ""),
                        "story_title": row.get("story_title", ""),
                        "retry_num": int(row.get("retry_num", 0)),
                        "status": row.get("status", ""),
                        "duration_sec": int(row.get("duration_sec", 0)),
                    })
    except (OSError, csv.Error, ValueError):
        pass

    return stories


def compute_complexity_score(retry_count: int, tokens: int) -> int:
    """Derive complexity score (1-10) from retry and token patterns.

    Score increases with retry count (indicates difficulty).
    Very high token usage also indicates complexity.

    Args:
        retry_count: Number of retries for this story
        tokens: Approximate token count used

    Returns:
        Complexity score 1-10
    """
    score = 1

    # Retry-based scoring
    if retry_count >= 3:
        score = min(10, score + 6)  # Very difficult
    elif retry_count == 2:
        score = min(10, score + 4)  # Difficult
    elif retry_count == 1:
        score = min(10, score + 2)  # Moderate
    # else: retry_count == 0 stays at 1 (easy)

    # Token-based scoring (high token usage = complexity)
    if tokens > 100000:
        score = min(10, score + 3)
    elif tokens > 50000:
        score = min(10, score + 1)

    return max(1, min(10, score))


def find_similar_stories(
    story_description: str,
    story_history: list[dict[str, Any]],
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Find top-k similar stories from history using semantic similarity.

    Args:
        story_description: Description of the story to find matches for
        story_history: List of historical stories with titles
        top_k: Number of similar stories to return

    Returns:
        List of dicts: {id, similarity, avg_retries, tokens}
    """
    if not story_history:
        return []

    # Compute embedding for target story
    target_embedding = compute_embedding(story_description)

    # Score all historical stories
    scored_stories: list[dict[str, Any]] = []
    for story in story_history:
        title = story.get("story_title", "")
        if not title:
            continue

        story_embedding = compute_embedding(title)
        similarity = cosine_similarity(target_embedding, story_embedding)

        if similarity > 0:  # Only include if there's some similarity
            scored_stories.append({
                "id": story.get("story_id", ""),
                "similarity": round(similarity, 2),
                "avg_retries": story.get("retry_num", 0),
                "tokens": story.get("duration_sec", 0) * 100,  # Rough estimate
            })

    # Sort by similarity descending, return top-k
    scored_stories.sort(key=lambda x: x["similarity"], reverse=True)
    return scored_stories[:top_k]


def predict_story_complexity(
    story_id: str,
    story_description: str,
    prd_path: Path = Path("prd.json"),
    results_tsv_path: Path = Path("results.tsv"),
) -> dict[str, Any]:
    """Predict story complexity and return scored output.

    Args:
        story_id: Story ID (e.g., 'US-123')
        story_description: Story description text
        prd_path: Path to prd.json
        results_tsv_path: Path to results.tsv

    Returns:
        Dict with: {story_id, score, label, similar: [{id, similarity, avg_retries, tokens}]}
    """
    # Load historical stories
    history = load_story_history(results_tsv_path)

    # Find similar stories
    similar = find_similar_stories(story_description, history, top_k=3)

    # Compute base score from historical retries
    avg_retries = 0
    if similar:
        avg_retries = int(sum(s.get("avg_retries", 0) for s in similar) / len(similar))

    base_score = compute_complexity_score(avg_retries, 0)

    # Adjust based on description length (longer = potentially more complex)
    word_count = len(story_description.split())
    if word_count > 100:
        base_score = min(10, base_score + 1)

    final_score = max(1, min(10, base_score))

    # Determine label
    if final_score <= 3:
        label = "easy"
    elif final_score <= 6:
        label = "medium"
    else:
        label = "hard"

    return {
        "story_id": story_id,
        "score": final_score,
        "label": label,
        "similar": similar,
    }
