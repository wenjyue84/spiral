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
import json
import os
import shutil
import sys
import time

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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
def prd_locked(prd_path: str, timeout: float = 30.0):
    """Context manager: acquire lock, yield loaded prd dict, write back on exit.

    Parameters
    ----------
    prd_path : str
        Path to prd.json.
    timeout : float
        Maximum seconds to wait for the lock (default 30).

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
                    raise PrdLockTimeout(
                        f"Could not acquire prd.json lock within {timeout}s "
                        f"(lock file: {lock_path})"
                    )
                time.sleep(poll_interval)

        # ── Lock held: read prd.json ────────────────────────────────────
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)

        yield prd

        # ── Still holding lock: atomic write back ───────────────────────
        tmp_path = prd_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(prd, f, indent=2, ensure_ascii=False)
            f.write("\n")
        shutil.move(tmp_path, prd_path)

    finally:
        if fd is not None:
            _unlock_fd(fd)
            os.close(fd)
