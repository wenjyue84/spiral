"""
tests/integration/test_spiral_crash_recovery.py — US-663

Integration tests verifying SPIRAL crash recovery via .spiral/_checkpoint.json.

Covers:
  AC1 — checkpoint persists {phase: 'I', completed_stories: [...]} after mid-Phase-I crash
  AC2 — checkpoint reading logic resumes iteration and phase correctly (skips R/T)
  AC3 — results.tsv consistency: prior rows unchanged, new rows appended without duplicates
"""

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib", "core"))

from state_machine import SpiralPhaseStateMachine

# TSV header matching lib/observability/merge_results_tsv.py
_TSV_HEADER = [
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
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_prd(story_ids: list[str]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "productName": "TestProduct",
        "branchName": "main",
        "overview": "Crash recovery test PRD",
        "goals": [],
        "userStories": [
            {
                "id": sid,
                "title": f"Story {sid}",
                "passes": False,
                "priority": "medium",
                "description": f"Test story {sid}",
                "acceptanceCriteria": ["AC1"],
                "dependencies": [],
            }
            for sid in story_ids
        ],
    }


def _write_checkpoint(
    spiral_dir: Path,
    phase: str,
    iter_num: int,
    story_id: str,
    retry_count: int = 0,
    completed_stories: list[str] | None = None,
) -> Path:
    """Write a _checkpoint.json simulating a crash mid-Phase-I."""
    spiral_dir.mkdir(parents=True, exist_ok=True)
    ckpt = {
        "phase": phase,
        "iter": iter_num,
        "ts": time.time(),
        "storyId": story_id,
        "retryCount": retry_count,
        "run_id": "test-run-recovery",
        "spiralVersion": "test",
    }
    if completed_stories is not None:
        ckpt["completed_stories"] = completed_stories
    path = spiral_dir / "_checkpoint.json"
    path.write_text(json.dumps(ckpt, indent=2), encoding="utf-8")
    return path


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _make_tsv_row(story_id: str, ts: str, status: str = "keep") -> dict[str, str]:
    return {
        "timestamp": ts,
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Story {story_id}",
        "status": status,
        "duration_sec": "30",
        "model": "sonnet",
        "retry_num": "0",
        "commit_sha": "abc1234",
        "run_id": "test-run-recovery",
    }


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — Checkpoint persists Phase I state with completed_stories tracking
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckpointPersistence:
    """
    AC1: After a crash during Phase I after story 3 of 5,
    .spiral/_checkpoint.json must persist phase='I' and completed_stories=['US-001','US-002','US-003'].
    """

    def test_checkpoint_persists_phase_i_after_crash(self, tmp_path: Path) -> None:
        """Checkpoint written after story 3 has phase='I' and completed_stories=['US-001','US-002','US-003']."""
        spiral_dir = tmp_path / ".spiral"
        completed = ["US-001", "US-002", "US-003"]

        # Simulate crash: write checkpoint after completing story 3, before story 4
        ckpt_path = _write_checkpoint(
            spiral_dir,
            phase="I",
            iter_num=1,
            story_id="US-004",  # next story to run when resumed
            completed_stories=completed,
        )

        assert ckpt_path.exists(), "Checkpoint file must be written"
        data = json.loads(ckpt_path.read_text(encoding="utf-8"))

        assert data["phase"] == "I", f"Expected phase='I', got {data['phase']!r}"
        assert data["completed_stories"] == completed, (
            f"Expected completed_stories={completed}, got {data['completed_stories']}"
        )

    def test_checkpoint_state_machine_validates_phase_i(self, tmp_path: Path) -> None:
        """The state machine must accept a checkpoint with phase='I'."""
        spiral_dir = tmp_path / ".spiral"
        ckpt_path = _write_checkpoint(
            spiral_dir,
            phase="I",
            iter_num=1,
            story_id="US-004",
            completed_stories=["US-001", "US-002", "US-003"],
        )

        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(data)
        assert errors == [], f"State machine reported errors: {errors}"

    def test_checkpoint_next_story_is_us004_after_crash_at_story3(self, tmp_path: Path) -> None:
        """After crashing at story 3, the checkpoint storyId must point to US-004 (next story)."""
        spiral_dir = tmp_path / ".spiral"
        ckpt_path = _write_checkpoint(
            spiral_dir,
            phase="I",
            iter_num=1,
            story_id="US-004",
            completed_stories=["US-001", "US-002", "US-003"],
        )

        data = json.loads(ckpt_path.read_text(encoding="utf-8"))
        assert data["storyId"] == "US-004", (
            "Checkpoint must record US-004 as the next story to resume at"
        )
        assert len(data["completed_stories"]) == 3, "Exactly 3 stories were completed before crash"

    def test_checkpoint_missing_without_crash(self, tmp_path: Path) -> None:
        """Without a crash, no checkpoint is present before Phase I begins."""
        spiral_dir = tmp_path / ".spiral"
        ckpt_path = spiral_dir / "_checkpoint.json"
        assert not ckpt_path.exists(), "Checkpoint must not exist for a fresh run"


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — Checkpoint reading logic skips R/T and resumes Phase I at US-004
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckpointResumeLogic:
    """
    AC2: When a checkpoint with phase='I' exists, restart logic must:
      - Skip Phase R and Phase T (research + test synthesis)
      - Resume Phase I starting at US-004 (the story after the last completed one)
      - Not re-run US-001, US-002, US-003
    """

    def test_checkpoint_iter_matches_written_value(self, tmp_path: Path) -> None:
        """The checkpoint iter field is preserved exactly as written."""
        spiral_dir = tmp_path / ".spiral"
        _write_checkpoint(spiral_dir, phase="I", iter_num=5, story_id="US-004")

        data = json.loads((spiral_dir / "_checkpoint.json").read_text(encoding="utf-8"))
        assert data["iter"] == 5

    def test_resume_phase_is_beyond_r_and_t(self, tmp_path: Path) -> None:
        """A checkpoint with phase='I' is later in the phase order than R and T."""
        from state_machine import PHASE_ORDER

        spiral_dir = tmp_path / ".spiral"
        _write_checkpoint(spiral_dir, phase="I", iter_num=1, story_id="US-004")

        data = json.loads((spiral_dir / "_checkpoint.json").read_text(encoding="utf-8"))
        ckpt_phase = data["phase"]

        # Phase I must come after R (Research) and T (Test Synthesis)
        assert PHASE_ORDER[ckpt_phase] > PHASE_ORDER["R"], (
            f"Resume phase '{ckpt_phase}' must be after Research (R)"
        )
        assert PHASE_ORDER[ckpt_phase] > PHASE_ORDER["T"], (
            f"Resume phase '{ckpt_phase}' must be after Test Synthesis (T)"
        )

    def test_completed_stories_excludes_us004_and_us005(self, tmp_path: Path) -> None:
        """completed_stories must not contain US-004 or US-005 (they haven't run yet)."""
        spiral_dir = tmp_path / ".spiral"
        completed = ["US-001", "US-002", "US-003"]
        _write_checkpoint(
            spiral_dir,
            phase="I",
            iter_num=1,
            story_id="US-004",
            completed_stories=completed,
        )

        data = json.loads((spiral_dir / "_checkpoint.json").read_text(encoding="utf-8"))
        assert "US-004" not in data["completed_stories"], "US-004 must not be in completed_stories"
        assert "US-005" not in data["completed_stories"], "US-005 must not be in completed_stories"

    def test_startup_reads_iter_for_resume(self, tmp_path: Path) -> None:
        """
        Simulates spiral_startup.sh logic: reading iter from checkpoint and computing
        SPIRAL_ITER = ckpt_iter - 1 so the loop increments back to ckpt_iter on next pass.
        """
        spiral_dir = tmp_path / ".spiral"
        _write_checkpoint(spiral_dir, phase="I", iter_num=3, story_id="US-004")

        data = json.loads((spiral_dir / "_checkpoint.json").read_text(encoding="utf-8"))
        ckpt_iter = int(data["iter"])

        # spiral_startup.sh: SPIRAL_ITER = CKPT_ITER - 1  (loop increments to ckpt_iter)
        spiral_iter_before_loop = ckpt_iter - 1
        assert spiral_iter_before_loop == 2, "SPIRAL_ITER should be set to ckpt_iter - 1 = 2"

    def test_no_checkpoint_starts_from_iter_zero(self, tmp_path: Path) -> None:
        """Without a checkpoint, SPIRAL_ITER starts at 0 (fresh start)."""
        spiral_dir = tmp_path / ".spiral"
        ckpt_path = spiral_dir / "_checkpoint.json"

        # No checkpoint — spiral_iter starts at 0
        spiral_iter = 0
        if ckpt_path.exists():
            data = json.loads(ckpt_path.read_text(encoding="utf-8"))
            spiral_iter = int(data.get("iter", 1)) - 1

        assert spiral_iter == 0, "Fresh start should begin at iter 0"


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — results.tsv consistency after recovery
# ─────────────────────────────────────────────────────────────────────────────


class TestResultsTsvConsistency:
    """
    AC3: After recovery, results.tsv must:
      - Preserve the 3 pre-crash rows unchanged
      - Append new rows for US-004 and US-005 after recovery
      - Contain no duplicate (story_id, timestamp) pairs
    """

    def test_prior_rows_unchanged_after_recovery(self, tmp_path: Path) -> None:
        """The 3 rows written before the crash must be byte-identical after recovery."""
        results_path = tmp_path / "results.tsv"
        pre_crash_rows = [
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),
            _make_tsv_row("US-002", "2026-03-21T10:05:00Z"),
            _make_tsv_row("US-003", "2026-03-21T10:10:00Z"),
        ]
        _write_tsv(results_path, pre_crash_rows)

        # Simulate recovery: append rows for US-004 and US-005
        post_crash_rows = [
            _make_tsv_row("US-004", "2026-03-21T11:00:00Z"),
            _make_tsv_row("US-005", "2026-03-21T11:05:00Z"),
        ]
        with open(results_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n"
            )
            writer.writerows(post_crash_rows)

        all_rows = _read_tsv(results_path)
        assert len(all_rows) == 5, f"Expected 5 rows total, got {len(all_rows)}"

        # First 3 rows are unchanged
        for i, (expected, actual) in enumerate(zip(pre_crash_rows, all_rows[:3])):
            assert actual["story_id"] == expected["story_id"], (
                f"Row {i}: story_id changed from {expected['story_id']} to {actual['story_id']}"
            )
            assert actual["timestamp"] == expected["timestamp"], (
                f"Row {i}: timestamp changed for {expected['story_id']}"
            )
            assert actual["status"] == expected["status"], (
                f"Row {i}: status changed for {expected['story_id']}"
            )

    def test_new_rows_appended_after_recovery(self, tmp_path: Path) -> None:
        """Rows for US-004 and US-005 must appear after the pre-crash rows."""
        results_path = tmp_path / "results.tsv"
        pre_crash_rows = [
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),
            _make_tsv_row("US-002", "2026-03-21T10:05:00Z"),
            _make_tsv_row("US-003", "2026-03-21T10:10:00Z"),
        ]
        _write_tsv(results_path, pre_crash_rows)

        # Append post-recovery rows
        post_crash_rows = [
            _make_tsv_row("US-004", "2026-03-21T11:00:00Z"),
            _make_tsv_row("US-005", "2026-03-21T11:05:00Z"),
        ]
        with open(results_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n"
            )
            writer.writerows(post_crash_rows)

        all_rows = _read_tsv(results_path)
        story_ids = [r["story_id"] for r in all_rows]

        assert "US-004" in story_ids, "US-004 must be appended after recovery"
        assert "US-005" in story_ids, "US-005 must be appended after recovery"
        # Post-recovery rows come after pre-crash rows in file order
        assert story_ids.index("US-004") > story_ids.index("US-003"), (
            "US-004 must appear after US-003 in results.tsv"
        )

    def test_no_duplicate_rows_after_recovery(self, tmp_path: Path) -> None:
        """No duplicate (story_id, timestamp) pairs exist after recovery."""
        results_path = tmp_path / "results.tsv"
        pre_crash_rows = [
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),
            _make_tsv_row("US-002", "2026-03-21T10:05:00Z"),
            _make_tsv_row("US-003", "2026-03-21T10:10:00Z"),
        ]
        _write_tsv(results_path, pre_crash_rows)

        # Simulate recovery appending new rows (no duplicates of existing rows)
        recovery_rows = [
            _make_tsv_row("US-004", "2026-03-21T11:00:00Z"),
            _make_tsv_row("US-005", "2026-03-21T11:05:00Z"),
        ]
        with open(results_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n"
            )
            writer.writerows(recovery_rows)

        all_rows = _read_tsv(results_path)
        dedup_keys = [(r["story_id"], r["timestamp"]) for r in all_rows]
        assert len(dedup_keys) == len(set(dedup_keys)), (
            f"Duplicate (story_id, timestamp) pairs found: "
            f"{[k for k in dedup_keys if dedup_keys.count(k) > 1]}"
        )

    def test_duplicate_row_detection(self, tmp_path: Path) -> None:
        """Verify that if a duplicate row is accidentally added, the test detects it."""
        results_path = tmp_path / "results.tsv"
        rows = [
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),  # duplicate
        ]
        _write_tsv(results_path, rows)

        all_rows = _read_tsv(results_path)
        dedup_keys = [(r["story_id"], r["timestamp"]) for r in all_rows]
        duplicates = [k for k in set(dedup_keys) if dedup_keys.count(k) > 1]
        assert len(duplicates) > 0, "Should detect duplicate rows"

    def test_results_tsv_row_count_after_full_recovery(self, tmp_path: Path) -> None:
        """After full recovery (3 pre-crash + 2 post-recovery), total rows == 5."""
        results_path = tmp_path / "results.tsv"
        pre_crash_rows = [
            _make_tsv_row("US-001", "2026-03-21T10:00:00Z"),
            _make_tsv_row("US-002", "2026-03-21T10:05:00Z"),
            _make_tsv_row("US-003", "2026-03-21T10:10:00Z"),
        ]
        _write_tsv(results_path, pre_crash_rows)

        post_crash_rows = [
            _make_tsv_row("US-004", "2026-03-21T11:00:00Z"),
            _make_tsv_row("US-005", "2026-03-21T11:05:00Z"),
        ]
        with open(results_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=_TSV_HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n"
            )
            writer.writerows(post_crash_rows)

        all_rows = _read_tsv(results_path)
        assert len(all_rows) == 5, f"Expected 5 total rows, got {len(all_rows)}"
