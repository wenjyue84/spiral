"""SQLiteMetricsStore — Persistent metrics storage for SPIRAL (US-1051).

Stores phase timing and cost data from results.tsv into timestamped SQLite rows.
Provides query_by_date_range for dashboard trend visualization.
"""

import csv
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteMetricsStore:
    """Persist phase metrics from results.tsv to SQLite for 7-day trend queries."""

    def __init__(self, db_path: Path | str) -> None:
        """Initialize store with database path."""
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create metrics table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    cost_tokens INTEGER NOT NULL,
                    duration_sec REAL NOT NULL
                )
                """
            )
            # Create index on timestamp for fast date-range queries
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_timestamp ON metrics(timestamp)
                """
            )
            conn.commit()

    def insert_from_results_tsv(self, tsv_path: Path | str) -> int:
        """Ingest results.tsv rows into metrics table.

        Returns: count of inserted rows (0 if file doesn't exist).
        """
        tsv_path = Path(tsv_path)
        if not tsv_path.exists():
            return 0

        inserted = 0
        with open(tsv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            rows_to_insert: list[tuple[str, int, str, int, float]] = []

            for row in reader:
                timestamp = row.get("timestamp", "")

                # Parse fields with defaults for malformed values
                try:
                    spiral_iter = int(row.get("spiral_iter", "0")) if row.get("spiral_iter") else 0
                except (ValueError, TypeError):
                    spiral_iter = 0

                try:
                    duration_sec_str = row.get("duration_sec", "0")
                    duration_sec = float(duration_sec_str) if duration_sec_str else 0.0
                except (ValueError, TypeError):
                    duration_sec = 0.0

                # Parse token fields, default to 0 for missing/malformed
                try:
                    cache_read = int(row.get("cache_read_tokens", "0")) if row.get("cache_read_tokens") else 0
                except (ValueError, TypeError):
                    cache_read = 0

                try:
                    cache_creation = (
                        int(row.get("cache_creation_tokens", "0")) if row.get("cache_creation_tokens") else 0
                    )
                except (ValueError, TypeError):
                    cache_creation = 0

                try:
                    review = int(row.get("review_tokens", "0")) if row.get("review_tokens") else 0
                except (ValueError, TypeError):
                    review = 0

                cost_tokens = cache_read + cache_creation + review
                phase = "I"  # Phase Implementation (results.tsv is only populated during Phase I)

                rows_to_insert.append((timestamp, spiral_iter, phase, cost_tokens, duration_sec))

        # Batch insert all rows
        if rows_to_insert:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany(
                    """
                    INSERT INTO metrics (timestamp, iteration, phase, cost_tokens, duration_sec)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows_to_insert,
                )
                conn.commit()
                inserted = len(rows_to_insert)

        return inserted

    def query_by_date_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Query metrics for a date range.

        Args:
            start_date: ISO date string (YYYY-MM-DD)
            end_date: ISO date string (YYYY-MM-DD)

        Returns: List of metric dicts with timestamp, iteration, phase, cost_tokens, duration_sec
        """
        if not self.db_path.exists():
            return []

        # Convert dates to ISO datetime range
        # start_date 2026-03-20 -> 2026-03-20T00:00:00Z
        # end_date 2026-03-26 -> 2026-03-26T23:59:59Z
        start_dt = f"{start_date}T00:00:00Z"
        end_dt = f"{end_date}T23:59:59Z"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT timestamp, iteration, phase, cost_tokens, duration_sec
                FROM metrics
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (start_dt, end_dt),
            )
            rows = cursor.fetchall()

        return [dict(row) for row in rows]
