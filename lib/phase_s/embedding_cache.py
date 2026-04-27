"""Embedding cache management for Phase S duplicate detection.

Provides functions to load and save embeddings to disk cache to avoid
recomputing embeddings for the same story titles across runs.

Cache format: JSONL with records like:
  {"title_hash": "abc123...", "title": "story title", "embedding": [0.1, 0.2, ...]}
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def compute_title_hash(title: str) -> str:
    """Compute SHA256 hash of story title for cache keying.

    Args:
        title: Story title string.

    Returns:
        Hexadecimal SHA256 hash of the title.
    """
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def load_cache(cache_path: str) -> dict[str, list[float]]:
    """Load embedding cache from JSONL file.

    Args:
        cache_path: Path to .spiral/embedding_cache.jsonl file.

    Returns:
        Dict mapping title_hash -> embedding vector.
        Returns empty dict if file doesn't exist or is unreadable.
    """
    cache: dict[str, list[float]] = {}
    if not os.path.isfile(cache_path):
        return cache

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                title_hash = record.get("title_hash")
                embedding = record.get("embedding")
                if title_hash and embedding:
                    cache[title_hash] = embedding
    except Exception:
        # On any error (corrupt file, parse error), return empty cache
        # and let caller recompute embeddings
        return {}

    return cache


def save_cache(
    cache_path: str,
    cache: dict[str, tuple[str, list[float]]],
) -> None:
    """Save embedding cache to JSONL file.

    Args:
        cache_path: Path to .spiral/embedding_cache.jsonl file.
        cache: Dict mapping title_hash -> (title, embedding) tuple.

    Creates parent directory if it doesn't exist. Appends new records
    to existing file (does not truncate).
    """
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)

    # Load existing cache to avoid duplicates
    existing = load_cache(cache_path)

    with open(cache_path, "a", encoding="utf-8") as f:
        for title_hash, (title, embedding) in cache.items():
            if title_hash not in existing:
                record = {
                    "title_hash": title_hash,
                    "title": title,
                    "embedding": embedding,
                }
                f.write(json.dumps(record) + "\n")
