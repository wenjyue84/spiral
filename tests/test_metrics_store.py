"""Tests for SQLiteMetricsStore (US-1051).

Validates:
- AC1: insert_from_results_tsv() ingests results.tsv rows correctly
- AC2: query_by_date_range() returns JSON array and executes quickly
- AC3: Response includes all fields needed for cost trend plotting
"""

import csv
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from metrics_store import SQLiteMetricsStore


def _write_results_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a minimal results.tsv file."""
    fieldnames = [
        "timestamp",
        "spiral_iter",
        "ralph_iter",
        "story_id",
        "story_title",
        "status",
        "duration_sec",
        "model",
        "retry_num",
        "commit_sha",
        "run_id",
        "cache_hit",
        "cache_read_tokens",
        "cache_creation_tokens",
        "review_tokens",
        "wall_seconds",
        "user_cpu_s",
        "sys_cpu_s",
        "peak_rss_kb",
        "batch_id",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Fill defaults for missing fields
            full_row = {f: "" for f in fieldnames}
            full_row.update(row)
            writer.writerow(full_row)


# ── AC1: insert_from_results_tsv ─────────────────────────────────────────────


class TestInsertFromResultsTSV:
    def test_inserts_basic_row(self, tmp_path: Path) -> None:
        """A single TSV row should be stored with correct fields."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-20T04:00:40Z",
                    "spiral_iter": "3",
                    "duration_sec": "292",
                    "cache_read_tokens": "894414",
                    "cache_creation_tokens": "56415",
                    "review_tokens": "0",
                }
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        inserted = store.insert_from_results_tsv(tsv)

        assert inserted == 1
        rows = store.query_by_date_range("2026-03-20", "2026-03-20")
        assert len(rows) == 1
        row = rows[0]
        assert row["timestamp"] == "2026-03-20T04:00:40Z"
        assert row["iteration"] == 3
        assert row["phase"] == "I"
        assert row["cost_tokens"] == 894414 + 56415 + 0
        assert row["duration_sec"] == pytest.approx(292.0)

    def test_inserts_multiple_rows(self, tmp_path: Path) -> None:
        """Multiple rows are all stored."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-20T04:00:40Z",
                    "spiral_iter": "3",
                    "duration_sec": "100",
                    "cache_read_tokens": "1000",
                    "cache_creation_tokens": "200",
                    "review_tokens": "50",
                },
                {
                    "timestamp": "2026-03-21T10:00:00Z",
                    "spiral_iter": "4",
                    "duration_sec": "200",
                    "cache_read_tokens": "2000",
                    "cache_creation_tokens": "400",
                    "review_tokens": "100",
                },
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        inserted = store.insert_from_results_tsv(tsv)
        assert inserted == 2

        rows = store.query_by_date_range("2026-03-20", "2026-03-22")
        assert len(rows) == 2

    def test_cost_tokens_is_sum(self, tmp_path: Path) -> None:
        """cost_tokens = cache_read_tokens + cache_creation_tokens + review_tokens."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-22T00:00:00Z",
                    "spiral_iter": "5",
                    "duration_sec": "10",
                    "cache_read_tokens": "100",
                    "cache_creation_tokens": "200",
                    "review_tokens": "300",
                }
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)
        rows = store.query_by_date_range("2026-03-22", "2026-03-22")
        assert rows[0]["cost_tokens"] == 600

    def test_missing_tsv_returns_zero(self, tmp_path: Path) -> None:
        """Returns 0 if results.tsv doesn't exist."""
        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        inserted = store.insert_from_results_tsv(tmp_path / "missing.tsv")
        assert inserted == 0

    def test_malformed_values_default_to_zero(self, tmp_path: Path) -> None:
        """Non-integer token values should default to 0, not crash."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-22T00:00:00Z",
                    "spiral_iter": "bad",
                    "duration_sec": "not_a_float",
                    "cache_read_tokens": "bad_value",
                    "cache_creation_tokens": "",
                    "review_tokens": "",
                }
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        inserted = store.insert_from_results_tsv(tsv)
        assert inserted == 1
        rows = store.query_by_date_range("2026-03-22", "2026-03-22")
        assert rows[0]["cost_tokens"] == 0
        assert rows[0]["duration_sec"] == pytest.approx(0.0)
        assert rows[0]["iteration"] == 0


# ── AC2: Date-range query performance ────────────────────────────────────────


class TestQueryByDateRange:
    def test_filters_by_start_and_end(self, tmp_path: Path) -> None:
        """Only rows within the date range are returned."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {"timestamp": "2026-03-19T23:59:59Z", "spiral_iter": "1", "duration_sec": "10"},
                {"timestamp": "2026-03-20T00:00:00Z", "spiral_iter": "2", "duration_sec": "20"},
                {"timestamp": "2026-03-26T23:59:59Z", "spiral_iter": "3", "duration_sec": "30"},
                {"timestamp": "2026-03-27T00:00:01Z", "spiral_iter": "4", "duration_sec": "40"},
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)

        rows = store.query_by_date_range("2026-03-20", "2026-03-26")
        # Only iterations 2 and 3 fall in the range
        iterations = [r["iteration"] for r in rows]
        assert 2 in iterations
        assert 3 in iterations
        assert 1 not in iterations
        assert 4 not in iterations

    def test_returns_empty_for_missing_db(self, tmp_path: Path) -> None:
        """Returns [] when the database doesn't exist."""
        store = SQLiteMetricsStore(db_path=tmp_path / "nonexistent.db")
        # Don't call _init_db to simulate missing db
        store.db_path = tmp_path / "really_missing.db"
        rows = store.query_by_date_range("2026-03-20", "2026-03-27")
        assert rows == []

    def test_7day_query_under_100ms(self, tmp_path: Path) -> None:
        """Query for 7-day range should execute in < 100ms (AC2)."""
        tsv = tmp_path / "results.tsv"
        # Generate 200 rows spanning 7 days
        test_rows = [
            {
                "timestamp": f"2026-03-{20 + (i % 7):02d}T{i % 24:02d}:00:00Z",
                "spiral_iter": str(i),
                "duration_sec": str(i * 2),
                "cache_read_tokens": str(i * 100),
                "cache_creation_tokens": str(i * 50),
                "review_tokens": "0",
            }
            for i in range(200)
        ]
        _write_results_tsv(tsv, test_rows)

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)

        start = time.perf_counter()
        rows = store.query_by_date_range("2026-03-20", "2026-03-27")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(rows) > 0
        assert elapsed_ms < 100, f"Query took {elapsed_ms:.1f}ms (limit: 100ms)"

    def test_ordered_by_timestamp_ascending(self, tmp_path: Path) -> None:
        """Results are ordered by timestamp ascending."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {"timestamp": "2026-03-22T12:00:00Z", "spiral_iter": "2"},
                {"timestamp": "2026-03-22T06:00:00Z", "spiral_iter": "1"},
                {"timestamp": "2026-03-22T18:00:00Z", "spiral_iter": "3"},
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)
        rows = store.query_by_date_range("2026-03-22", "2026-03-22")
        timestamps = [r["timestamp"] for r in rows]
        assert timestamps == sorted(timestamps)


# ── AC3: Response schema for frontend plotting ────────────────────────────────


class TestResponseSchemaForFrontend:
    def test_all_required_fields_present(self, tmp_path: Path) -> None:
        """Each row must include timestamp, iteration, phase, cost_tokens, duration_sec."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-22T10:00:00Z",
                    "spiral_iter": "3",
                    "duration_sec": "150",
                    "cache_read_tokens": "5000",
                    "cache_creation_tokens": "1000",
                    "review_tokens": "500",
                }
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)
        rows = store.query_by_date_range("2026-03-22", "2026-03-22")

        assert len(rows) == 1
        row = rows[0]
        required_keys = {"timestamp", "iteration", "phase", "cost_tokens", "duration_sec"}
        assert required_keys.issubset(row.keys()), f"Missing keys: {required_keys - row.keys()}"

    def test_cost_tokens_is_plottable_integer(self, tmp_path: Path) -> None:
        """cost_tokens field is an integer (directly usable for Y-axis of cost trend)."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {
                    "timestamp": "2026-03-22T10:00:00Z",
                    "spiral_iter": "5",
                    "cache_read_tokens": "88400",
                    "cache_creation_tokens": "5700",
                    "review_tokens": "300",
                }
            ],
        )

        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        store.insert_from_results_tsv(tsv)
        rows = store.query_by_date_range("2026-03-22", "2026-03-22")

        assert isinstance(rows[0]["cost_tokens"], int)
        assert rows[0]["cost_tokens"] == 94400

    def test_empty_range_returns_empty_list(self, tmp_path: Path) -> None:
        """An empty date range returns a JSON-serialisable empty list."""
        db = tmp_path / "metrics.db"
        store = SQLiteMetricsStore(db_path=db)
        rows = store.query_by_date_range("2026-01-01", "2026-01-02")
        assert rows == []
        import json

        serialised = json.dumps(rows)
        assert serialised == "[]"
