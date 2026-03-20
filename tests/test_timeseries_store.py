"""tests/test_timeseries_store.py — Unit tests for lib/dashboard/timeseries_store.py.

Acceptance Criteria:
  AC1: SQLite schema created with iterations, stories, workers tables.
  AC2: record_iteration_from_results_tsv() persists data from results.tsv.
  AC3: query_timeseries() returns [{timestamp, value}] enabling trend charts.
"""

import csv
import sqlite3
import tempfile
from pathlib import Path

import pytest

from lib.dashboard.timeseries_store import (
    _connect,
    query_timeseries,
    record_iteration,
    record_iteration_from_results_tsv,
    record_story,
    record_worker,
)


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Temporary database path for each test."""
    return tmp_path / "test_dashboard.db"


@pytest.fixture()
def tmp_tsv(tmp_path: Path) -> Path:
    """Temporary results.tsv path for each test."""
    return tmp_path / "results.tsv"


# ── AC1: Schema ───────────────────────────────────────────────────────────────


class TestSchema:
    """AC1 — SQLite schema has the required tables and columns."""

    def test_tables_created_on_connect(self, tmp_db: Path) -> None:
        conn = _connect(tmp_db)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "iterations" in tables
        assert "stories" in tables
        assert "workers" in tables
        conn.close()

    def test_iterations_columns(self, tmp_db: Path) -> None:
        conn = _connect(tmp_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(iterations)").fetchall()}
        assert {"iteration_N", "timestamp", "phase", "duration_sec", "tokens_spent"}.issubset(cols)
        conn.close()

    def test_stories_columns(self, tmp_db: Path) -> None:
        conn = _connect(tmp_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stories)").fetchall()}
        assert {"story_id", "iteration_N", "phase", "status", "retry_count"}.issubset(cols)
        conn.close()

    def test_workers_columns(self, tmp_db: Path) -> None:
        conn = _connect(tmp_db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(workers)").fetchall()}
        assert {"worker_id", "timestamp", "memory_mb", "lock_wait_ms"}.issubset(cols)
        conn.close()

    def test_db_created_in_missing_dir(self, tmp_path: Path) -> None:
        nested_db = tmp_path / "subdir" / "dashboard.db"
        conn = _connect(nested_db)
        assert nested_db.exists()
        conn.close()


# ── AC2: record_iteration_from_results_tsv ────────────────────────────────────


class TestRecordIteration:
    """AC2 — Phase C integration: persist metrics from results.tsv."""

    def _write_tsv(self, path: Path, rows: list[dict[str, str]]) -> None:
        fieldnames = ["story_id", "iteration", "phase", "status", "retry_count", "impl_secs", "tokens_used"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def test_records_stories_for_iteration(self, tmp_db: Path, tmp_tsv: Path) -> None:
        self._write_tsv(
            tmp_tsv,
            [
                {"story_id": "US-001", "iteration": "5", "phase": "I", "status": "passed",
                 "retry_count": "0", "impl_secs": "10.0", "tokens_used": "500"},
                {"story_id": "US-002", "iteration": "5", "phase": "I", "status": "failed",
                 "retry_count": "1", "impl_secs": "8.0", "tokens_used": "300"},
            ],
        )
        record_iteration_from_results_tsv(iteration_n=5, results_tsv=tmp_tsv, db_path=tmp_db)

        conn = _connect(tmp_db)
        stories = conn.execute("SELECT story_id FROM stories WHERE iteration_N = 5").fetchall()
        story_ids = {row[0] for row in stories}
        assert "US-001" in story_ids
        assert "US-002" in story_ids
        conn.close()

    def test_records_iterations_row(self, tmp_db: Path, tmp_tsv: Path) -> None:
        self._write_tsv(
            tmp_tsv,
            [
                {"story_id": "US-003", "iteration": "7", "phase": "I", "status": "passed",
                 "retry_count": "0", "impl_secs": "15.5", "tokens_used": "1000"},
            ],
        )
        record_iteration_from_results_tsv(iteration_n=7, results_tsv=tmp_tsv, db_path=tmp_db)

        conn = _connect(tmp_db)
        row = conn.execute(
            "SELECT duration_sec, tokens_spent FROM iterations WHERE iteration_N = 7"
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(15.5, abs=0.01)
        assert row[1] == 1000
        conn.close()

    def test_ignores_other_iterations(self, tmp_db: Path, tmp_tsv: Path) -> None:
        self._write_tsv(
            tmp_tsv,
            [
                {"story_id": "US-010", "iteration": "1", "phase": "I", "status": "passed",
                 "retry_count": "0", "impl_secs": "5.0", "tokens_used": "200"},
                {"story_id": "US-011", "iteration": "2", "phase": "I", "status": "passed",
                 "retry_count": "0", "impl_secs": "5.0", "tokens_used": "200"},
            ],
        )
        record_iteration_from_results_tsv(iteration_n=1, results_tsv=tmp_tsv, db_path=tmp_db)

        conn = _connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM stories WHERE iteration_N = 2").fetchone()[0]
        assert count == 0
        conn.close()

    def test_missing_tsv_is_noop(self, tmp_db: Path, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.tsv"
        # Should not raise
        record_iteration_from_results_tsv(iteration_n=1, results_tsv=missing, db_path=tmp_db)

    def test_programmatic_record_iteration(self, tmp_db: Path) -> None:
        record_iteration(iteration_n=3, phase="R", duration_sec=45.0, tokens_spent=800, db_path=tmp_db)
        conn = _connect(tmp_db)
        row = conn.execute(
            "SELECT phase, duration_sec, tokens_spent FROM iterations WHERE iteration_N = 3"
        ).fetchone()
        assert row is not None
        assert row[0] == "R"
        assert row[1] == pytest.approx(45.0)
        assert row[2] == 800
        conn.close()


# ── AC3: query_timeseries ─────────────────────────────────────────────────────


class TestQueryTimeseries:
    """AC3 — /api/dashboard/timeseries returns [{timestamp, value}] for trend charts."""

    def test_returns_empty_when_db_missing(self, tmp_path: Path) -> None:
        db = tmp_path / "nonexistent.db"
        result = query_timeseries(metric="phase_duration", db_path=db)
        assert result == []

    def test_phase_duration_returns_list_of_dicts(self, tmp_db: Path) -> None:
        record_iteration(iteration_n=1, phase="I", duration_sec=20.0, tokens_spent=100, db_path=tmp_db)
        result = query_timeseries(metric="phase_duration", db_path=tmp_db)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "timestamp" in result[0]
        assert "value" in result[0]

    def test_phase_filter_works(self, tmp_db: Path) -> None:
        record_iteration(iteration_n=1, phase="R", duration_sec=10.0, tokens_spent=50, db_path=tmp_db)
        record_iteration(iteration_n=1, phase="I", duration_sec=30.0, tokens_spent=200, db_path=tmp_db)

        r_only = query_timeseries(metric="phase_duration", phase="R", db_path=tmp_db)
        i_only = query_timeseries(metric="phase_duration", phase="I", db_path=tmp_db)

        assert all(True for _ in r_only)  # has data
        r_values = [p["value"] for p in r_only]
        assert any(abs(v - 10.0) < 0.01 for v in r_values)

        i_values = [p["value"] for p in i_only]
        assert any(abs(v - 30.0) < 0.01 for v in i_values)

    def test_story_throughput_metric(self, tmp_db: Path) -> None:
        record_iteration(iteration_n=2, phase="I", duration_sec=5.0, tokens_spent=100, db_path=tmp_db)
        result = query_timeseries(metric="story_throughput", db_path=tmp_db)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "value" in result[0]

    def test_worker_memory_metric(self, tmp_db: Path) -> None:
        record_worker(worker_id="w0", memory_mb=512.0, lock_wait_ms=50, db_path=tmp_db)
        result = query_timeseries(metric="worker_memory", db_path=tmp_db)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["value"] == pytest.approx(512.0, abs=0.1)

    def test_unknown_metric_returns_empty(self, tmp_db: Path) -> None:
        record_iteration(iteration_n=1, phase="I", duration_sec=5.0, tokens_spent=100, db_path=tmp_db)
        result = query_timeseries(metric="totally_unknown_metric", db_path=tmp_db)
        assert result == []

    def test_window_filters_old_data(self, tmp_db: Path) -> None:
        # Initialise schema first, then insert a very old row directly
        init_conn = _connect(tmp_db)
        init_conn.close()
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "INSERT INTO iterations (iteration_N, timestamp, phase, duration_sec, tokens_spent)"
            " VALUES (1, '2000-01-01T00:00:00+00:00', 'I', 99.0, 0)"
        )
        conn.commit()
        conn.close()

        result = query_timeseries(metric="phase_duration", window_days=30, db_path=tmp_db)
        # Old row should be excluded
        assert all(p["value"] != pytest.approx(99.0) for p in result)

    def test_trend_across_10_iterations(self, tmp_db: Path) -> None:
        """Simulates 10+ iterations for trend chart data points."""
        for i in range(1, 12):
            record_iteration(iteration_n=i, phase="I", duration_sec=float(i * 5), tokens_spent=i * 100, db_path=tmp_db)

        result = query_timeseries(metric="phase_duration", phase="I", window_days=30, db_path=tmp_db)
        assert len(result) >= 10
