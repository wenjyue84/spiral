#!/usr/bin/env python3
"""
SPIRAL — prd.json Write Lock

Provides an exclusive file lock around prd.json read-modify-write cycles
to prevent parallel worker corruption.

Usage:
    from prd_lock import prd_locked

    with prd_locked("prd.json", timeout=30) as prd:
        for s in prd["userStories"]:
            if s["id"] == "US-040":
                s["passes"] = True
        # prd is written back atomically on context-manager exit

The lock file is ``<prd_path>.lock``.  On Windows the lock uses
``msvcrt.locking``; on POSIX it uses ``fcntl.flock``.
"""
import contextlib
import errno
import json
import logging
import os
import random
import sys
import time
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any, TypeVar

_T = TypeVar("_T")

# ── Retry configuration ────────────────────────────────────────────────────────

_MAX_IO_RETRIES = 5
_IO_BASE_DELAY = 0.1  # seconds; actual delay = base * 2^attempt + jitter

# errno values for transient lock/permission errors (POSIX + Windows)
_RETRYABLE_ERRNOS: frozenset[int] = frozenset(
    [
        errno.EACCES,   # 13 — Permission denied (Windows antivirus, indexer)
        errno.ETXTBSY,  # 26 — Text file busy (Linux)
    ]
)

# ── Stale lock detection helpers ──────────────────────────────────────────────


def _write_lock_pid(fd: int) -> None:
    """Write current PID to lock file at offset 1 (after lock byte 0)."""
    os.lseek(fd, 1, os.SEEK_SET)
    os.write(fd, str(os.getpid()).encode())


def _read_lock_pid(lock_path: str) -> int | None:
    """Read PID from lock file without acquiring the lock."""
    try:
        with open(lock_path, "rb") as f:
            f.seek(1)
            data = f.read().strip()
            return int(data) if data else None
    except (OSError, ValueError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Check if process is still running (cross-platform)."""
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # process exists but we can't signal it

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import append_jsonl, configure_utf8_stdout
configure_utf8_stdout()

# ── Transient I/O retry helpers ────────────────────────────────────────────────

_log = logging.getLogger(__name__)


def _is_retryable_error(exc: OSError) -> bool:
    """Return True for transient filesystem errors worth retrying."""
    if isinstance(exc, PermissionError):
        return True
    return exc.errno in _RETRYABLE_ERRNOS


def _retry_io(
    fn: Callable[[], _T],
    *,
    events_path: str = "spiral_events.jsonl",
) -> _T:
    """Call *fn()* with exponential-backoff retry on transient I/O errors.

    Retries up to ``_MAX_IO_RETRIES`` times for ``PermissionError`` or
    ``OSError`` with errno ``EACCES``/``ETXTBSY``.  Backoff formula::

        delay = _IO_BASE_DELAY * 2**attempt + random.uniform(0, 0.1)

    After all retries are exhausted the error is logged to *events_path*
    (``spiral_events.jsonl``) and re-raised.

    Parameters
    ----------
    fn:
        Zero-argument callable to invoke.
    events_path:
        Path to the JSONL audit log.  Pass ``""`` to disable event logging.
    """
    last_exc: OSError | None = None
    for attempt in range(_MAX_IO_RETRIES + 1):
        try:
            return fn()
        except OSError as exc:
            if not _is_retryable_error(exc) or attempt >= _MAX_IO_RETRIES:
                # Exhausted or non-retryable — log and re-raise
                if events_path:
                    try:
                        append_jsonl(
                            events_path,
                            {
                                "event_type": "prd_io_error",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "error": str(exc),
                                "errno": exc.errno,
                                "attempts": attempt + 1,
                            },
                        )
                    except Exception:  # pragma: no cover — logging must never crash
                        pass
                raise
            last_exc = exc
            delay = _IO_BASE_DELAY * (2**attempt) + random.uniform(0, 0.1)
            _log.debug(
                "[prd_lock] Retry %d/%d after transient I/O error (delay=%.3fs): %s",
                attempt + 1,
                _MAX_IO_RETRIES,
                delay,
                exc,
            )
            time.sleep(delay)
    # Should be unreachable, but satisfy the type-checker
    raise last_exc  # type: ignore[misc]


class PrdLockTimeout(Exception):
    """Raised when the lock cannot be acquired within the timeout period."""
    pass


def _lock_fd(fd: int) -> None:
    """Acquire an exclusive, non-blocking lock on an open file descriptor."""
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    """Release the lock on an open file descriptor."""
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


@contextlib.contextmanager
def prd_locked(
    prd_path: str,
    timeout: float = 30.0,
    events_path: str = "spiral_events.jsonl",
) -> Generator[dict[str, Any], None, None]:
    """Context manager: acquire lock, yield loaded prd dict, write back on exit.

    Parameters
    ----------
    prd_path : str
        Path to prd.json.
    timeout : float
        Maximum seconds to wait for the lock (default 30).
    events_path : str
        Path to the JSONL audit log for transient I/O errors (default
        ``"spiral_events.jsonl"``).  Pass ``""`` to disable event logging.

    Yields
    ------
    dict
        The parsed prd.json contents.  Mutate in-place; the dict is
        written back atomically when the ``with`` block exits normally.

    Raises
    ------
    PrdLockTimeout
        If the lock cannot be acquired within *timeout* seconds.
    FileNotFoundError
        If *prd_path* does not exist.
    """
    lock_path = prd_path + ".lock"
    fd = None
    poll_interval = 0.1  # seconds between retries

    try:
        # Open (or create) the lock file
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)

        # Retry loop with timeout
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock_fd(fd)
                break  # lock acquired
            except OSError:
                if time.monotonic() >= deadline:
                    # Stale lock detection: check if holding process is dead
                    holder_pid = _read_lock_pid(lock_path)
                    if holder_pid is not None and not _is_pid_alive(holder_pid):
                        print(
                            f"[prd_lock] WARNING: breaking stale lock "
                            f"(PID {holder_pid} is dead)",
                            file=sys.stderr,
                        )
                        os.close(fd)
                        fd = None  # prevent double-close in finally
                        try:
                            os.unlink(lock_path)
                        except OSError:
                            pass
                        # Retry once with a fresh fd
                        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
                        try:
                            _lock_fd(fd)
                        except OSError:
                            raise PrdLockTimeout(
                                f"Could not acquire prd.json lock within {timeout}s "
                                f"(lock file: {lock_path})"
                            )
                        break  # lock acquired after stale break
                    raise PrdLockTimeout(
                        f"Could not acquire prd.json lock within {timeout}s "
                        f"(lock file: {lock_path})"
                    )
                time.sleep(poll_interval)

        # Write PID for stale detection by other processes
        _write_lock_pid(fd)

        # ── Lock held: read prd.json (with transient I/O retry) ─────────
        def _read() -> dict[str, Any]:
            with open(prd_path, encoding="utf-8") as f:
                return json.load(f)  # type: ignore[return-value]

        prd = _retry_io(_read, events_path=events_path)

        yield prd

        # ── Still holding lock: atomic write back (with retry) ──────────
        def _write() -> None:
            tmp_path = prd_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(prd, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, prd_path)

        _retry_io(_write, events_path=events_path)

    finally:
        if fd is not None:
            _unlock_fd(fd)
            os.close(fd)
