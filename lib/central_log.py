"""Central log — aggregates per-story and per-run metrics into ~/.spiral/central.db.

Cross-project SQLite database for SPIRAL telemetry. Every SPIRAL invocation
records run start/end and per-story attempts. Query via `lib/cli/central_log_insights.py`.

CLI entry point (called from plugin hooks):
    python lib/central_log.py record-run-start --run-id X --project-path /foo
    python lib/central_log.py record-story --run-id X --project-name bar --story-id US-1 ...
    python lib/central_log.py record-run-end --run-id X --exit-code 0 --iterations 5 ...
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_db_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".spiral", "central.db")


def _spiral_version() -> str:
    """Best-effort git describe for version tagging."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(__file__),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Cost computation — reuse PRICING from core/constants.py
# Inline the pricing dict to avoid import issues when called from bash hooks
_PRICING: dict[str, dict[str, float]] = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}


def compute_cost(
    model: str,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate USD cost from model name and token counts.

    Assumes cache_read_tokens are input and cache_creation_tokens are output.
    """
    model = (model or "sonnet").lower()
    rates = _PRICING.get(model, _PRICING["sonnet"])
    cost = (cache_read_tokens / 1_000_000) * rates["input"]
    cost += (cache_creation_tokens / 1_000_000) * rates["output"]
    return round(cost, 6)


class CentralLog:
    """Writer for ~/.spiral/central.db — cross-project SPIRAL telemetry."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.con = sqlite3.connect(self.db_path, timeout=10)
        self.con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=5000")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                project_path TEXT,
                project_name TEXT,
                started_at TEXT,
                ended_at TEXT,
                exit_code INTEGER,
                iterations INTEGER,
                stories_attempted INTEGER,
                stories_passed INTEGER,
                stories_failed INTEGER,
                stories_skipped INTEGER,
                total_cost_usd REAL,
                total_duration_sec REAL,
                models_used TEXT,
                top_failure_types TEXT,
                spiral_version TEXT
            );

            CREATE TABLE IF NOT EXISTS story_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT REFERENCES runs(run_id),
                project_name TEXT,
                story_id TEXT,
                story_title TEXT,
                model TEXT,
                duration_sec REAL,
                status TEXT,
                failure_type TEXT,
                failure_message TEXT,
                retry_num INTEGER,
                estimated_complexity TEXT,
                spiral_iter INTEGER,
                timestamp TEXT,
                cache_read_tokens INTEGER,
                cache_creation_tokens INTEGER,
                cost_usd REAL
            );

            CREATE INDEX IF NOT EXISTS idx_sa_run_id ON story_attempts(run_id);
            CREATE INDEX IF NOT EXISTS idx_sa_project ON story_attempts(project_name);
            CREATE INDEX IF NOT EXISTS idx_sa_status ON story_attempts(status);
            CREATE INDEX IF NOT EXISTS idx_sa_timestamp ON story_attempts(timestamp);
            CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_name);
        """)

    def record_run_start(
        self,
        run_id: str,
        project_path: str,
        started_at: str | None = None,
    ) -> None:
        project_name = os.path.basename(project_path)
        self.con.execute(
            """INSERT OR IGNORE INTO runs
               (run_id, project_path, project_name, started_at, spiral_version)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, project_path, project_name, started_at or _now_iso(), _spiral_version()),
        )
        self.con.commit()

    def record_story(
        self,
        run_id: str,
        project_name: str,
        story_id: str,
        story_title: str = "",
        model: str = "",
        duration_sec: float = 0.0,
        status: str = "",
        failure_type: str = "",
        failure_message: str = "",
        retry_num: int = 0,
        estimated_complexity: str = "",
        spiral_iter: int = 0,
        timestamp: str = "",
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        if cost_usd is None:
            cost_usd = compute_cost(model, cache_read_tokens, cache_creation_tokens)
        self.con.execute(
            """INSERT INTO story_attempts
               (run_id, project_name, story_id, story_title, model, duration_sec,
                status, failure_type, failure_message, retry_num,
                estimated_complexity, spiral_iter, timestamp,
                cache_read_tokens, cache_creation_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                project_name,
                story_id,
                story_title,
                model,
                duration_sec,
                status,
                failure_type,
                failure_message,
                retry_num,
                estimated_complexity,
                spiral_iter,
                timestamp or _now_iso(),
                cache_read_tokens,
                cache_creation_tokens,
                cost_usd,
            ),
        )
        self.con.commit()

    def record_run_end(
        self,
        run_id: str,
        ended_at: str | None = None,
        exit_code: int = 0,
        iterations: int = 0,
        stories_attempted: int = 0,
        stories_passed: int = 0,
        stories_failed: int = 0,
        stories_skipped: int = 0,
        total_duration_sec: float = 0.0,
    ) -> None:
        # Aggregate cost and models from story_attempts
        row = self.con.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM story_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        total_cost = row[0] if row else 0.0

        models_row = self.con.execute(
            "SELECT DISTINCT model FROM story_attempts WHERE run_id = ? AND model != ''",
            (run_id,),
        ).fetchall()
        models_used = json.dumps(sorted(set(r[0] for r in models_row)))

        # Aggregate failure types
        fail_rows = self.con.execute(
            """SELECT failure_type, COUNT(*) as cnt
               FROM story_attempts
               WHERE run_id = ? AND status = 'fail' AND failure_type != ''
               GROUP BY failure_type ORDER BY cnt DESC LIMIT 10""",
            (run_id,),
        ).fetchall()
        top_failures = json.dumps({r[0]: r[1] for r in fail_rows})

        self.con.execute(
            """UPDATE runs SET
                ended_at = ?,
                exit_code = ?,
                iterations = ?,
                stories_attempted = ?,
                stories_passed = ?,
                stories_failed = ?,
                stories_skipped = ?,
                total_cost_usd = ?,
                total_duration_sec = ?,
                models_used = ?,
                top_failure_types = ?
               WHERE run_id = ?""",
            (
                ended_at or _now_iso(),
                exit_code,
                iterations,
                stories_attempted,
                stories_passed,
                stories_failed,
                stories_skipped,
                total_cost,
                total_duration_sec,
                models_used,
                top_failures,
                run_id,
            ),
        )
        self.con.commit()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "CentralLog":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ── CLI entry point (called from plugin hooks) ──────────────────────────────


def _cli_record_run_start(args: argparse.Namespace) -> None:
    with CentralLog() as cl:
        cl.record_run_start(args.run_id, args.project_path)


def _cli_record_story(args: argparse.Namespace) -> None:
    with CentralLog() as cl:
        cl.record_story(
            run_id=args.run_id,
            project_name=args.project_name,
            story_id=args.story_id,
            story_title=getattr(args, "story_title", ""),
            model=getattr(args, "model", ""),
            duration_sec=float(getattr(args, "duration_sec", 0) or 0),
            status=getattr(args, "status", ""),
            failure_type=getattr(args, "failure_type", ""),
            failure_message=getattr(args, "failure_message", ""),
            retry_num=int(getattr(args, "retry_num", 0) or 0),
            estimated_complexity=getattr(args, "estimated_complexity", ""),
            spiral_iter=int(getattr(args, "spiral_iter", 0) or 0),
            timestamp=getattr(args, "timestamp", ""),
            cache_read_tokens=int(getattr(args, "cache_read_tokens", 0) or 0),
            cache_creation_tokens=int(getattr(args, "cache_creation_tokens", 0) or 0),
        )


def _cli_record_run_end(args: argparse.Namespace) -> None:
    with CentralLog() as cl:
        cl.record_run_end(
            run_id=args.run_id,
            exit_code=int(getattr(args, "exit_code", 0) or 0),
            iterations=int(getattr(args, "iterations", 0) or 0),
            stories_attempted=int(getattr(args, "stories_attempted", 0) or 0),
            stories_passed=int(getattr(args, "stories_passed", 0) or 0),
            stories_failed=int(getattr(args, "stories_failed", 0) or 0),
            stories_skipped=int(getattr(args, "stories_skipped", 0) or 0),
            total_duration_sec=float(getattr(args, "total_duration_sec", 0) or 0),
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="central_log", description="SPIRAL central log writer")
    subs = parser.add_subparsers(dest="action", required=True)

    start = subs.add_parser("record-run-start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--project-path", required=True)

    story = subs.add_parser("record-story")
    story.add_argument("--run-id", required=True)
    story.add_argument("--project-name", required=True)
    story.add_argument("--story-id", required=True)
    story.add_argument("--story-title", default="")
    story.add_argument("--model", default="")
    story.add_argument("--duration-sec", default="0")
    story.add_argument("--status", default="")
    story.add_argument("--failure-type", default="")
    story.add_argument("--failure-message", default="")
    story.add_argument("--retry-num", default="0")
    story.add_argument("--estimated-complexity", default="")
    story.add_argument("--spiral-iter", default="0")
    story.add_argument("--timestamp", default="")
    story.add_argument("--cache-read-tokens", default="0")
    story.add_argument("--cache-creation-tokens", default="0")

    end = subs.add_parser("record-run-end")
    end.add_argument("--run-id", required=True)
    end.add_argument("--exit-code", default="0")
    end.add_argument("--iterations", default="0")
    end.add_argument("--stories-attempted", default="0")
    end.add_argument("--stories-passed", default="0")
    end.add_argument("--stories-failed", default="0")
    end.add_argument("--stories-skipped", default="0")
    end.add_argument("--total-duration-sec", default="0")

    return parser


if __name__ == "__main__":
    try:
        parser = _build_parser()
        args = parser.parse_args()
        if args.action == "record-run-start":
            _cli_record_run_start(args)
        elif args.action == "record-story":
            _cli_record_story(args)
        elif args.action == "record-run-end":
            _cli_record_run_end(args)
    except Exception:
        # Never crash SPIRAL
        pass
