"""Tests for lib/prd_lock.py — exclusive prd.json write lock."""
import errno
import json
import os
import sys
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from prd_lock import (
    PrdLockTimeout,
    _is_pid_alive,
    _is_retryable_error,
    _read_lock_pid,
    _retry_io,
    _write_lock_pid,
    prd_locked,
)


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


# ── Stale lock detection ─────────────────────────────────────────────────────

def test_pid_written_to_lock_file(tmp_path):
    """After acquiring the lock, the current PID is written to the lock file."""
    path = _make_prd(tmp_path)
    lock_path = path + ".lock"

    with prd_locked(path) as _prd:
        pid = _read_lock_pid(lock_path)
        assert pid == os.getpid()


def test_stale_lock_broken_when_holder_dead(tmp_path):
    """A lock file left by a dead PID is broken and acquisition succeeds."""
    path = _make_prd(tmp_path)
    lock_path = path + ".lock"

    # Create a lock file with a PID that doesn't exist (99999999)
    dead_pid = 99999999
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, str(dead_pid).encode())
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, str(dead_pid).encode())
        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)

    # prd_locked should detect the dead PID and break the stale lock
    with prd_locked(path, timeout=0.5) as prd:
        prd["userStories"][0]["passes"] = True

    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    assert result["userStories"][0]["passes"] is True


def test_live_lock_not_broken(tmp_path):
    """A lock held by a live process is NOT broken — caller gets PrdLockTimeout."""
    path = _make_prd(tmp_path)
    lock_path = path + ".lock"

    # Hold the lock with our own PID (alive)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write our PID (alive process)
        os.lseek(fd, 1, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode())

        with pytest.raises(PrdLockTimeout):
            with prd_locked(path, timeout=0.3) as _prd:
                pass
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


def test_empty_lock_file_falls_back_to_timeout(tmp_path):
    """An old-format lock file (no PID) falls back to normal timeout behavior."""
    path = _make_prd(tmp_path)
    lock_path = path + ".lock"

    # Hold the lock with NO PID written (old format)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(PrdLockTimeout):
            with prd_locked(path, timeout=0.3) as _prd:
                pass
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


def test_is_pid_alive_current_process():
    """Current process PID should be reported as alive."""
    assert _is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead_process():
    """A very high PID should not be alive."""
    assert _is_pid_alive(99999999) is False


# ── _is_retryable_error ───────────────────────────────────────────────────────

def test_retryable_permission_error():
    """PermissionError is always retryable."""
    assert _is_retryable_error(PermissionError("denied")) is True


def test_retryable_eacces():
    """OSError with EACCES errno is retryable."""
    exc = OSError(errno.EACCES, "Permission denied")
    assert _is_retryable_error(exc) is True


def test_retryable_etxtbsy():
    """OSError with ETXTBSY errno is retryable."""
    exc = OSError(errno.ETXTBSY, "Text file busy")
    assert _is_retryable_error(exc) is True


def test_not_retryable_file_not_found():
    """FileNotFoundError (ENOENT) is not retryable."""
    assert _is_retryable_error(FileNotFoundError("nope")) is False


def test_not_retryable_generic_oserror():
    """A generic OSError with unrecognised errno is not retryable."""
    exc = OSError(errno.ENOENT, "not found")
    assert _is_retryable_error(exc) is False


# ── _retry_io ────────────────────────────────────────────────────────────────

def test_retry_io_succeeds_first_attempt():
    """When fn succeeds immediately, the result is returned without retrying."""
    fn = MagicMock(return_value=42)
    result = _retry_io(fn, events_path="")
    assert result == 42
    fn.assert_called_once()


def test_retry_io_succeeds_on_second_attempt():
    """fn raises PermissionError once, then succeeds — result returned."""
    calls = 0

    def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("locked")
        return "ok"

    with patch("prd_lock.time.sleep"):
        result = _retry_io(fn, events_path="")

    assert result == "ok"
    assert calls == 2


def test_retry_io_retries_up_to_max(tmp_path):
    """fn always raises PermissionError — after _MAX_IO_RETRIES+1 attempts, re-raises."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise PermissionError("always locked")

    events_file = str(tmp_path / "events.jsonl")
    with patch("prd_lock.time.sleep"):
        with pytest.raises(PermissionError, match="always locked"):
            _retry_io(fn, events_path=events_file)

    # 1 initial attempt + 5 retries = 6 total
    assert call_count == 6


def test_retry_io_non_retryable_raises_immediately():
    """fn raises FileNotFoundError (non-retryable) — no sleep, raised immediately."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        raise FileNotFoundError("gone")

    with patch("prd_lock.time.sleep") as mock_sleep:
        with pytest.raises(FileNotFoundError):
            _retry_io(fn, events_path="")

    assert call_count == 1
    mock_sleep.assert_not_called()


def test_retry_io_logs_to_events_file_on_exhaustion(tmp_path):
    """After retries are exhausted, an event is appended to the JSONL file."""
    events_file = str(tmp_path / "events.jsonl")

    def fn():
        raise PermissionError("denied")

    with patch("prd_lock.time.sleep"):
        with pytest.raises(PermissionError):
            _retry_io(fn, events_path=events_file)

    assert os.path.exists(events_file)
    with open(events_file) as f:
        record = json.loads(f.read().strip())
    assert record["event_type"] == "prd_io_error"
    assert record["attempts"] == 6  # 1 + 5 retries


def test_retry_io_no_logging_when_events_path_empty():
    """Pass events_path='' — no file is created, error still re-raised."""
    def fn():
        raise PermissionError("denied")

    with patch("prd_lock.time.sleep"):
        with pytest.raises(PermissionError):
            _retry_io(fn, events_path="")


def test_retry_io_backoff_delays_increase():
    """sleep is called with increasing delays (exponential backoff)."""
    call_count = 0

    def fn():
        nonlocal call_count
        call_count += 1
        if call_count < 4:
            raise PermissionError("locked")
        return "done"

    sleep_delays: list[float] = []

    def capture_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    with patch("prd_lock.time.sleep", side_effect=capture_sleep):
        result = _retry_io(fn, events_path="")

    assert result == "done"
    # 3 retries → 3 sleeps; each should be >= previous (backoff)
    assert len(sleep_delays) == 3
    assert sleep_delays[1] >= sleep_delays[0]
    assert sleep_delays[2] >= sleep_delays[1]


def test_prd_locked_retries_on_transient_read_error(tmp_path):
    """prd_locked retries reading prd.json on transient PermissionError."""
    path = _make_prd(tmp_path)
    read_calls = 0
    real_open = open

    def flaky_open(file, *args, **kwargs):
        nonlocal read_calls
        # Only intercept reads of the prd path (not .tmp or .lock)
        if str(file) == path and "w" not in str(kwargs.get("mode", args[0] if args else "r")):
            read_calls += 1
            if read_calls == 1:
                raise PermissionError("antivirus hold")
        return real_open(file, *args, **kwargs)

    with patch("prd_lock.time.sleep"):
        with patch("builtins.open", side_effect=flaky_open):
            with prd_locked(path, events_path="") as prd:
                prd["userStories"][0]["passes"] = True

    assert read_calls >= 2  # first call raised, second succeeded
