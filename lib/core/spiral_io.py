"""Unified I/O utilities for SPIRAL -- stdlib-only, no circular dependency risk."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import fcntl
    import msvcrt


def atomic_write_json(path: str, data: Any, *, backup: bool = False) -> None:
    """Write *data* as pretty-printed JSON to *path* atomically.

    Uses ``tempfile.mkstemp`` in the same directory to avoid cross-device
    rename issues and name collisions.  The temporary file is always
    cleaned up on failure.

    Parameters
    ----------
    path : str
        Destination file path.
    data : Any
        JSON-serializable data.
    backup : bool
        If True, copy existing *path* to ``path + '.bak'`` before overwriting.
    """
    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)

    if backup and os.path.isfile(path):
        import shutil

        shutil.copy2(path, path + ".bak")

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


def append_jsonl(path: str, record: Any) -> None:
    """Append a single JSON record to a JSONL file.

    Creates parent directories if needed.  Writes
    ``json.dumps(record) + "\\n"`` in a single ``write()`` call for atomicity.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def locked_append_jsonl(filepath: str, record: Any, *, timeout: float = 5.0) -> None:
    """Append *record* to a JSONL file with exclusive file locking.

    Uses ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows to prevent
    corruption when multiple processes append concurrently (e.g. parallel workers
    writing to spiral_events.jsonl).

    Falls back to an unlocked raw append if the lock cannot be acquired within
    *timeout* seconds, so writes are never silently dropped.

    Parameters
    ----------
    filepath : str
        Destination JSONL file path.
    record : Any
        JSON-serializable record to append.
    timeout : float
        Seconds to wait for exclusive lock before falling back to raw append.
    """
    parent = os.path.dirname(os.path.abspath(filepath))
    if parent:
        os.makedirs(parent, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        if os.name == "nt":
            _nt_locked_write(filepath, line, timeout)
        else:
            _posix_locked_write(filepath, line, timeout)
    except Exception:  # noqa: BLE001 — last-resort fallback, never drop a write
        with open(filepath, "a", encoding="utf-8") as _fh:
            _fh.write(line)


def _posix_locked_write(filepath: str, line: str, timeout: float) -> None:
    """fcntl.flock-based exclusive append for POSIX systems."""
    import fcntl  # noqa: PLC0415

    deadline = time.monotonic() + timeout
    with open(filepath, "a", encoding="utf-8") as fh:
        lock_acquired = False
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break  # timeout — write without lock (fallback per AC4)
                time.sleep(0.05)
        try:
            fh.write(line)
        finally:
            if lock_acquired:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def _nt_locked_write(filepath: str, line: str, timeout: float) -> None:
    """msvcrt.locking-based exclusive append for Windows."""
    import msvcrt  # noqa: PLC0415

    deadline = time.monotonic() + timeout
    # Open with low-level fd so msvcrt.locking can address byte ranges.
    # O_APPEND ensures all writes land at end-of-file atomically.
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(filepath, flags, 0o666)
    lock_acquired = False
    try:
        # Lock 1 byte at position 0 as a mutual-exclusion sentinel.
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                lock_acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break  # timeout — write without lock (fallback per AC4)
                time.sleep(0.05)
        os.write(fd, line.encode("utf-8"))
    finally:
        if lock_acquired:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(fd)


def safe_read_json(path: str, default: Any = None) -> Any:
    """Read and parse a JSON file, returning *default* on missing or corrupt."""
    if not os.path.isfile(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


def safe_read_jsonl(path: str) -> list[Any]:
    """Read a JSONL file, skipping corrupt lines with a warning to stderr."""
    records: list[Any] = []
    if not os.path.isfile(path):
        return records
    try:
        with open(path, encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    print(
                        f"[spiral_io] WARNING: corrupt JSONL line {line_num} in {path}",
                        file=sys.stderr,
                    )
    except OSError as e:
        print(f"[spiral_io] WARNING: failed to read {path}: {e}", file=sys.stderr)
    return records


def configure_utf8_stdout() -> None:
    """Reconfigure stdout and stderr for UTF-8 on Windows (cp1252 workaround)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    # CLI used by shell wrappers: python spiral_io.py --append <filepath> <json-line>
    import argparse

    _parser = argparse.ArgumentParser(description="spiral_io CLI")
    _parser.add_argument("--append", metavar="FILEPATH", help="Locked-append JSON line to JSONL")
    _parser.add_argument("json_line", nargs="?", help="JSON string to append")
    _args = _parser.parse_args()
    if _args.append and _args.json_line:
        try:
            _record = json.loads(_args.json_line)
            locked_append_jsonl(_args.append, _record)
        except (json.JSONDecodeError, OSError) as _e:
            print(f"[spiral_io] error: {_e}", file=sys.stderr)
            sys.exit(1)
    else:
        _parser.print_help(sys.stderr)
        sys.exit(1)
