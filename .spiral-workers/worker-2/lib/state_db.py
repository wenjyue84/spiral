"""SQLite state store for SPIRAL — replaces hand-rolled ACID files.

Consolidates _txn_journal, undo/, _checkpoint, retry-counts, and calibration
into a single WAL-mode SQLite database at .spiral/spiral_state.db.

For Python-written data (txn journal, calibration): writes go directly to SQLite.
For bash-written data (checkpoint, retry-counts, undo): provides sync_from_files()
to import flat-file data, and read methods that fall back to flat files if SQLite
has no data yet.

Usage:
    from lib.state_db import StateDB

    db = StateDB("/path/to/project")

    # Transaction journal (replaces TxnJournal for Python callers)
    with db.transaction("phase_m_merge") as txn:
        txn.write_json("prd.json", data)

    # Calibration
    db.record_calibration(story_id="US-123", ...)

    # Read checkpoint/retry-counts (synced from bash-written files)
    db.sync_from_files()
    checkpoint = db.get_checkpoint()
    retries = db.get_retry_counts()
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


def _db_path(project_root: str) -> str:
    return os.path.join(project_root, ".spiral", "spiral_state.db")


class StateDB:
    """Single SQLite database for all SPIRAL state management."""

    def __init__(self, project_root: str) -> None:
        self.root = os.path.abspath(project_root)
        self.scratch = os.path.join(self.root, ".spiral")
        os.makedirs(self.scratch, exist_ok=True)
        self.db_path = _db_path(self.root)
        self.con = sqlite3.connect(self.db_path, timeout=10)
        self.con.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist. WAL mode for concurrent readers."""
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=5000")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT NOT NULL,
                label TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'committed')),
                files_json TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                PRIMARY KEY (id, status)
            );

            CREATE TABLE IF NOT EXISTS undo_log (
                story_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                operation TEXT NOT NULL,
                target TEXT,
                inverse_command TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                PRIMARY KEY (story_id, seq)
            );

            CREATE TABLE IF NOT EXISTS checkpoint (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                iter INTEGER NOT NULL,
                phase TEXT NOT NULL,
                ts TEXT NOT NULL,
                run_id TEXT,
                spiral_version TEXT,
                log_level TEXT,
                phase_durations_json TEXT,
                quality_scores_json TEXT
            );

            CREATE TABLE IF NOT EXISTS retry_counts (
                story_id TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS calibration (
                story_id TEXT NOT NULL,
                timestamp TEXT,
                story_title TEXT,
                estimated_complexity TEXT,
                actual_duration_s INTEGER,
                phase_retries INTEGER DEFAULT 0,
                passed BOOLEAN,
                model TEXT,
                spiral_iter INTEGER,
                ralph_iter INTEGER,
                UNIQUE(story_id, timestamp)
            );

            CREATE INDEX IF NOT EXISTS idx_calibration_complexity
                ON calibration(estimated_complexity);
            CREATE INDEX IF NOT EXISTS idx_undo_story
                ON undo_log(story_id);
            CREATE INDEX IF NOT EXISTS idx_txn_status
                ON transactions(status);
        """)

    # ── Transaction Journal (replaces TxnJournal) ─────────────────────────

    @contextmanager
    def transaction(self, label: str) -> Generator["_TxnWriter", None, None]:
        """Context manager for crash-safe multi-file writes.

        Replaces the JSONL-based TxnJournal with SQLite ACID guarantees.
        On normal exit, transaction is committed. On exception, stays pending
        for recovery via recover_transactions().
        """
        txn_id = uuid.uuid4().hex[:12]
        writer = _TxnWriter(txn_id, label, self)
        try:
            yield writer
        except BaseException:
            raise
        else:
            self.con.execute(
                "INSERT INTO transactions (id, label, status, files_json) VALUES (?, ?, 'committed', ?)",
                (txn_id, label, json.dumps(writer.files)),
            )
            self.con.commit()

    def recover_transactions(self) -> list[str]:
        """Roll back incomplete transactions by restoring .bak files."""
        cursor = self.con.execute("""
            SELECT t.id, t.label, t.files_json
            FROM transactions t
            WHERE t.status = 'pending'
              AND t.id NOT IN (
                  SELECT id FROM transactions WHERE status = 'committed'
              )
        """)
        actions: list[str] = []
        for row in cursor.fetchall():
            txn_id, label = row["id"], row["label"]
            files = json.loads(row["files_json"] or "[]")
            for f_info in files:
                backup = f_info.get("backup", "")
                target = f_info.get("path", "")
                if backup and os.path.isfile(backup) and target:
                    shutil.copy2(backup, target)
                    os.unlink(backup)
                    msg = f"Rolled back {target} from {backup} (txn {txn_id}: {label})"
                    actions.append(msg)

        if actions:
            self.con.execute("""
                DELETE FROM transactions
                WHERE status = 'pending'
                  AND id NOT IN (SELECT id FROM transactions WHERE status = 'committed')
            """)
            self.con.commit()
        return actions

    def compact_transactions(self) -> int:
        """Remove committed transactions older than latest 100. Returns count deleted."""
        cursor = self.con.execute("""
            DELETE FROM transactions
            WHERE rowid NOT IN (
                SELECT rowid FROM transactions ORDER BY created_at DESC LIMIT 100
            )
        """)
        deleted = cursor.rowcount
        self.con.commit()
        return deleted

    # ── Undo Log ──────────────────────────────────────────────────────────

    def undo_record(self, story_id: str, operation: str, target: str, inverse_command: str) -> None:
        """Record an undo entry for a story."""
        seq = self.con.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM undo_log WHERE story_id = ?",
            (story_id,),
        ).fetchone()[0]
        self.con.execute(
            "INSERT INTO undo_log (story_id, seq, operation, target, inverse_command) VALUES (?, ?, ?, ?, ?)",
            (story_id, seq, operation, target, inverse_command),
        )
        self.con.commit()

    def undo_get(self, story_id: str) -> list[dict[str, Any]]:
        """Get undo entries for a story in reverse order (LIFO)."""
        cursor = self.con.execute(
            "SELECT operation, target, inverse_command, created_at FROM undo_log WHERE story_id = ? ORDER BY seq DESC",
            (story_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def undo_cleanup(self, story_id: str) -> None:
        """Delete undo entries after successful merge."""
        self.con.execute("DELETE FROM undo_log WHERE story_id = ?", (story_id,))
        self.con.commit()

    def undo_exists(self, story_id: str) -> bool:
        """Check if undo entries exist for a story."""
        row = self.con.execute(
            "SELECT 1 FROM undo_log WHERE story_id = ? LIMIT 1", (story_id,)
        ).fetchone()
        return row is not None

    def undo_story_ids(self) -> list[str]:
        """List all story IDs that have undo entries."""
        cursor = self.con.execute("SELECT DISTINCT story_id FROM undo_log ORDER BY story_id")
        return [row[0] for row in cursor.fetchall()]

    # ── Checkpoint ────────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        iteration: int,
        phase: str,
        ts: str,
        run_id: str = "",
        spiral_version: str = "",
        log_level: str = "INFO",
        phase_durations: dict[str, float] | None = None,
        quality_scores: dict[str, Any] | None = None,
    ) -> None:
        """Save or update the checkpoint (upsert)."""
        self.con.execute(
            """INSERT OR REPLACE INTO checkpoint
               (id, iter, phase, ts, run_id, spiral_version, log_level, phase_durations_json, quality_scores_json)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                iteration,
                phase,
                ts,
                run_id,
                spiral_version,
                log_level,
                json.dumps(phase_durations) if phase_durations else None,
                json.dumps(quality_scores) if quality_scores else None,
            ),
        )
        self.con.commit()

    def get_checkpoint(self) -> dict[str, Any] | None:
        """Get current checkpoint, falling back to _checkpoint.json if no SQLite data."""
        row = self.con.execute("SELECT * FROM checkpoint WHERE id = 1").fetchone()
        if row:
            result: dict[str, Any] = {
                "iter": row["iter"],
                "phase": row["phase"],
                "ts": row["ts"],
                "run_id": row["run_id"],
                "spiralVersion": row["spiral_version"],
                "log_level": row["log_level"],
            }
            if row["phase_durations_json"]:
                result["phaseDurations"] = json.loads(row["phase_durations_json"])
            if row["quality_scores_json"]:
                result["_qualityScores"] = json.loads(row["quality_scores_json"])
            return result

        # Fallback: read from flat file
        ckpt_path = os.path.join(self.scratch, "_checkpoint.json")
        if os.path.isfile(ckpt_path):
            try:
                with open(ckpt_path, encoding="utf-8") as f:
                    return json.load(f)  # type: ignore[no-any-return]
            except (json.JSONDecodeError, OSError):
                pass
        return None

    # ── Retry Counts ──────────────────────────────────────────────────────

    def set_retry_count(self, story_id: str, count: int) -> None:
        """Set or update retry count for a story."""
        self.con.execute(
            "INSERT OR REPLACE INTO retry_counts (story_id, count) VALUES (?, ?)",
            (story_id, count),
        )
        self.con.commit()

    def increment_retry(self, story_id: str) -> int:
        """Increment retry count and return new value."""
        self.con.execute(
            "INSERT INTO retry_counts (story_id, count) VALUES (?, 1) "
            "ON CONFLICT(story_id) DO UPDATE SET count = count + 1",
            (story_id,),
        )
        self.con.commit()
        row = self.con.execute(
            "SELECT count FROM retry_counts WHERE story_id = ?", (story_id,)
        ).fetchone()
        return row[0] if row else 1

    def get_retry_count(self, story_id: str) -> int:
        """Get retry count for a single story."""
        row = self.con.execute(
            "SELECT count FROM retry_counts WHERE story_id = ?", (story_id,)
        ).fetchone()
        return row[0] if row else 0

    def get_retry_counts(self) -> dict[str, int]:
        """Get all retry counts, falling back to retry-counts.json if empty."""
        cursor = self.con.execute("SELECT story_id, count FROM retry_counts")
        rows = cursor.fetchall()
        if rows:
            return {r["story_id"]: r["count"] for r in rows}

        # Fallback: read from flat file
        rc_path = os.path.join(self.root, "retry-counts.json")
        if os.path.isfile(rc_path):
            try:
                with open(rc_path, encoding="utf-8") as f:
                    return json.load(f)  # type: ignore[no-any-return]
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def reset_retry(self, story_id: str) -> None:
        """Reset retry count to 0 (for DLQ replay)."""
        self.con.execute("DELETE FROM retry_counts WHERE story_id = ?", (story_id,))
        self.con.commit()

    # ── Calibration ───────────────────────────────────────────────────────

    def record_calibration(
        self,
        story_id: str,
        estimated_complexity: str,
        actual_duration_s: int,
        phase_retries: int = 0,
        passed: bool = False,
        story_title: str = "",
        timestamp: str = "",
        model: str = "",
        spiral_iter: int = 0,
        ralph_iter: int = 0,
    ) -> None:
        """Record a calibration entry. Skips duplicates by (story_id, timestamp)."""
        self.con.execute(
            """INSERT OR IGNORE INTO calibration
               (story_id, timestamp, story_title, estimated_complexity,
                actual_duration_s, phase_retries, passed, model, spiral_iter, ralph_iter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                story_id,
                timestamp,
                story_title,
                estimated_complexity,
                actual_duration_s,
                phase_retries,
                passed,
                model,
                spiral_iter,
                ralph_iter,
            ),
        )
        self.con.commit()

    def calibration_report(self) -> dict[str, Any]:
        """Compute calibration stats from SQLite, falling back to JSONL if empty."""
        count = self.con.execute("SELECT COUNT(*) FROM calibration").fetchone()[0]

        if count == 0:
            # Fallback: check flat file
            cal_path = os.path.join(self.root, "calibration.jsonl")
            if os.path.isfile(cal_path):
                self._sync_calibration(cal_path)
                count = self.con.execute("SELECT COUNT(*) FROM calibration").fetchone()[0]

        if count == 0:
            return {"total_completed": 0, "by_tier": {}, "underestimated": [], "pass_rate": 0.0}

        # Per-tier stats
        cursor = self.con.execute("""
            SELECT
                estimated_complexity AS tier,
                COUNT(*) AS count,
                AVG(actual_duration_s) AS avg_s,
                MIN(actual_duration_s) AS min_s,
                MAX(actual_duration_s) AS max_s
            FROM calibration
            GROUP BY estimated_complexity
        """)
        by_tier = {}
        medians = {}
        for row in cursor.fetchall():
            tier = row["tier"] or "unknown"
            # Compute median via separate query
            med_row = self.con.execute(
                """SELECT actual_duration_s FROM calibration
                   WHERE estimated_complexity = ?
                   ORDER BY actual_duration_s
                   LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM calibration WHERE estimated_complexity = ?)""",
                (tier, tier),
            ).fetchone()
            median_s = med_row[0] if med_row else 0
            medians[tier] = median_s
            by_tier[tier] = {
                "count": row["count"],
                "median_s": round(median_s, 2),
                "min_s": row["min_s"],
                "max_s": row["max_s"],
            }

        # Underestimated stories (actual > 2x median)
        underestimated = []
        for tier, median in medians.items():
            if median <= 0:
                continue
            cursor2 = self.con.execute(
                """SELECT story_id, actual_duration_s FROM calibration
                   WHERE estimated_complexity = ? AND actual_duration_s > ? * 2""",
                (tier, median),
            )
            for row2 in cursor2.fetchall():
                underestimated.append({
                    "story_id": row2["story_id"],
                    "estimated": tier,
                    "actual_duration_s": row2["actual_duration_s"],
                    "median_for_tier_s": median,
                    "ratio": round(row2["actual_duration_s"] / median, 2),
                })

        # Pass rate
        pass_row = self.con.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN passed THEN 1 ELSE 0 END) AS passes FROM calibration"
        ).fetchone()
        pass_rate = (pass_row["passes"] / pass_row["total"] * 100) if pass_row["total"] > 0 else 0.0

        return {
            "total_completed": count,
            "by_tier": by_tier,
            "underestimated": underestimated,
            "pass_rate": round(pass_rate, 1),
        }

    # ── Sync from flat files (for bash-written data) ──────────────────────

    def sync_from_files(self) -> dict[str, int]:
        """Import data from flat files into SQLite. Returns counts of imported records."""
        counts: dict[str, int] = {}

        # Sync checkpoint
        ckpt_path = os.path.join(self.scratch, "_checkpoint.json")
        if os.path.isfile(ckpt_path):
            try:
                with open(ckpt_path, encoding="utf-8") as f:
                    ckpt = json.load(f)
                self.save_checkpoint(
                    iteration=ckpt.get("iter", 0),
                    phase=ckpt.get("phase", "R"),
                    ts=ckpt.get("ts", ""),
                    run_id=ckpt.get("run_id", ""),
                    spiral_version=ckpt.get("spiralVersion", ""),
                    log_level=ckpt.get("log_level", "INFO"),
                    phase_durations=ckpt.get("phaseDurations"),
                    quality_scores=ckpt.get("_qualityScores"),
                )
                counts["checkpoint"] = 1
            except (json.JSONDecodeError, OSError):
                pass

        # Sync retry-counts
        rc_path = os.path.join(self.root, "retry-counts.json")
        if os.path.isfile(rc_path):
            try:
                with open(rc_path, encoding="utf-8") as f:
                    rc = json.load(f)
                imported = 0
                for story_id, count in rc.items():
                    self.con.execute(
                        "INSERT OR REPLACE INTO retry_counts (story_id, count) VALUES (?, ?)",
                        (story_id, count),
                    )
                    imported += 1
                self.con.commit()
                counts["retry_counts"] = imported
            except (json.JSONDecodeError, OSError):
                pass

        # Sync undo logs
        undo_dir = os.path.join(self.scratch, "undo")
        if os.path.isdir(undo_dir):
            imported = 0
            for filename in os.listdir(undo_dir):
                if not filename.endswith(".jsonl"):
                    continue
                story_id = filename.removesuffix(".jsonl")
                filepath = os.path.join(undo_dir, filename)
                try:
                    with open(filepath, encoding="utf-8") as f:
                        for seq, line in enumerate(f, 1):
                            line = line.strip()
                            if not line:
                                continue
                            record = json.loads(line)
                            self.con.execute(
                                """INSERT OR IGNORE INTO undo_log
                                   (story_id, seq, operation, target, inverse_command, created_at)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (
                                    story_id,
                                    seq,
                                    record.get("operation", ""),
                                    record.get("target", ""),
                                    record.get("inverse_command", ""),
                                    record.get("timestamp", ""),
                                ),
                            )
                            imported += 1
                except (json.JSONDecodeError, OSError):
                    continue
            self.con.commit()
            counts["undo_entries"] = imported

        # Sync calibration
        cal_path = os.path.join(self.root, "calibration.jsonl")
        if os.path.isfile(cal_path):
            counts["calibration"] = self._sync_calibration(cal_path)

        # Sync transaction journal
        txn_path = os.path.join(self.scratch, "_txn_journal.jsonl")
        if os.path.isfile(txn_path):
            counts["transactions"] = self._sync_txn_journal(txn_path)

        return counts

    def _sync_calibration(self, cal_path: str) -> int:
        imported = 0
        try:
            with open(cal_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.con.execute(
                        """INSERT OR IGNORE INTO calibration
                           (story_id, timestamp, story_title, estimated_complexity,
                            actual_duration_s, phase_retries, passed, model, spiral_iter, ralph_iter)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            r.get("story_id", ""),
                            r.get("timestamp", ""),
                            r.get("story_title", ""),
                            r.get("estimated_complexity", ""),
                            r.get("actual_duration_s", 0),
                            r.get("phase_retries", 0),
                            r.get("passed", False),
                            r.get("model", ""),
                            r.get("spiral_iter", 0),
                            r.get("ralph_iter", 0),
                        ),
                    )
                    imported += 1
            self.con.commit()
        except OSError:
            pass
        return imported

    def _sync_txn_journal(self, txn_path: str) -> int:
        imported = 0
        try:
            with open(txn_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    txn_id = r.get("id", "")
                    status = r.get("status", "")
                    if txn_id and status in ("pending", "committed"):
                        self.con.execute(
                            """INSERT OR IGNORE INTO transactions (id, label, status, files_json)
                               VALUES (?, ?, ?, ?)""",
                            (txn_id, r.get("label", ""), status, json.dumps(r.get("files", []))),
                        )
                        imported += 1
            self.con.commit()
        except OSError:
            pass
        return imported

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self.con.close()

    def __enter__(self) -> "StateDB":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class _TxnWriter:
    """Writer for a single transaction within StateDB."""

    def __init__(self, txn_id: str, label: str, db: StateDB) -> None:
        self.txn_id = txn_id
        self.label = label
        self.db = db
        self.files: list[dict[str, str]] = []

    def write_json(self, path: str, data: Any) -> None:
        """Create .bak of current file, then write new data atomically."""
        backup_path = path + ".bak"
        if os.path.isfile(path):
            shutil.copy2(path, backup_path)

        self.files.append({"path": path, "backup": backup_path})

        # Record pending state in SQLite
        self.db.con.execute(
            "INSERT OR REPLACE INTO transactions (id, label, status, files_json) VALUES (?, ?, 'pending', ?)",
            (self.txn_id, self.label, json.dumps(self.files)),
        )
        self.db.con.commit()

        # Write the actual file atomically
        parent = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def cleanup_backups(self) -> None:
        """Remove .bak files after successful commit."""
        for f_info in self.files:
            backup = f_info.get("backup", "")
            if backup and os.path.isfile(backup):
                try:
                    os.unlink(backup)
                except OSError:
                    pass
