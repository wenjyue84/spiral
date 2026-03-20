"""Tests for lib/state_db.py — SQLite state management."""

import json
import os

import pytest

from lib.state_db import StateDB


@pytest.fixture
def state_db(tmp_path):
    """Create a StateDB in a temp directory."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    db = StateDB(str(tmp_path))
    yield db
    db.close()


# ── Transaction Journal ──────────────────────────────────────────────────────


def test_transaction_commit(state_db, tmp_path):
    """Committed transactions write files atomically."""
    target = str(tmp_path / "test.json")
    with state_db.transaction("test_label") as txn:
        txn.write_json(target, {"key": "value"})

    assert os.path.isfile(target)
    with open(target, encoding="utf-8") as f:
        assert json.load(f)["key"] == "value"


def test_transaction_rollback(state_db, tmp_path):
    """Failed transactions leave pending records for recovery."""
    target = str(tmp_path / "rollback.json")
    # Write initial content
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"original": True}, f)

    with pytest.raises(ValueError):
        with state_db.transaction("will_fail") as txn:
            txn.write_json(target, {"modified": True})
            raise ValueError("Simulated failure")

    # Recovery should restore original
    actions = state_db.recover_transactions()
    assert len(actions) == 1
    with open(target, encoding="utf-8") as f:
        assert json.load(f)["original"] is True


def test_transaction_compact(state_db, tmp_path):
    """Compaction removes old transactions."""
    for i in range(150):
        target = str(tmp_path / f"compact_{i}.json")
        with state_db.transaction(f"txn_{i}") as txn:
            txn.write_json(target, {"i": i})

    deleted = state_db.compact_transactions()
    assert deleted > 0


def test_cleanup_backups(state_db, tmp_path):
    """cleanup_backups removes .bak files."""
    target = str(tmp_path / "cleanup.json")
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"old": True}, f)

    with state_db.transaction("cleanup_test") as txn:
        txn.write_json(target, {"new": True})
        txn.cleanup_backups()

    assert not os.path.isfile(target + ".bak")


# ── Undo Log ─────────────────────────────────────────────────────────────────


def test_undo_record_and_get(state_db):
    """Record and retrieve undo entries in LIFO order."""
    state_db.undo_record("US-001", "checkpoint", "HEAD:abc", "git reset --hard abc")
    state_db.undo_record("US-001", "git_commit", "def", "git reset --hard HEAD~1")

    entries = state_db.undo_get("US-001")
    assert len(entries) == 2
    # LIFO: git_commit first, checkpoint second
    assert entries[0]["operation"] == "git_commit"
    assert entries[1]["operation"] == "checkpoint"


def test_undo_cleanup(state_db):
    """Cleanup removes all entries for a story."""
    state_db.undo_record("US-002", "checkpoint", "x", "git reset")
    assert state_db.undo_exists("US-002")

    state_db.undo_cleanup("US-002")
    assert not state_db.undo_exists("US-002")


def test_undo_story_ids(state_db):
    """List all story IDs with undo entries."""
    state_db.undo_record("US-010", "op", "t", "cmd")
    state_db.undo_record("US-020", "op", "t", "cmd")
    ids = state_db.undo_story_ids()
    assert set(ids) == {"US-010", "US-020"}


# ── Checkpoint ───────────────────────────────────────────────────────────────


def test_checkpoint_save_and_get(state_db):
    """Save and retrieve checkpoint."""
    state_db.save_checkpoint(
        iteration=5,
        phase="M",
        ts="2026-03-18T10:00:00Z",
        run_id="run-123",
        phase_durations={"R": 60, "T": 30},
    )
    ckpt = state_db.get_checkpoint()
    assert ckpt is not None
    assert ckpt["iter"] == 5
    assert ckpt["phase"] == "M"
    assert ckpt["phaseDurations"]["R"] == 60


def test_checkpoint_fallback_to_file(tmp_path):
    """Falls back to _checkpoint.json if SQLite has no data."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    ckpt_file = spiral_dir / "_checkpoint.json"
    ckpt_file.write_text(json.dumps({"iter": 3, "phase": "I", "ts": "2026-03-18T09:00:00Z"}))

    db = StateDB(str(tmp_path))
    ckpt = db.get_checkpoint()
    assert ckpt is not None
    assert ckpt["iter"] == 3
    db.close()


