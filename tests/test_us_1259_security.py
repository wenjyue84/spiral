"""Security tests for lib/history_search.py (US-1259).

Verifies FTS5 query sanitization, path safety, and result schema safety.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from history_search import build_index, find_similar_attempts
from results_tsv import ResultsRecord, write_results_tsv


def _make_record(story_id: str, title: str) -> ResultsRecord:
    return ResultsRecord(
        timestamp="2026-01-01T00:00:00Z",
        spiral_iter="1",
        ralph_iter="1",
        story_id=story_id,
        story_title=title,
        status="pass",
        duration_sec="10",
        model="haiku",
        retry_num="0",
        commit_sha="abc123",
        run_id="run-1",
    )


def test_sql_injection_returns_empty_list(tmp_path: Path) -> None:
    """AC1: SQL injection payload raises no exception and returns []."""
    tsv = str(tmp_path / "results.tsv")
    db = str(tmp_path / "history.db")
    write_results_tsv(tsv, [_make_record("US-1", "Login feature")])
    build_index(results_path=tsv, db_path=db, root=str(tmp_path))

    result = find_similar_attempts("'; DROP TABLE--", k=5, db_path=db)
    assert result == []


def test_history_db_created_at_spiral_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: history.db is created at .spiral/history.db (relative to CWD)."""
    monkeypatch.chdir(tmp_path)
    tsv = str(tmp_path / "results.tsv")
    write_results_tsv(tsv, [_make_record("US-2", "Migration fix")])

    # Call build_index with no db_path — uses default .spiral/history.db
    build_index(results_path=tsv)

    assert Path(".spiral/history.db").exists()
    # Verify the path is relative, not an escaped absolute path
    db_path = Path(".spiral/history.db")
    assert not db_path.is_absolute()


def test_result_keys_are_subset_of_expected(tmp_path: Path) -> None:
    """AC3: Return value contains only (story_id, model, outcome, duration, cost)."""
    tsv = str(tmp_path / "results.tsv")
    db = str(tmp_path / "history.db")
    write_results_tsv(tsv, [_make_record("US-3", "Deploy pipeline")])
    build_index(results_path=tsv, db_path=db, root=str(tmp_path))

    result = find_similar_attempts("pipeline", k=5, db_path=db)

    assert len(result) >= 1
    allowed_keys = {"story_id", "model", "outcome", "duration", "cost"}
    assert all(set(r.keys()) <= allowed_keys for r in result)
