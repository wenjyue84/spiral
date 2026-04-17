"""Tests for lib/history_search.py — FTS5 index + recall property test."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from history_search import build_index, find_similar_attempts
from results_tsv import ResultsRecord, write_results_tsv  # noqa: E402

# ── helpers ──────────────────────────────────────────────────────────────


def _make_tsv(path: str, records: list[ResultsRecord]) -> None:
    write_results_tsv(path, records)


def _make_record(story_id: str, title: str, status: str = "pass", failure_msg: str = "") -> ResultsRecord:
    return ResultsRecord(
        timestamp="2026-01-01T00:00:00Z",
        spiral_iter="1",
        ralph_iter="1",
        story_id=story_id,
        story_title=title,
        status=status,
        duration_sec="10",
        model="haiku",
        retry_num="0",
        commit_sha="abc123",
        run_id="run-1",
        failure_message=failure_msg,
    )


# ── unit tests ────────────────────────────────────────────────────────────


class TestBuildIndex:
    def test_creates_db_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            _make_tsv(tsv, [_make_record("US-1", "Add login feature")])
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            assert os.path.isfile(db)

    def test_empty_tsv_creates_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            _make_tsv(tsv, [])
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            hits = find_similar_attempts("anything", k=5, db_path=db)
            assert hits == []

    def test_missing_tsv_creates_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = os.path.join(tmpdir, "history.db")
            build_index(results_path=os.path.join(tmpdir, "missing.tsv"), db_path=db, root=tmpdir)
            hits = find_similar_attempts("test query", k=5, db_path=db)
            assert hits == []


class TestFindSimilarAttempts:
    def test_returns_empty_for_missing_db(self) -> None:
        hits = find_similar_attempts("query", k=5, db_path="/nonexistent/path.db")
        assert hits == []

    def test_returns_empty_for_blank_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            _make_tsv(tsv, [_make_record("US-1", "Fix bug")])
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            assert find_similar_attempts("  ", k=5, db_path=db) == []

    def test_basic_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            records = [
                _make_record("US-1", "Add authentication login"),
                _make_record("US-2", "Fix database migration error"),
            ]
            _make_tsv(tsv, records)
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            hits = find_similar_attempts("authentication login", k=5, db_path=db)
            assert len(hits) >= 1
            assert hits[0]["story_id"] == "US-1"

    def test_result_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            _make_tsv(tsv, [_make_record("US-1", "Deploy pipeline fix")])
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            hits = find_similar_attempts("pipeline", k=5, db_path=db)
            assert len(hits) == 1
            assert set(hits[0].keys()) >= {"story_id", "model", "outcome", "duration", "cost"}

    def test_invalid_fts_query_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv = os.path.join(tmpdir, "results.tsv")
            db = os.path.join(tmpdir, "history.db")
            _make_tsv(tsv, [_make_record("US-1", "something")])
            build_index(results_path=tsv, db_path=db, root=tmpdir)
            # FTS5 syntax error should not raise; return empty
            result = find_similar_attempts("OR OR AND", k=5, db_path=db)
            assert isinstance(result, list)


# ── property test: recall >= 0.8 at k=5 over N=50 synthetic rows ─────────


def _build_synthetic_dataset(n: int = 50) -> tuple[list[ResultsRecord], list[str]]:
    """Build N synthetic records with distinct, queryable titles."""
    import random

    rng = random.Random(42)

    topics = [
        "authentication oauth login",
        "database migration schema",
        "typescript compilation error",
        "deploy pipeline failure",
        "test coverage report",
        "api rate limit exceeded",
        "memory leak heap dump",
        "css styling regression",
        "websocket connection timeout",
        "caching redis invalidation",
    ]

    records = []
    queries: list[str] = []

    for i in range(n):
        topic = topics[i % len(topics)]
        words = topic.split()
        # Slight variation to simulate real-world diversity
        variant = rng.choice(words)
        title = f"Fix {variant} issue story US-{2000 + i}"
        status = rng.choice(["pass", "fail", "skip"])
        failure_msg = f"{variant} error in step {i}" if status == "fail" else ""
        records.append(_make_record(f"US-{2000 + i}", title, status, failure_msg))
        queries.append(variant)

    return records, queries


@pytest.mark.parametrize("seed", [42])
def test_recall_fifty_rows(seed: int) -> None:
    """Insert N=50 synthetic rows; assert recall >= 0.8 at k=5 for seeded queries."""
    import random

    n = 50
    records, queries = _build_synthetic_dataset(n)

    with tempfile.TemporaryDirectory() as tmpdir:
        tsv = os.path.join(tmpdir, "results.tsv")
        db = os.path.join(tmpdir, "history.db")
        _make_tsv(tsv, records)
        build_index(results_path=tsv, db_path=db, root=tmpdir)

        # Build expected mapping: query → set of story_ids whose title contains it
        rng = random.Random(seed)
        # Sample 20 unique queries to evaluate recall
        sample_queries = list(set(queries))[:20]
        rng.shuffle(sample_queries)
        sample_queries = sample_queries[:10]

        hits_total = 0
        for q in sample_queries:
            # Expected: at least one record containing the query word
            expected_ids = {rec.story_id for rec in records if q in rec.story_title.lower()}
            results = find_similar_attempts(q, k=5, db_path=db)
            returned_ids = {r["story_id"] for r in results}
            if expected_ids & returned_ids:
                hits_total += 1

        recall = hits_total / len(sample_queries)
        assert recall >= 0.8, f"Recall {recall:.2f} < 0.8 for {len(sample_queries)} queries"
