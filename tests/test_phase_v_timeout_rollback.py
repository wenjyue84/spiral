"""tests/test_phase_v_timeout_rollback.py — US-1081

Integration test: Phase V test timeout triggers story rollback + retry escalation.

Acceptance criteria:
  AC1 — Timeout triggers git checkout HEAD (worktree clean) and records
        status='timeout' entry in results.tsv.
  AC2 — Story retry counter increments; model escalates haiku→sonnet on retry.
  AC3 — 3-story federated prd.json: A times out, B succeeds, C fails normally;
        final prd.json and results.tsv match expected state.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from impl.retry import execute_ralph
from results_tsv import HEADER, ResultsRecord

# ── Fixtures & helpers ─────────────────────────────────────────────────────────


def _init_repo(directory: Path) -> None:
    """Initialize a minimal git repo with one commit so HEAD is valid.

    Includes impl_candidate.py as a tracked file so modifications to it
    can be rolled back by 'git checkout HEAD -- .' (which only reverts tracked files).
    """
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "test@spiral.test"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(cmd, cwd=directory, check=True, capture_output=True)
    (directory / "base.txt").write_text("base", encoding="utf-8")
    # Track impl_candidate.py so it can be modified (and rolled back) in tests
    (directory / "impl_candidate.py").write_text("# original\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=directory, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=directory, check=True, capture_output=True)


def _write_prd(directory: Path) -> Path:
    """Write prd.json with 3 stories (A=haiku, B=haiku, C=haiku) and return path."""
    prd: dict[str, Any] = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": [
            {"id": "US-A01", "title": "Story A", "passes": False, "priority": "high", "model": "haiku"},
            {"id": "US-B01", "title": "Story B", "passes": False, "priority": "high", "model": "haiku"},
            {"id": "US-C01", "title": "Story C", "passes": False, "priority": "medium", "model": "haiku"},
        ],
    }
    prd_path = directory / "prd.json"
    prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return prd_path


def _timeout_exc(timeout: int = 60) -> subprocess.TimeoutExpired:
    """Build a TimeoutExpired with empty bytes output."""
    exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=timeout)
    exc.stdout = b""
    exc.stderr = b""
    return exc


def _mock_proc(returncode: int) -> MagicMock:
    """Build a mock CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = "ok" if returncode == 0 else ""
    m.stderr = "" if returncode == 0 else "error"
    return m


