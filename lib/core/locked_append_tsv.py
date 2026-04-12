#!/usr/bin/env python3
# lib/core/locked_append_tsv.py — Append to TSV files with exclusive file locking
#
# Usage: python lib/core/locked_append_tsv.py <tsv_file> <row_data>
#
# Acquires an exclusive file lock before appending and releases it after.
# Uses fcntl.flock on POSIX and msvcrt.locking on Windows to prevent
# corruption when multiple processes append concurrently.

import os
import sys
import time
from typing import TYPE_CHECKING

# Platform-specific imports
if os.name == "nt":
    import msvcrt
else:
    import fcntl

if TYPE_CHECKING:
    import msvcrt  # noqa: F401 — stub for type checking on Linux


def locked_append_tsv(tsv_file: str, row_data: str, timeout: float = 10.0) -> None:
    """Append a row to a TSV file with exclusive file locking.

    Acquires an exclusive lock before appending and releases it after.
    Falls back to raw append if lock cannot be acquired within timeout.

    Parameters
    ----------
    tsv_file : str
        Path to TSV file to append to.
    row_data : str
        Row data (tab-separated values) to append. Newline is added automatically.
    timeout : float
        Seconds to wait for lock before falling back to raw append.

    Raises
    ------
    IOError
        If the append operation fails (after acquiring lock or during fallback).
    """
    # Ensure parent directory exists
    parent = os.path.dirname(os.path.abspath(tsv_file))
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Derive lock file from target path (same dir, .lock suffix)
    lock_file = f"{tsv_file}.lock"
    os.makedirs(os.path.dirname(lock_file) or ".", exist_ok=True)

    # Acquire lock and append
    try:
        _do_locked_append(tsv_file, row_data, lock_file, timeout)
    except Exception as e:
        print(f"  [locked_append] ERROR: {e}", file=sys.stderr)
        raise


def _do_locked_append(tsv_file: str, row_data: str, lock_file: str, timeout: float) -> None:
    """Platform-specific locked append implementation."""
    if os.name == "nt":
        _nt_locked_append(tsv_file, row_data, lock_file, timeout)
    else:
        _posix_locked_append(tsv_file, row_data, lock_file, timeout)


def _posix_locked_append(tsv_file: str, row_data: str, lock_file: str, timeout: float) -> None:
    """POSIX locked append using fcntl.flock."""
    with open(lock_file, "a") as lock_fh:
        # Acquire exclusive lock (non-blocking with timeout loop)
        start_time = time.time()
        lock_acquired = False

        while time.time() - start_time < timeout:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
                break
            except (IOError, OSError):
                time.sleep(0.01)  # Back off and retry

        if not lock_acquired:
            # Timeout: fallback to raw append
            print(
                f"  [locked_append] WARNING: Lock timeout on {tsv_file} (timeout={timeout}s) — fallback to raw append",
                file=sys.stderr,
            )
            with open(tsv_file, "a") as f:
                f.write(f"{row_data}\n")
            return

        try:
            # Append with lock held
            with open(tsv_file, "a") as tsv_fh:
                tsv_fh.write(f"{row_data}\n")
        finally:
            # Release lock
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _nt_locked_append(tsv_file: str, row_data: str, lock_file: str, timeout: float) -> None:
    """Windows locked append using msvcrt.locking."""
    # Open TSV file in append + binary mode for locking
    start_time = time.time()
    lock_acquired = False
    lock_fh = None

    try:
        # Try to acquire lock via msvcrt.locking
        while time.time() - start_time < timeout:
            try:
                lock_fh = open(lock_file, "ab")
                # Lock the entire file (we only need byte 0)
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
                lock_acquired = True
                break
            except OSError:
                if lock_fh:
                    lock_fh.close()
                    lock_fh = None
                time.sleep(0.01)  # Back off and retry

        if not lock_acquired:
            # Timeout: fallback to raw append
            print(
                f"  [locked_append] WARNING: Lock timeout on {tsv_file} (timeout={timeout}s) — fallback to raw append",
                file=sys.stderr,
            )
            with open(tsv_file, "a") as f:
                f.write(f"{row_data}\n")
            return

        # Append with lock held
        with open(tsv_file, "a") as tsv_fh:
            tsv_fh.write(f"{row_data}\n")
    finally:
        # Release lock
        if lock_fh:
            try:
                msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
            except (OSError, ValueError):
                pass  # Already unlocked or file closed
            lock_fh.close()


def main() -> None:
    """Command-line entry point."""
    if len(sys.argv) < 3:
        print("Usage: locked_append_tsv.py <tsv_file> <row_data>", file=sys.stderr)
        sys.exit(1)

    tsv_file = sys.argv[1]
    row_data = sys.argv[2]

    try:
        locked_append_tsv(tsv_file, row_data)
        sys.exit(0)
    except Exception as e:
        print(f"  [locked_append] FATAL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
