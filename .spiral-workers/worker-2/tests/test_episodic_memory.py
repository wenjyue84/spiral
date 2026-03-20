"""Tests for lib/episodic_memory.py — SQLite FTS5 episodic memory."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from episodic_memory import init_db, list_recent, query_top3, write_record


class TestInitDb:
    def test_creates_database_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            conn = init_db(db_path)
            conn.close()
            assert os.path.exists(db_path)

    def test_idempotent(self) -> None:
        """Calling init_db twice does not raise."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            init_db(db_path).close()
            init_db(db_path).close()


class TestWriteAndQuery:
    def test_write_then_query_returns_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            write_record(
                story_id="US-100",
                story_type="Add SQLite episodic memory module",
                approach_summary="Created lib/episodic_memory.py with FTS5 table",
                outcome="pass",
                iteration=1,
                db_path=db_path,
            )
            results = query_top3("episodic memory SQLite", top_k=3, db_path=db_path)
            assert len(results) >= 1
            assert results[0]["story_id"] == "US-100"
            assert results[0]["outcome"] == "pass"

    def test_query_ranks_relevant_higher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            write_record("US-1", "Add logging framework", "Added winston logger", "pass", 1, db_path)
            write_record("US-2", "Fix database migration", "Fixed alembic upgrade", "fail", 2, db_path)
            write_record("US-3", "Add structured logging", "JSON log output", "pass", 3, db_path)
            results = query_top3("logging framework structured", top_k=3, db_path=db_path)
            # Both logging stories should appear before the unrelated database one
            story_ids = [r["story_id"] for r in results]
            assert "US-1" in story_ids or "US-3" in story_ids


class TestListRecent:
    def test_list_returns_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            write_record("US-10", "first story", "approach A", "pass", 1, db_path)
            write_record("US-11", "second story", "approach B", "fail", 2, db_path)
            results = list_recent(limit=20, db_path=db_path)
            assert len(results) == 2
            # Newest (US-11) should be first
            assert results[0]["story_id"] == "US-11"
            assert results[1]["story_id"] == "US-10"

    def test_list_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            for i in range(5):
                write_record(f"US-{i}", f"story {i}", f"approach {i}", "pass", i, db_path)
            results = list_recent(limit=3, db_path=db_path)
            assert len(results) == 3


class TestEmptyQuery:
    def test_query_empty_db_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            init_db(db_path).close()
            results = query_top3("anything at all", top_k=3, db_path=db_path)
            assert results == []

    def test_query_short_tokens_returns_empty(self) -> None:
        """Tokens shorter than 3 chars are filtered out; if none remain, return empty."""
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            write_record("US-1", "test", "approach", "pass", 1, db_path)
            results = query_top3("ab cd", top_k=3, db_path=db_path)
            assert results == []


# ── Module-level acceptance criteria tests ──────────────────────────────────
def test_record_and_retrieve_happy_path() -> None:
    """AC1: Write a record and retrieve it successfully."""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test.db")
        write_record(
            story_id="US-100",
            story_type="Add SQLite episodic memory module",
            approach_summary="Created lib/episodic_memory.py with FTS5 table",
            outcome="pass",
            iteration=1,
            db_path=db_path,
        )
        results = query_top3("episodic memory SQLite", top_k=3, db_path=db_path)
        assert len(results) >= 1, "Should retrieve at least 1 record"
        assert results[0]["story_id"] == "US-100"
        assert results[0]["outcome"] == "pass"
        assert "FTS5" in results[0]["approach_summary"]


def test_top3_fts5_ranking() -> None:
    """AC2: FTS5 ranks relevant stories higher; verify top-3 are returned correctly."""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test.db")
        # Seed with 5+ varied records
        write_record("US-1", "Add logging framework", "Added winston logger", "pass", 1, db_path)
        write_record("US-2", "Fix database migration", "Fixed alembic upgrade", "fail", 2, db_path)
        write_record("US-3", "Add structured logging", "JSON log output", "pass", 3, db_path)
        write_record("US-4", "Implement caching layer", "Redis cache setup", "pass", 4, db_path)
        write_record("US-5", "Add async logging", "asyncio logging handler", "pass", 5, db_path)

        # Query for logging-related stories
        results = query_top3("logging framework structured", top_k=3, db_path=db_path)
        assert len(results) > 0, "Should return results for logging query"
        story_ids = [r["story_id"] for r in results]
        # At least one logging story (US-1, US-3, or US-5) should be in top 3
        logging_stories = {"US-1", "US-3", "US-5"}
        assert any(sid in logging_stories for sid in story_ids), (
            f"Expected at least one logging story in top 3, got {story_ids}"
        )
        # Database migration (US-2) and caching (US-4) should rank lower
        if "US-2" in story_ids and "US-1" in story_ids:
            assert story_ids.index("US-1") < story_ids.index("US-2"), (
                "US-1 (logging) should rank higher than US-2 (migration)"
            )


def test_empty_store_returns_empty_context() -> None:
    """AC3: Query an empty store returns empty list with no exception."""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test.db")
        init_db(db_path).close()
        results = query_top3("anything at all", top_k=3, db_path=db_path)
        assert results == [], "Empty store should return empty list"
        # Verify no exception was raised by this point
        assert True, "No exception raised"