def _run_story(
    story_id: str,
    model: str,
    mock_kwargs: dict[str, Any],
    worktree: Path,
    prd_path: Path,
    retry_counts: dict[str, int],
    tsv_records: list[ResultsRecord],
) -> str:
    """Mini-orchestrator: runs one story, handles result, updates prd + tsv.

    Returns 'timeout' | 'success' | 'failed'.
    """
    with patch("subprocess.run", **mock_kwargs):
        result = execute_ralph(story_id, model, ["ralph", "--story", story_id], timeout=60)

    if result["status"] == "retry_escalated":
        # AC1: Rollback worktree to clean state
        subprocess.run(
            ["git", "checkout", "HEAD", "--", "."],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        # AC2: Increment retry counter and escalate model in prd.json
        retry_counts[story_id] = retry_counts.get(story_id, 0) + 1
        prd_data: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        next_model = result.get("next_model") or model
        for s in prd_data["userStories"]:
            if s["id"] == story_id:
                s["model"] = next_model
                break
        prd_path.write_text(json.dumps(prd_data, indent=2), encoding="utf-8")
        tsv_records.append(
            ResultsRecord(
                timestamp="2026-01-01T00:00:00Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id=story_id,
                story_title="",
                status="timeout",
                duration_sec="60",
                model=model,
                retry_num=str(retry_counts[story_id]),
                commit_sha="",
                run_id="test",
                failure_root_cause="timeout",
            )
        )
        return "timeout"

    if result["status"] == "passed":
        prd_data = json.loads(prd_path.read_text(encoding="utf-8"))
        for s in prd_data["userStories"]:
            if s["id"] == story_id:
                s["passes"] = True
                break
        prd_path.write_text(json.dumps(prd_data, indent=2), encoding="utf-8")
        tsv_records.append(
            ResultsRecord(
                timestamp="2026-01-01T00:00:00Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id=story_id,
                story_title="",
                status="success",
                duration_sec="10",
                model=model,
                retry_num="0",
                commit_sha="abc123",
                run_id="test",
            )
        )
        return "success"

    # failed
    tsv_records.append(
        ResultsRecord(
            timestamp="2026-01-01T00:00:00Z",
            spiral_iter="1",
            ralph_iter="1",
            story_id=story_id,
            story_title="",
            status="failed",
            duration_sec="5",
            model=model,
            retry_num="0",
            commit_sha="",
            run_id="test",
            failure_root_cause="nonzero_exit",
        )
    )
    return "failed"


# ── AC1: Timeout triggers git rollback + timeout_status in results.tsv ─────────


class TestTimeoutRollback:
    """AC1 — timeout reverts worktree and records status='timeout' in results.tsv."""

    def test_worktree_clean_after_timeout_rollback(self, tmp_path: Path) -> None:
        """Dirty worktree becomes clean after git checkout HEAD -- . on timeout."""
        _init_repo(tmp_path)
        prd_path = _write_prd(tmp_path)

        # Simulate an implementation attempt modifying a tracked file
        (tmp_path / "impl_candidate.py").write_text("# modified by worker\n", encoding="utf-8")

        def _tracked_changes(repo: Path) -> str:
            """Return porcelain lines for tracked changes only (exclude untracked ??)."""
            out = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
            return "\n".join(ln for ln in out.splitlines() if not ln.startswith("??"))

        dirty = _tracked_changes(tmp_path)
        assert dirty, "Worktree should have tracked changes before rollback"

        _run_story(
            "US-A01",
            "haiku",
            {"side_effect": _timeout_exc(60)},
            tmp_path,
            prd_path,
            {},
            [],
        )

        clean = _tracked_changes(tmp_path)
        assert not clean, "Tracked file changes must be reverted after git rollback"

    def test_timeout_status_recorded_in_tsv(self, tmp_path: Path) -> None:
        """results.tsv must contain status='timeout' entry for story that timed out."""
        _init_repo(tmp_path)
        prd_path = _write_prd(tmp_path)
        tsv_records: list[ResultsRecord] = []

        _run_story("US-A01", "haiku", {"side_effect": _timeout_exc(60)}, tmp_path, prd_path, {}, tsv_records)

        assert any(r.status == "timeout" and r.story_id == "US-A01" for r in tsv_records)


# ── AC2: Retry counter increments, model escalates haiku→sonnet ────────────────


class TestRetryEscalation:
    """AC2 — retry_counts incremented; prd.json model field escalated haiku→sonnet."""

    def test_retry_counter_increments(self, tmp_path: Path) -> None:
        """retry_counts[story_id] increases from 0 to 1 after first timeout."""
        _init_repo(tmp_path)
        prd_path = _write_prd(tmp_path)
        retry_counts: dict[str, int] = {}

        assert retry_counts.get("US-A01", 0) == 0
        _run_story("US-A01", "haiku", {"side_effect": _timeout_exc()}, tmp_path, prd_path, retry_counts, [])
        assert retry_counts["US-A01"] == 1

    def test_model_escalates_haiku_to_sonnet(self, tmp_path: Path) -> None:
        """After timeout on haiku, prd.json model for the story is updated to 'sonnet'."""
        _init_repo(tmp_path)
        prd_path = _write_prd(tmp_path)

        _run_story("US-A01", "haiku", {"side_effect": _timeout_exc()}, tmp_path, prd_path, {}, [])

        prd_after: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        model_after = next(s["model"] for s in prd_after["userStories"] if s["id"] == "US-A01")
        assert model_after == "sonnet", f"Expected sonnet after haiku timeout, got {model_after}"


# ── AC3: Full 3-story run ──────────────────────────────────────────────────────


class TestThreeStoryFederatedRun:
    """AC3 — 3-story: A→timeout, B→success, C→fail; prd.json + results.tsv complete."""

    def test_three_story_final_state(self, tmp_path: Path) -> None:
        """Run 3 stories; verify final prd.json and results.tsv match expected state."""
        _init_repo(tmp_path)
        prd_path = _write_prd(tmp_path)
        tsv_path = tmp_path / "results.tsv"
        retry_counts: dict[str, int] = {}
        tsv_records: list[ResultsRecord] = []

        status_a = _run_story(
            "US-A01", "haiku", {"side_effect": _timeout_exc(60)}, tmp_path, prd_path, retry_counts, tsv_records
        )
        status_b = _run_story(
            "US-B01", "haiku", {"return_value": _mock_proc(0)}, tmp_path, prd_path, retry_counts, tsv_records
        )
        status_c = _run_story(
            "US-C01", "haiku", {"return_value": _mock_proc(1)}, tmp_path, prd_path, retry_counts, tsv_records
        )

        assert status_a == "timeout"
        assert status_b == "success"
        assert status_c == "failed"

        # Verify prd.json final state
        final_prd: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        by_id = {s["id"]: s for s in final_prd["userStories"]}
        assert by_id["US-A01"]["passes"] is False, "A still pending after rollback"
        assert by_id["US-A01"]["model"] == "sonnet", "A model escalated to sonnet"
        assert by_id["US-B01"]["passes"] is True, "B succeeded"
        assert by_id["US-C01"]["passes"] is False, "C failed normally"

        # Write and re-read results.tsv
        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER, extrasaction="ignore", delimiter="\t")
            writer.writeheader()
            for rec in tsv_records:
                writer.writerow(asdict(rec))

        with open(tsv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))

        assert len(rows) == 3, f"Expected 3 results.tsv rows, got {len(rows)}"
        tsv_by_id = {r["story_id"]: r for r in rows}
        assert tsv_by_id["US-A01"]["status"] == "timeout"
        assert tsv_by_id["US-B01"]["status"] == "success"
        assert tsv_by_id["US-C01"]["status"] == "failed"
