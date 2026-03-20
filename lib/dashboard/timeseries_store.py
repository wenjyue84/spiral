#!/usr/bin/env python3
"""timeseries_store.py — SQLite-backed historical metrics for trend analysis.

Schema:
    iterations(iteration_N, timestamp, phase, duration_sec, tokens_spent)
    stories(story_id, iteration_N, phase, status, retry_count)
    workers(worker_id, timestamp, memory_mb, lock_wait_ms)

Public API:
    record_iteration_from_results_tsv(iteration_n, results_tsv, db_path)
    record_iteration(iteration_n, phase, duration_sec, tokens_spent, db_path)
    query_timeseries(metric, phase, window_days, db_path) -> list[dict]
"""

import csv
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_DEFAULT_DB = Path(".spiral/dashboard.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS iterations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_N   INTEGER NOT NULL,
    timestamp     TEXT    NOT NULL,
    phase         TEXT    NOT NULL DEFAULT '',
    duration_sec  REAL    NOT NULL DEFAULT 0.0,
    tokens_spent  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id      TEXT    NOT NULL,
    iteration_N   INTEGER NOT NULL,
    phase         TEXT    NOT NULL DEFAULT 'I',
    status        TEXT    NOT NULL DEFAULT 'unknown',
    retry_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS workers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id     TEXT    NOT NULL,
    timestamp     TEXT    NOT NULL,
    memory_mb     REAL    NOT NULL DEFAULT 0.0,
    lock_wait_ms  INTEGER NOT NULL DEFAULT 0
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open (and initialise) the SQLite database, returning a connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


def record_iteration(
    iteration_n: int,
    phase: str,
    duration_sec: float,
    tokens_spent: int,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert a single phase-duration row into the iterations table."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO iterations (iteration_N, timestamp, phase, duration_sec, tokens_spent) VALUES (?, ?, ?, ?, ?)",
            (iteration_n, ts, phase, duration_sec, tokens_spent),
        )
        conn.commit()


def record_story(
    story_id: str,
    iteration_n: int,
    phase: str,
    status: str,
    retry_count: int,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert a story-attempt row into the stories table."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stories (story_id, iteration_N, phase, status, retry_count) VALUES (?, ?, ?, ?, ?)",
            (story_id, iteration_n, phase, status, retry_count),
        )
        conn.commit()


def record_worker(
    worker_id: str,
    memory_mb: float,
    lock_wait_ms: int,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Insert a worker snapshot row into the workers table."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO workers (worker_id, timestamp, memory_mb, lock_wait_ms) VALUES (?, ?, ?, ?)",
            (worker_id, ts, memory_mb, lock_wait_ms),
        )
        conn.commit()


def record_iteration_from_results_tsv(
    iteration_n: int,
    results_tsv: Path,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Parse results.tsv and persist per-iteration metrics to SQLite.

    Called by Phase C after each iteration completes.  Reads all rows for
    *iteration_n* from results.tsv and records:
      - one iterations row per phase with aggregated duration_sec / tokens
      - one stories row per story attempt
    """
    if not results_tsv.exists():
        return

    # Accumulate per-phase totals across rows that match this iteration
    phase_duration: dict[str, float] = {}
    phase_tokens: dict[str, int] = {}

    try:
        with open(results_tsv, encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                row_iter_raw = row.get("iteration", "")
                try:
                    row_iter = int(row_iter_raw)
                except (ValueError, TypeError):
                    row_iter = -1

                # Parse impl_secs as proxy for this story's phase duration
                try:
                    impl_sec = float(row.get("impl_secs", 0) or 0)
                except (ValueError, TypeError):
                    impl_sec = 0.0

                try:
                    tokens = int(row.get("tokens_used", 0) or 0)
                except (ValueError, TypeError):
                    tokens = 0

                phase = str(row.get("phase", "I") or "I").strip()
                status = str(row.get("status", "unknown") or "unknown").strip()
                story_id = str(row.get("story_id", "unknown") or "unknown").strip()

                try:
                    retry_count = int(row.get("retry_count", 0) or 0)
                except (ValueError, TypeError):
                    retry_count = 0

                # Only record stories for matching iteration
                if row_iter == iteration_n:
                    record_story(
                        story_id=story_id,
                        iteration_n=iteration_n,
                        phase=phase,
                        status=status,
                        retry_count=retry_count,
                        db_path=db_path,
                    )

                    phase_duration[phase] = phase_duration.get(phase, 0.0) + impl_sec
                    phase_tokens[phase] = phase_tokens.get(phase, 0) + tokens

    except Exception:
        # Best-effort; never raise from Phase C hook
        return

    # Write aggregated phase rows to iterations table
    ts = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        for ph, dur in phase_duration.items():
            conn.execute(
                "INSERT INTO iterations (iteration_N, timestamp, phase, duration_sec, tokens_spent)"
                " VALUES (?, ?, ?, ?, ?)",
                (iteration_n, ts, ph, dur, phase_tokens.get(ph, 0)),
            )
        conn.commit()


def query_timeseries(
    metric: str = "phase_duration",
    phase: Optional[str] = None,
    window_days: int = 30,
    db_path: Path = _DEFAULT_DB,
) -> list[dict[str, Any]]:
    """Return time-series data points for the requested metric.

    Args:
        metric:      'phase_duration' | 'story_throughput' | 'worker_memory'
        phase:       Phase letter filter (only for phase_duration, e.g. 'R', 'I')
        window_days: How many days of history to include (default: 30)
        db_path:     Path to dashboard.db

    Returns:
        List of dicts with 'timestamp' (ISO string) and 'value' (float).
        Returns [] if the database doesn't exist or no data is available.
    """
    if not db_path.exists():
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    try:
        conn = _connect(db_path)
        rows: list[dict[str, Any]] = []

        if metric == "phase_duration":
            if phase:
                cur = conn.execute(
                    "SELECT timestamp, duration_sec FROM iterations"
                    " WHERE phase = ? AND timestamp >= ?"
                    " ORDER BY timestamp ASC",
                    (phase, cutoff),
                )
            else:
                cur = conn.execute(
                    "SELECT timestamp, SUM(duration_sec) as duration_sec FROM iterations"
                    " WHERE timestamp >= ?"
                    " GROUP BY iteration_N, timestamp"
                    " ORDER BY timestamp ASC",
                    (cutoff,),
                )
            for row in cur.fetchall():
                rows.append({"timestamp": row["timestamp"], "value": float(row["duration_sec"])})

        elif metric == "story_throughput":
            cur = conn.execute(
                "SELECT timestamp, COUNT(*) as cnt FROM iterations"
                " WHERE timestamp >= ?"
                " GROUP BY iteration_N, timestamp"
                " ORDER BY timestamp ASC",
                (cutoff,),
            )
            for row in cur.fetchall():
                rows.append({"timestamp": row["timestamp"], "value": float(row["cnt"])})

        elif metric == "worker_memory":
            cur = conn.execute(
                "SELECT timestamp, AVG(memory_mb) as avg_mem FROM workers"
                " WHERE timestamp >= ?"
                " GROUP BY timestamp"
                " ORDER BY timestamp ASC",
                (cutoff,),
            )
            for row in cur.fetchall():
                rows.append({"timestamp": row["timestamp"], "value": float(row["avg_mem"])})

        conn.close()
        return rows

    except Exception:
        return []
