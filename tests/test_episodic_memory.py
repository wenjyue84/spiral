"""Tests for lib/episodic_memory.py — JSONL-based episodic memory."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from episodic_memory import EpisodicMemory, list_recent


def _write_record(
    mem: EpisodicMemory,
    story_id: str,
    story_type: str,
    approach_summary: str,
    outcome: str,
    iteration: int,
) -> None:
    """Helper matching old write_record signature for test convenience."""
    mem.write(
        story_id,
        {
            "story_type": story_type,
            "approach_summary": approach_summary,
            "outcome": outcome,
            "iteration": iteration,
        },
    )


class TestInit:
    def test_creates_storage_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            _write_record(mem, "US-1", "test", "approach", "pass", 1)
            assert os.path.exists(path)

    def test_idempotent(self) -> None:
        """Creating EpisodicMemory twice does not raise."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            EpisodicMemory(path)
            EpisodicMemory(path)


class TestWriteAndQuery:
    def test_write_then_query_returns_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            _write_record(
                mem,
                story_id="US-100",
                story_type="Add episodic memory module",
                approach_summary="Created lib/episodic_memory.py with JSONL store",
                outcome="pass",
                iteration=1,
            )
            results = mem.query_by_text("episodic memory", k=3)
            assert len(results) >= 1
            assert results[0]["story_id"] == "US-100"
            assert results[0]["outcome"] == "pass"

    def test_query_ranks_relevant_higher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            _write_record(mem, "US-1", "Add logging framework", "Added winston logger", "pass", 1)
            _write_record(mem, "US-2", "Fix database migration", "Fixed alembic upgrade", "fail", 2)
            _write_record(mem, "US-3", "Add structured logging", "JSON log output", "pass", 3)
            results = mem.query_by_text("logging framework structured", k=3)
            story_ids = [r["story_id"] for r in results]
            assert "US-1" in story_ids or "US-3" in story_ids


class TestListRecent:
    def test_list_returns_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            _write_record(mem, "US-10", "first story", "approach A", "pass", 1)
            _write_record(mem, "US-11", "second story", "approach B", "fail", 2)
            results = list_recent(limit=20, memory_path=path)
            assert len(results) == 2
            assert results[0]["story_id"] == "US-11"
            assert results[1]["story_id"] == "US-10"

    def test_list_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            for i in range(5):
                _write_record(mem, f"US-{i}", f"story {i}", f"approach {i}", "pass", i)
            results = list_recent(limit=3, memory_path=path)
            assert len(results) == 3


class TestEmptyQuery:
    def test_query_empty_store_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            results = mem.query_by_text("anything at all", k=3)
            assert results == []

    def test_query_short_tokens_returns_zero_similarity(self) -> None:
        """Tokens shorter than 3 chars are filtered out; empty embedding yields 0 similarity."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "mem.jsonl")
            mem = EpisodicMemory(path)
            _write_record(mem, "US-1", "test", "approach", "pass", 1)
            query_embedding = EpisodicMemory._embed({"_query": "ab cd"})
            assert query_embedding == {}


def test_record_and_retrieve_happy_path() -> None:
    """AC1: Write a record and retrieve it successfully."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        _write_record(
            mem,
            story_id="US-100",
            story_type="Add episodic memory module",
            approach_summary="Created lib/episodic_memory.py with JSONL store",
            outcome="pass",
            iteration=1,
        )
        results = mem.query_by_text("episodic memory", k=3)
        assert len(results) >= 1, "Should retrieve at least 1 record"
        assert results[0]["story_id"] == "US-100"
        assert results[0]["outcome"] == "pass"
        assert "JSONL" in results[0]["approach_summary"]


def test_top3_similarity_ranking() -> None:
    """AC2: Similarity ranks relevant stories higher; verify top-3 are returned correctly."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        _write_record(mem, "US-1", "Add logging framework", "Added winston logger", "pass", 1)
        _write_record(mem, "US-2", "Fix database migration", "Fixed alembic upgrade", "fail", 2)
        _write_record(mem, "US-3", "Add structured logging", "JSON log output", "pass", 3)
        _write_record(mem, "US-4", "Implement caching layer", "Redis cache setup", "pass", 4)
        _write_record(mem, "US-5", "Add async logging", "asyncio logging handler", "pass", 5)

        results = mem.query_by_text("logging framework structured", k=3)
        assert len(results) > 0, "Should return results for logging query"
        story_ids = [r["story_id"] for r in results]
        logging_stories = {"US-1", "US-3", "US-5"}
        assert any(sid in logging_stories for sid in story_ids), (
            f"Expected at least one logging story in top 3, got {story_ids}"
        )


def test_empty_store_returns_empty_context() -> None:
    """AC3: Query an empty store returns empty list with no exception."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        results = mem.query_by_text("anything at all", k=3)
        assert results == [], "Empty store should return empty list"