# ── Retry Counts ─────────────────────────────────────────────────────────────


def test_retry_increment(state_db):
    """Increment retry count atomically."""
    assert state_db.get_retry_count("US-100") == 0

    new = state_db.increment_retry("US-100")
    assert new == 1
    new = state_db.increment_retry("US-100")
    assert new == 2

    assert state_db.get_retry_count("US-100") == 2


def test_retry_reset(state_db):
    """Reset removes retry count."""
    state_db.set_retry_count("US-200", 5)
    state_db.reset_retry("US-200")
    assert state_db.get_retry_count("US-200") == 0


def test_retry_counts_fallback(tmp_path):
    """Falls back to retry-counts.json if SQLite is empty."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    rc_file = tmp_path / "retry-counts.json"
    rc_file.write_text(json.dumps({"US-300": 3, "US-301": 1}))

    db = StateDB(str(tmp_path))
    counts = db.get_retry_counts()
    assert counts["US-300"] == 3
    assert counts["US-301"] == 1
    db.close()


# ── Calibration ──────────────────────────────────────────────────────────────


def test_calibration_record_and_report(state_db):
    """Record calibration entries and generate report."""
    state_db.record_calibration("US-050", "small", 100, passed=True)
    state_db.record_calibration("US-051", "small", 120, passed=True)
    state_db.record_calibration("US-052", "medium", 300, passed=False)

    report = state_db.calibration_report()
    assert report["total_completed"] == 3
    assert "small" in report["by_tier"]
    assert report["by_tier"]["small"]["count"] == 2
    assert report["pass_rate"] == pytest.approx(66.7, abs=0.1)


def test_calibration_dedup(state_db):
    """Duplicate records are ignored."""
    state_db.record_calibration("US-060", "small", 100, timestamp="2026-03-18T10:00:00Z")
    state_db.record_calibration("US-060", "small", 100, timestamp="2026-03-18T10:00:00Z")

    rows = state_db.con.execute("SELECT count(*) FROM calibration WHERE story_id = 'US-060'").fetchone()
    assert rows[0] == 1


# ── Sync from Files ──────────────────────────────────────────────────────────


def test_sync_from_files(tmp_path):
    """Sync imports data from all flat-file sources."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()

    # checkpoint
    ckpt = spiral_dir / "_checkpoint.json"
    ckpt.write_text(json.dumps({"iter": 7, "phase": "V", "ts": "2026-03-18T12:00:00Z"}))

    # retry-counts
    rc = tmp_path / "retry-counts.json"
    rc.write_text(json.dumps({"US-400": 2, "US-401": 4}))

    # undo logs
    undo_dir = spiral_dir / "undo"
    undo_dir.mkdir()
    (undo_dir / "US-400.jsonl").write_text(
        json.dumps(
            {
                "operation": "checkpoint",
                "target": "HEAD:abc",
                "inverse_command": "git reset --hard abc",
                "timestamp": "2026-03-18T11:00:00Z",
            }
        )
        + "\n"
    )

    # calibration
    cal = tmp_path / "calibration.jsonl"
    cal.write_text(
        json.dumps({"story_id": "US-400", "estimated_complexity": "small", "actual_duration_s": 100, "passed": True})
        + "\n"
    )

    db = StateDB(str(tmp_path))
    counts = db.sync_from_files()

    assert counts.get("checkpoint") == 1
    assert counts.get("retry_counts") == 2
    assert counts.get("undo_entries", 0) >= 1
    assert counts.get("calibration", 0) >= 1

    # Verify synced data
    ckpt_data = db.get_checkpoint()
    assert ckpt_data is not None
    assert ckpt_data["iter"] == 7
    assert db.get_retry_count("US-400") == 2
    assert db.undo_exists("US-400")

    db.close()


# ── Context Manager ──────────────────────────────────────────────────────────


def test_context_manager(tmp_path):
    """StateDB works as a context manager."""
    (tmp_path / ".spiral").mkdir()
    with StateDB(str(tmp_path)) as db:
        db.save_checkpoint(1, "R", "2026-03-18T10:00:00Z")
        ckpt = db.get_checkpoint()
        assert ckpt["iter"] == 1
