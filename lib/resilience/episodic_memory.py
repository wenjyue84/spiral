"""episodic_memory.py — JSONL episodic memory with embedding-based similarity search.

Stores story implementation patterns so future workers can recall how similar stories
were implemented. Uses sentence-transformers for embedding-based cosine similarity
ranking and TTL-based expiration for automatic cleanup.

Usage (Python):
    from episodic_memory import EpisodicMemory, get_similar_patterns

    mem = EpisodicMemory(".spiral/episodic_memory.jsonl")
    mem.write("US-100", {"approach": "add logging", "outcome": "pass"})
    similar = mem.get_similar("US-100", k=3)
    expired = mem.clear_expired(ttl_days=7)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# Try to import sentence-transformers; fall back to simple embedding if unavailable
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_MODEL: SentenceTransformer | None = None
    _embedding_model_available = True
except ImportError:
    _embedding_model_available = False
    EMBEDDING_MODEL = None  # type: ignore


def _get_embedding_model() -> SentenceTransformer:
    """Lazy-load the embedding model on first use."""
    global EMBEDDING_MODEL
    if EMBEDDING_MODEL is None:
        EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return EMBEDDING_MODEL


def _embed_text(text: str) -> list[float]:
    """Generate embedding for text using sentence-transformers."""
    if not _embedding_model_available:
        # Fallback: simple hash-based "embedding" (not ideal but allows testing)
        hash_val = hash(text)
        # Create a 384-dim pseudo-embedding from hash
        rng = np.random.RandomState(hash_val % (2**31))
        return rng.randn(384).tolist()

    model = _get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    v1 = np.array(vec1, dtype=np.float32)
    v2 = np.array(vec2, dtype=np.float32)

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)

    if norm1 < 1e-9 or norm2 < 1e-9:
        return 0.0

    return float(np.dot(v1, v2) / (norm1 * norm2))


class EpisodicMemory:
    """JSONL-based episodic memory with embedding similarity."""

    def __init__(self, jsonl_path: str) -> None:
        """Initialize episodic memory with a JSONL file path."""
        self.jsonl_path = jsonl_path
        # Ensure parent directory exists
        Path(jsonl_path).parent.mkdir(parents=True, exist_ok=True)

    def write(self, story_id: str, pattern_dict: dict[str, object]) -> None:
        """Write a pattern to the episodic memory.

        Args:
            story_id: Story identifier (e.g., "US-100")
            pattern_dict: Dictionary with keys like "approach", "outcome", "iteration"
        """
        record = {
            "story_id": story_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "approach": pattern_dict.get("approach", ""),
            "outcome": pattern_dict.get("outcome", ""),
            "iteration": pattern_dict.get("iteration", 0),
        }

        # Compute embedding for the approach text
        approach_text = str(pattern_dict.get("approach", ""))
        record["embedding"] = _embed_text(approach_text)

        # Append to JSONL file
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def get_similar(self, story_id: str, k: int = 3) -> list[dict[str, object]]:
        """Retrieve top-k similar patterns by embedding distance.

        Args:
            story_id: Story ID to find similar patterns for (we skip records with same ID)
            k: Number of results to return

        Returns:
            List of dicts with story_id, approach, outcome, iteration, timestamp, similarity
        """
        # Load all records
        all_records = self._load_all_records()
        if not all_records:
            return []

        # Find the target record (skip if not found)
        target_embedding = None
        for record in all_records:
            if record["story_id"] == story_id:
                # We skip records with the same story_id
                break

        # If we have no target, compute embedding from scratch (shouldn't happen in normal use)
        if target_embedding is None and all_records:
            # Use the first non-matching record as fallback
            for record in all_records:
                if record["story_id"] != story_id:
                    target_embedding = record.get("embedding", [])
                    break

        if target_embedding is None:
            return []

        # Compute similarities for all records (excluding same story_id)
        candidates: list[tuple[dict[str, object], float]] = []
        for record in all_records:
            if record["story_id"] == story_id:
                continue

            embedding = record.get("embedding", [])
            if embedding:
                similarity = _cosine_similarity(target_embedding, embedding)
                candidates.append((record, similarity))

        # Sort by similarity (descending) and return top-k
        candidates.sort(key=lambda x: x[1], reverse=True)
        results: list[dict[str, object]] = []
        for record, similarity in candidates[:k]:
            result = dict(record)
            result["similarity"] = similarity
            # Remove embedding from output (too large for display)
            result.pop("embedding", None)
            results.append(result)

        return results

    def clear_expired(self, ttl_days: int = 7) -> int:
        """Remove records older than ttl_days.

        Args:
            ttl_days: Age threshold in days; older records are deleted

        Returns:
            Number of records deleted
        """
        all_records = self._load_all_records()
        if not all_records:
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=ttl_days)

        remaining: list[dict[str, object]] = []
        deleted_count = 0

        for record in all_records:
            try:
                ts_str = record.get("timestamp", "")
                if isinstance(ts_str, str):
                    # Parse ISO format timestamp
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        remaining.append(record)
                    else:
                        deleted_count += 1
                else:
                    remaining.append(record)
            except (ValueError, AttributeError):
                remaining.append(record)

        # Rewrite JSONL file with non-expired records
        with open(self.jsonl_path, "w") as f:
            for record in remaining:
                f.write(json.dumps(record) + "\n")

        return deleted_count

    def _load_all_records(self) -> list[dict[str, object]]:
        """Load all records from the JSONL file."""
        if not os.path.exists(self.jsonl_path):
            return []

        records: list[dict[str, object]] = []
        try:
            with open(self.jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        records.append(record)
        except (IOError, json.JSONDecodeError):
            pass

        return records


def get_similar_patterns(
    story_id: str,
    k: int = 3,
    jsonl_path: str = ".spiral/episodic_memory.jsonl",
) -> list[dict[str, object]]:
    """Retrieve similar patterns for a story (convenience function).

    Args:
        story_id: Story ID to find similar patterns for
        k: Number of results to return
        jsonl_path: Path to episodic memory JSONL file

    Returns:
        List of similar pattern records
    """
    mem = EpisodicMemory(jsonl_path)
    return mem.get_similar(story_id, k=k)
