"""Unified I/O utilities for SPIRAL -- stdlib-only, no circular dependency risk."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any


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
