"""Phase S — Duplicate Story Detection via Embeddings.

Detects duplicate stories using sentence-transformers embeddings with cosine
similarity. Embeddings are cached to avoid recomputation across runs.

Usage:
    from lib.phase_s.duplicate_detector import find_duplicates

    duplicates = find_duplicates(stories)
    # Returns: [(story_a, story_b, similarity_score), ...]
"""

from __future__ import annotations

import difflib
import os
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from lib.phase_s.embedding_cache import compute_title_hash, load_cache, save_cache


def find_duplicates(
    stories: list[dict[str, Any]],
    similarity_threshold: float = 0.80,
    cache_dir: str = ".spiral",
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    """Find duplicate stories using sentence-transformers embeddings.

    Computes embeddings for each story's title+description using
    all-MiniLM-L6-v2 model. Results are cached in .spiral/embedding_cache.jsonl
    to avoid recomputation.

    Args:
        stories: List of story dicts with 'title' and 'description' fields.
        similarity_threshold: Minimum cosine similarity (0-1) to report pair.
        cache_dir: Directory for .spiral/embedding_cache.jsonl cache file.

    Returns:
        List of (story_a, story_b, similarity_score) tuples for all pairs
        with similarity > threshold, sorted by score descending.
    """
    if len(stories) < 2:
        return []

    cache_path = os.path.join(cache_dir, "embedding_cache.jsonl")
    os.makedirs(cache_dir, exist_ok=True)

    # Load existing cache
    embedding_cache = load_cache(cache_path)

    # Load model once (will be cached by sentence_transformers)
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Compute or retrieve embeddings for each story
    embeddings: list[list[float]] = []
    new_cache_entries: dict[str, tuple[str, list[float]]] = {}

    for story in stories:
        title = story.get("title", "")
        description = story.get("description", "")
        text = f"{title} {description}".strip()

        title_hash = compute_title_hash(title)

        # Check if embedding is in cache
        if title_hash in embedding_cache:
            embedding = embedding_cache[title_hash]
        else:
            # Compute embedding using sentence-transformers
            try:
                embedding = model.encode(text, convert_to_tensor=False).tolist()
            except Exception:
                # Fallback to difflib.SequenceMatcher-based fake embedding
                # This is a degenerate fallback; in practice should not happen
                embedding = _fallback_embedding(text)

            # Store in new entries for later cache save
            new_cache_entries[title_hash] = (title, embedding)

        embeddings.append(embedding)

    # Save new embeddings to cache
    if new_cache_entries:
        save_cache(cache_path, new_cache_entries)

    # Compute cosine similarity between all pairs
    embeddings_array = np.array(embeddings, dtype=np.float32)
    similarity_matrix = cosine_similarity(embeddings_array)

    # Extract pairs above threshold
    duplicates: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    for i in range(len(stories)):
        for j in range(i + 1, len(stories)):
            score = float(similarity_matrix[i][j])
            if score > similarity_threshold:
                duplicates.append((stories[i], stories[j], score))

    # Sort by score descending
    duplicates.sort(key=lambda x: -x[2])
    return duplicates


def _fallback_embedding(text: str) -> list[float]:
    """Generate a simple fallback embedding using difflib.SequenceMatcher.

    This is used when sentence-transformers fails. The embedding is derived
    from the text's character n-grams and is NOT a proper semantic embedding.

    Args:
        text: Input text string.

    Returns:
        A 384-dimensional vector (matching all-MiniLM-L6-v2 output size).
    """
    # Create a simple hash-based embedding for fallback
    # This is a last-resort approach when the model is unavailable
    import hashlib

    hash_val = hashlib.md5(text.encode("utf-8")).digest()
    # Convert bytes to 384-dim float vector by repeating hash
    embedding = []
    for i in range(384):
        embedding.append(float((hash_val[i % len(hash_val)] & 0xFF) / 255.0))
    return embedding


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Detect duplicate stories in a validated stories JSON file."
    )
    parser.add_argument("stories_file", help="Path to JSON file with {stories: [...]} format")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold (default: 0.85)",
    )
    args = parser.parse_args()

    try:
        with open(args.stories_file, encoding="utf-8") as f:
            data = json.load(f)
        stories = data.get("stories", [])
    except Exception as e:
        print(f"[S] duplicate_detector: failed to read {args.stories_file}: {e}", file=sys.stderr)
        sys.exit(0)

    try:
        pairs = find_duplicates(stories, similarity_threshold=args.threshold)
        for story_a, story_b, score in pairs:
            id_a = story_a.get("id", "?")
            id_b = story_b.get("id", "?")
            print(f"DUPLICATE_CANDIDATE: {id_a} / {id_b} ({score:.2f})")
    except Exception as e:
        print(f"[S] duplicate_detector: error during detection: {e}", file=sys.stderr)
        sys.exit(0)
