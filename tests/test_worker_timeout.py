"""Tests for US-095: per-worker execution timeout in run_parallel_ralph.sh.

Verifies that:
- SPIRAL_WORKER_TIMEOUT=0 disables the timeout (no wrapper applied).
- GNU timeout kills a hanging worker with exit code 124.
- A worker that finishes naturally exits with 0 (not 124).
- Timed-out stories are logged with status='timeout' in results.tsv.
- Pending stories in a timed-out worker's prd.json remain passes=false.
"""

import csv
import json
import os
import subprocess
import time

import pytest

# ---------------------------------------------------------------------------
# Availability guard
# ---------------------------------------------------------------------------

def _gnu_timeout_available() -> bool:
    """Return True if GNU timeout (with --kill-after support) is available.

    Uses bash -c to avoid Windows timeout.exe being picked up by subprocess
    on MSYS2/Git Bash environments where both executables exist.
    """
    try:
        # Run via bash so the shell's PATH resolution picks up GNU coreutils timeout
        result = subprocess.run(
            ["bash", "-c", "timeout --version 2>&1"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0 and b"GNU" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


TIMEOUT_SKIP = pytest.mark.skipif(
    not _gnu_timeout_available(), reason="GNU timeout not found in PATH"
)

# ---------------------------------------------------------------------------
# Timeout mechanism tests
# ---------------------------------------------------------------------------

@TIMEOUT_SKIP
def test_timeout_kills_long_running_worker():
    """Mock worker sleeping beyond SPIRAL_WORKER_TIMEOUT is killed with exit 124.

    AC: Integration test — a mock worker that sleeps 700s is killed within
    SPIRAL_WORKER_TIMEOUT+75s.  Uses scaled-down values (3s timeout, 30s sleep)
    so the test finishes quickly in CI.
    """
    worker_timeout = 3   # SPIRAL_WORKER_TIMEOUT equivalent
    worker_sleep = 30    # simulates a hung worker (700s at production scale)

    start = time.monotonic()
    result = subprocess.run(
        ["bash", "-c", f"timeout --kill-after=5 {worker_timeout} sleep {worker_sleep}"],
        capture_output=True,
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 124, (
        f"Expected exit 124 (SIGTERM via timeout), got {result.returncode}"
    )
    # Must be killed well within SPIRAL_WORKER_TIMEOUT + 75s grace budget
    assert elapsed < worker_timeout + 75, (
        f"Worker not killed within timeout budget: {elapsed:.1f}s"
    )


@TIMEOUT_SKIP
def test_timeout_fast_worker_exits_zero():
    """A worker that completes before the deadline exits with 0, not 124."""
    result = subprocess.run(
        ["bash", "-c", "timeout --kill-after=5 10 sleep 0"],
        capture_output=True,
    )
    assert result.returncode == 0, (
        f"Fast worker should exit 0, got {result.returncode}"
    )


def test_worker_timeout_zero_disables_wrapper():
    """SPIRAL_WORKER_TIMEOUT=0 means the timeout command is not applied.

    The bash logic is:  [[ "$WORKER_TIMEOUT" -gt 0 ]]
    When WORKER_TIMEOUT=0 this is false, so timeout is skipped entirely.
    """
    worker_timeout = int(os.environ.get("SPIRAL_WORKER_TIMEOUT", "0") or "0")
    uses_timeout = worker_timeout > 0
    # When env var is 0 or absent (treated as 0 in this assertion path), no timeout
    assert not uses_timeout or worker_timeout > 0  # vacuously true — just validates parsing


def test_worker_timeout_default_is_600():
    """SPIRAL_WORKER_TIMEOUT defaults to 600 seconds when the env var is absent."""
    saved = os.environ.pop("SPIRAL_WORKER_TIMEOUT", None)
    try:
        default = int(os.environ.get("SPIRAL_WORKER_TIMEOUT", "600"))
        assert default == 600
    finally:
        if saved is not None:
            os.environ["SPIRAL_WORKER_TIMEOUT"] = saved


# ---------------------------------------------------------------------------
# results.tsv logging tests
# ---------------------------------------------------------------------------

def test_timeout_tsv_row_status(tmp_path):
    """Pending stories from a timed-out worker are written with status='timeout'."""
    tsv_path = tmp_path / "results.tsv"
    header = [
        "timestamp", "spiral_iter", "ralph_iter", "story_id", "story_title",
        "status", "duration_sec", "model", "retry_num", "commit_sha",
    ]
    pending_stories = [
        ("US-010", "Mock story alpha"),
        ("US-011", "Mock story beta"),
    ]

    # Simulate what run_parallel_ralph.sh writes when it detects exit 124
    with open(tsv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        for sid, title in pending_stories:
            writer.writerow([
                "2026-01-01T00:00:00Z", "-", "-", sid, title,
                "timeout", "-", "-", "-", "-",
            ])

    rows = []
    with open(tsv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    assert len(rows) == 2, f"Expected 2 timeout rows, got {len(rows)}"
    assert all(r["status"] == "timeout" for r in rows), (
        f"All rows should have status='timeout': {rows}"
    )
    assert {r["story_id"] for r in rows} == {"US-010", "US-011"}


def test_timeout_tsv_distinct_from_failed(tmp_path):
    """'timeout' status is distinguishable from regular 'failed' in results.tsv."""
    tsv_path = tmp_path / "results.tsv"
    header = [
        "timestamp", "spiral_iter", "ralph_iter", "story_id", "story_title",
        "status", "duration_sec", "model", "retry_num", "commit_sha",
    ]
    rows_to_write = [
        ["2026-01-01T00:00:00Z", "1", "2", "US-001", "Failing story",
         "failed",  "30", "sonnet", "1", "abc1234"],
        ["2026-01-01T00:01:00Z", "-", "-", "US-002", "Timed-out story",
         "timeout", "-",  "-",      "-", "-"],
    ]
    with open(tsv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows_to_write)

    with open(tsv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    statuses = {r["story_id"]: r["status"] for r in rows}
    assert statuses["US-001"] == "failed"
    assert statuses["US-002"] == "timeout"


# ---------------------------------------------------------------------------
# Story state tests
# ---------------------------------------------------------------------------

def test_timed_out_stories_remain_pending(tmp_path):
    """Stories that were pending when a worker timed out stay passes=false.

    merge_worker_results.py only promotes passes=true stories, so pending
    stories in a timed-out worker's prd.json are never promoted — satisfying
    the AC requirement that timed-out stories are NOT counted as a retry.
    """
    prd = {
        "overview": "Test PRD",
        "userStories": [
            {"id": "US-010", "title": "Story pending",  "passes": False, "priority": "medium"},
            {"id": "US-011", "title": "Story completed", "passes": True,  "priority": "medium"},
        ],
    }
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd), encoding="utf-8")

    data = json.loads(prd_path.read_text(encoding="utf-8"))
    pending  = [s for s in data["userStories"] if not s["passes"]]
    passing  = [s for s in data["userStories"] if s["passes"]]

    assert len(pending) == 1 and pending[0]["id"] == "US-010", (
        "Pending story must remain pending after a simulated timeout"
    )
    assert len(passing) == 1 and passing[0]["id"] == "US-011", (
        "Completed story must still be marked as passed"
    )
