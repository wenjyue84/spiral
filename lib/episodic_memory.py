"""episodic_memory.py — JSONL-based episodic memory for Ralph workers.

Stores implementation patterns as structured JSON records with timestamps,
enabling recall of similar past solutions. Uses simple token-based embedding
and cosine similarity (no external ML dependencies) for pattern matching.

Usage:
    mem = EpisodicMemory('.spiral/episodic_memory.jsonl')
    mem.write('US-100', {'approach': '...', 'outcome': 'pass', ...})
    similar = mem.get_similar('US-100', k=3)
    deleted = mem.clear_expired(ttl_days=7)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class EpisodicMemory:
    """Pattern store with embedding-based similarity search."""

    def __init__(self, jsonl_path: str = ".spiral/episodic_memory.jsonl") -> None:
        """Initialize episodic memory store.

        Args:
            jsonl_path: Path to JSONL file for storage.
        """
        self.jsonl_path = jsonl_path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create parent directory if needed."""
        Path(self.jsonl_path).parent.mkdir(parents=True, exist_ok=True)

    def write(self, story_id: str, pattern_dict: dict[str, Any]) -> None:
        """Write a pattern record to the episodic memory store.

        Args:
            story_id: Story identifier (e.g., "US-100").
            pattern_dict: Pattern data including approach, outcome, etc.
        """
        self._ensure_storage()

        record = {
            "story_id": story_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **pattern_dict,
        }

        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_similar(self, story_id: str, k: int = 3) -> list[dict[str, Any]]:
        """Retrieve top-k similar patterns by embedding distance.

        Args:
            story_id: Story to find similar patterns for.
            k: Number of similar patterns to return.

        Returns:
            List of dicts with similar patterns, ranked by cosine similarity.
        """
        if not os.path.exists(self.jsonl_path):
            return []

        records = self._load_all_records()
        if not records:
            return []

        # Get reference pattern for the given story_id
        reference = None
        for rec in records:
            if rec.get("story_id") == story_id:
                reference = rec
                break

        if not reference:
            return []

        # Compute embedding-based similarity for all other records
        ref_embedding = self._embed(reference)
        similarities: list[tuple[float, dict[str, Any]]] = []

        for rec in records:
            if rec.get("story_id") == story_id:
                continue  # Skip the reference itself

            rec_embedding = self._embed(rec)
            sim = self._cosine_similarity(ref_embedding, rec_embedding)
            similarities.append((sim, rec))

        # Sort by similarity descending, return top-k
        similarities.sort(reverse=True, key=lambda x: x[0])
        return [rec for _sim, rec in similarities[:k]]

    def clear_expired(self, ttl_days: int = 7) -> int:
        """Remove records older than ttl_days.

        Args:
            ttl_days: Time-to-live in days.

        Returns:
            Number of records deleted.
        """
        if not os.path.exists(self.jsonl_path):
            return 0

        records = self._load_all_records()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=ttl_days)

        # Keep only non-expired records
        kept = []
        deleted = 0

        for rec in records:
            try:
                ts_str = rec.get("timestamp", "")
                ts = datetime.fromisoformat(ts_str)
                if ts > cutoff:
                    kept.append(rec)
                else:
                    deleted += 1
            except (ValueError, AttributeError):
                # Keep records with unparseable timestamps (conservative)
                kept.append(rec)

        # Write back only kept records
        with open(self.jsonl_path, "w", encoding="utf-8") as f:
            for rec in kept:
                f.write(json.dumps(rec) + "\n")

        return deleted

    def _load_all_records(self) -> list[dict[str, Any]]:
        """Load all records from JSONL file."""
        records: list[dict[str, Any]] = []
        if not os.path.exists(self.jsonl_path):
            return records

        try:
            with open(self.jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            # Skip malformed lines
                            continue
        except (OSError, IOError):
            pass

        return records

    @staticmethod
    def _embed(record: dict[str, Any]) -> dict[str, float]:
        """Compute simple token-based embedding from record fields.

        Treats all string values as tokens and counts frequency.
        """
        tokens: dict[str, float] = {}

        for value in record.values():
            if isinstance(value, str):
                # Tokenize by whitespace and normalize
                for token in value.lower().split():
                    # Strip punctuation and limit token length
                    token = "".join(c for c in token if c.isalnum())
                    if len(token) > 2:  # Ignore short tokens
                        tokens[token] = tokens.get(token, 0) + 1

        return tokens

    @staticmethod
    def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
        """Compute cosine similarity between two token-based embeddings.

        Returns value in [0, 1].
        """
        if not vec1 or not vec2:
            return 0.0

        # Compute dot product
        dot_product = 0.0
        for token, count1 in vec1.items():
            if token in vec2:
                dot_product += count1 * vec2[token]

        # Compute magnitudes
        mag1 = sum(c * c for c in vec1.values()) ** 0.5
        mag2 = sum(c * c for c in vec2.values()) ** 0.5

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return float(dot_product / (mag1 * mag2))


def list_recent(
    limit: int = 20,
    db_path: str | None = None,
    memory_path: str = ".spiral/episodic_memory.jsonl",
) -> list[dict[str, Any]]:
    """Return the most recent episodic memory records.

    Args:
        limit: Maximum number of records to return.
        db_path: Ignored (legacy compat). Uses memory_path instead.
        memory_path: Path to episodic memory JSONL file.

    Returns:
        List of dicts sorted by timestamp descending, up to limit.
    """
    mem = EpisodicMemory(memory_path)
    records = mem._load_all_records()
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit]


def get_similar_patterns(
    story_id: str, memory_path: str = ".spiral/episodic_memory.jsonl", k: int = 3
) -> list[dict[str, Any]]:
    """Convenience function for Phase I: get similar patterns by story_id.

    Args:
        story_id: Story to find similar patterns for.
        memory_path: Path to episodic memory JSONL.
        k: Number of patterns to return.

    Returns:
        List of similar patterns (top-k ranked by embedding distance).
    """
    mem = EpisodicMemory(memory_path)
    return mem.get_similar(story_id, k=k)
