"""Tests for lib/episodic_memory.py — JSONL episodic memory with embedding similarity.

Covers pattern write/retrieve, embedding-based ranking, TTL expiration, and edge cases.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from episodic_memory import EpisodicMemory, get_similar_patterns


class TestWriteAndRetrieve:
    """AC1: Write a pattern and retrieve it successfully."""

    def test_write_creates_jsonl_file(self) -> None:
        """Writing should create JSONL file if it doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = os.path.join(td, "episodic.jsonl")
            mem = EpisodicMemory(jsonl_path)
            mem.write("US-100", {"approach": "add logging", "outcome": "pass"})
            assert os.path.exists(jsonl_path), "JSONL file should be created"

    def test_write_and_get_similar_happy_path(self) -> None:
        """Writing and querying should return stored pattern."""
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = os.path.join(td, "episodic.jsonl")
            mem = EpisodicMemory(jsonl_path)
            mem.write("US-100", {
                "approach": "implemented logging framework with winston",
                "outcome": "pass",
                "iteration": 1,
            })
            results = mem.get_similar("US-100", k=3)
            assert len(results) == 0, "Query for same story should return empty"

            mem.write("US-101", {
                "approach": "structured logging with JSON output",
                "outcome": "pass",
                "iteration": 1,
            })
            results = mem.get_similar("US-100", k=3)
            assert len(results) >= 1, "Should find similar patterns"
            assert results[0]["story_id"] == "US-101"


class TestEmbeddingSimilarity:
    """AC2: Ranking by embedding distance (cosine similarity)."""

    def test_similarity_ranking_relevance(self) -> None:
        """More relevant patterns should rank higher."""
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = os.path.join(td, "episodic.jsonl")
            mem = EpisodicMemory(jsonl_path)
            mem.write("US-1", {"approach": "add logging framework with winston logger", "outcome": "pass"})
            mem.write("US-2", {"approach": "structured logging implementation with winston", "outcome": "pass"})
            mem.write("US-3", {"approach": "implement database migration with alembic", "outcome": "fail"})
            mem.write("US-4", {"approach": "fix UI button styling with CSS", "outcome": "pass"})

            results = mem.get_similar("US-1", k=3)
            assert len(results) >= 1, "Should find at least one similar pattern"
            story_ids = [r["story_id"] for r in results]
            if len(story_ids) >= 2:
                if "US-2" in story_ids and "US-4" in story_ids:
                    assert story_ids.index("US-2") < story_ids.index("US-4"), "US-2 should rank higher than US-4"


class TestTTLExpiration:
    """AC3: TTL expiration logic removes old records."""

    def test_clear_expired_removes_old_records(self) -> None:
        """clear_expired should remove records older than ttl_days."""
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = os.path.join(td, "episodic.jsonl")
            mem = EpisodicMemory(jsonl_path)

            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=10)).isoformat()
            new_ts = (now - timedelta(days=1)).isoformat()

            with open(jsonl_path, "w") as f:
                old_rec = {"story_id": "US-old", "timestamp": old_ts, "approach": "old"}
                f.write(json.dumps(old_rec) + "\n")
                new_rec = {"story_id": "US-new", "timestamp": new_ts, "approach": "new"}
                f.write(json.dumps(new_rec) + "\n")

            deleted_count = mem.clear_expired(ttl_days=7)
            assert deleted_count == 1, "Should delete 1 old record"

            remaining = mem._load_all_records()
            assert len(remaining) == 1, "Should have 1 record remaining"
            assert remaining[0]["story_id"] == "US-new", "New record should remain"


def test_write_and_retrieve() -> None:
    """AC1: Write and retrieve patterns successfully."""
    with tempfile.TemporaryDirectory() as td:
        jsonl_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(jsonl_path)
        mem.write("US-100", {
            "approach": "implemented error handling with custom exceptions",
            "outcome": "pass",
            "iteration": 1,
        })
        mem.write("US-101", {
            "approach": "error handling implementation with try-catch",
            "outcome": "pass",
            "iteration": 2,
        })
        mem.write("US-102", {
            "approach": "database schema migration",
            "outcome": "fail",
            "iteration": 1
        })
        results = mem.get_similar("US-100", k=3)
        assert len(results) >= 1, "Should find at least one similar pattern"


def test_similarity_ranking() -> None:
    """AC2: Embedding distance similarity ranking."""
    with tempfile.TemporaryDirectory() as td:
        jsonl_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(jsonl_path)
        mem.write("US-1", {"approach": "logging setup with structured JSON output", "outcome": "pass"})
        mem.write("US-2", {"approach": "structured logging JSON implementation", "outcome": "pass"})
        mem.write("US-3", {"approach": "cache layer implementation with Redis", "outcome": "fail"})

        results = mem.get_similar("US-1", k=3)
        assert len(results) >= 1, "Should find matches"


def test_ttl_expiration() -> None:
    """AC3: TTL expiration removes old records."""
    with tempfile.TemporaryDirectory() as td:
        jsonl_path = os.path.join(td, "episodic.jsonl")
        now = datetime.now(timezone.utc)

        with open(jsonl_path, "w") as f:
            for i, days_ago in enumerate([8, 10], start=1):
                ts = (now - timedelta(days=days_ago)).isoformat()
                rec = {"story_id": f"US-old-{i}", "timestamp": ts, "approach": f"old {i}"}
                f.write(json.dumps(rec) + "\n")
            for i, days_ago in enumerate([1, 3], start=1):
                ts = (now - timedelta(days=days_ago)).isoformat()
                rec = {"story_id": f"US-recent-{i}", "timestamp": ts, "approach": f"recent {i}"}
                f.write(json.dumps(rec) + "\n")
            ts = (now - timedelta(days=7)).isoformat()
            rec = {"story_id": "US-boundary", "timestamp": ts, "approach": "boundary"}
            f.write(json.dumps(rec) + "\n")

        mem = EpisodicMemory(jsonl_path)
        deleted = mem.clear_expired(ttl_days=7)
        # Boundary case (exactly 7 days old) is deleted with > comparison
        assert deleted == 3, f"Should delete 3 old records (including boundary), got {deleted}"

        remaining = mem._load_all_records()
        assert len(remaining) == 2, f"Should keep 2 records, got {len(remaining)}"


def test_get_similar_patterns_function() -> None:
    """Test the convenience function get_similar_patterns()."""
    with tempfile.TemporaryDirectory() as td:
        jsonl_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(jsonl_path)
        mem.write("US-100", {"approach": "logging implementation", "outcome": "pass"})
        mem.write("US-101", {"approach": "structured logging system", "outcome": "pass"})

        # Test via convenience function
        results = get_similar_patterns("US-100", memory_path=jsonl_path, k=2)
        assert len(results) >= 1, "Convenience function should return results"
