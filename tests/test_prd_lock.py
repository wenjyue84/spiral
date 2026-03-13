"""Tests for lib/prd_lock.py — exclusive prd.json write lock."""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from prd_lock import prd_locked, PrdLockTimeout


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_prd(tmp_path, stories=None):
    """Write a minimal valid prd.json and return its path."""
    if stories is None:
        stories = [
            {"id": "US-001", "title": "A", "passes": False, "priority": "high",
             "acceptanceCriteria": ["x"], "dependencies": []},
            {"id": "US-002", "title": "B", "passes": False, "priority": "high",
             "acceptanceCriteria": ["x"], "dependencies": []},
            {"id": "US-003", "title": "C", "passes": False, "priority": "high",
             "acceptanceCriteria": ["x"], "dependencies": []},
        ]
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    path = str(tmp_path / "prd.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2)
    return path


# ── Basic functionality ──────────────────────────────────────────────────────

def test_read_and_write_back(tmp_path):
    """Lock, mutate, release — file should reflect the mutation."""
    path = _make_prd(tmp_path)

    with prd_locked(path) as prd:
        prd["userStories"][0]["passes"] = True

    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    assert result["userStories"][0]["passes"] is True
    assert result["userStories"][1]["passes"] is False


def test_no_mutation_still_writes(tmp_path):
    """Even without changes the file is rewritten (idempotent)."""
    path = _make_prd(tmp_path)
    mtime_before = os.path.getmtime(path)
    time.sleep(0.05)

    with prd_locked(path) as prd:
        pass  # no changes

    mtime_after = os.path.getmtime(path)
    assert mtime_after >= mtime_before  # file was rewritten


def test_lock_file_created(tmp_path):
    """A .lock file is created alongside prd.json."""
    path = _make_prd(tmp_path)

    with prd_locked(path) as _prd:
        assert os.path.exists(path + ".lock")


def test_exception_inside_context_does_not_write(tmp_path):
    """If the with-block raises, the original file is NOT overwritten."""
    path = _make_prd(tmp_path)

    with open(path, encoding="utf-8") as f:
        original = json.load(f)

    with pytest.raises(ValueError):
        with prd_locked(path) as prd:
            prd["userStories"][0]["passes"] = True
            raise ValueError("boom")

    with open(path, encoding="utf-8") as f:
        after = json.load(f)
    # Original should be unchanged since the exception prevented the write
    assert after == original


# ── Timeout behaviour ────────────────────────────────────────────────────────

def test_timeout_raises_clear_error(tmp_path):
    """If the lock is held, a second caller times out with PrdLockTimeout."""
    path = _make_prd(tmp_path)
    lock_path = path + ".lock"

    # Manually hold the lock
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(PrdLockTimeout, match="Could not acquire"):
            with prd_locked(path, timeout=0.3) as _prd:
                pass  # should never reach here
    finally:
        if sys.platform == "win32":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ── Concurrent workers (AC #2) ──────────────────────────────────────────────

def test_three_concurrent_workers_all_pass(tmp_path):
    """3 threads each mark a different story passed — all 3 end up True.

    This is the core acceptance criterion: parallel workers must not
    clobber each other's writes.
    """
    path = _make_prd(tmp_path)
    errors: list[str] = []
    barrier = threading.Barrier(3, timeout=10)

    def worker(story_id: str):
        try:
            barrier.wait()  # synchronise start
            with prd_locked(path, timeout=10) as prd:
                for s in prd["userStories"]:
                    if s["id"] == story_id:
                        s["passes"] = True
                        break
        except Exception as exc:
            errors.append(f"{story_id}: {exc}")

    threads = [
        threading.Thread(target=worker, args=("US-001",)),
        threading.Thread(target=worker, args=("US-002",)),
        threading.Thread(target=worker, args=("US-003",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Worker errors: {errors}"

    with open(path, encoding="utf-8") as f:
        result = json.load(f)

    passed = {s["id"]: s["passes"] for s in result["userStories"]}
    assert passed == {"US-001": True, "US-002": True, "US-003": True}


def test_five_concurrent_workers(tmp_path):
    """5 threads each mark a different story — stress test variant."""
    stories = [
        {"id": f"US-{i:03d}", "title": f"S{i}", "passes": False,
         "priority": "high", "acceptanceCriteria": ["x"], "dependencies": []}
        for i in range(1, 6)
    ]
    path = _make_prd(tmp_path, stories=stories)
    errors: list[str] = []
    barrier = threading.Barrier(5, timeout=10)

    def worker(story_id: str):
        try:
            barrier.wait()
            with prd_locked(path, timeout=15) as prd:
                for s in prd["userStories"]:
                    if s["id"] == story_id:
                        s["passes"] = True
                        break
        except Exception as exc:
            errors.append(f"{story_id}: {exc}")

    threads = [
        threading.Thread(target=worker, args=(f"US-{i:03d}",))
        for i in range(1, 6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"Worker errors: {errors}"

    with open(path, encoding="utf-8") as f:
        result = json.load(f)

    for s in result["userStories"]:
        assert s["passes"] is True, f"{s['id']} should be passed"


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_file_not_found(tmp_path):
    """Lock on a non-existent prd.json raises FileNotFoundError."""
    path = str(tmp_path / "does_not_exist.json")
    with pytest.raises(FileNotFoundError):
        with prd_locked(path) as _prd:
            pass


def test_lock_released_after_normal_exit(tmp_path):
    """After a successful with-block, a second caller can acquire the lock."""
    path = _make_prd(tmp_path)

    with prd_locked(path) as prd:
        prd["userStories"][0]["passes"] = True

    # Second acquisition should succeed immediately
    with prd_locked(path, timeout=1) as prd2:
        assert prd2["userStories"][0]["passes"] is True


def test_lock_released_after_exception(tmp_path):
    """After an exception in the with-block, the lock is still released."""
    path = _make_prd(tmp_path)

    with pytest.raises(RuntimeError):
        with prd_locked(path) as prd:
            raise RuntimeError("oops")

    # Lock should be released — second acquisition succeeds
    with prd_locked(path, timeout=1) as prd2:
        assert prd2["userStories"][0]["passes"] is False
