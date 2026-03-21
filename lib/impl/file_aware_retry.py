#!/usr/bin/env python3
"""
file_aware_retry.py — US-597: File-aware retry helper for Phase I.

Provides two commands:

  extract <stderr_file>
      Parse a Ralph stderr capture for file-path failure signals.
      Outputs a JSON array of unique file paths, e.g. '["src/a.py","lib/b.py"]'.

  get <results_tsv> <story_id>
      Read the failed_files column from the last failed row for story_id
      in results.tsv. Outputs a JSON array string.

Both commands print [] on error so callers can safely use the output.

Usage (from retry.sh):
    python lib/impl/file_aware_retry.py extract /tmp/ralph_stderr_XXX.txt
    python lib/impl/file_aware_retry.py get results.tsv US-597
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

# ── Regex patterns for extracting failed file paths from stderr ──────────────

_FILE_PATTERNS = [
    # mypy: lib/foo.py:12: error: ...
    re.compile(r"^([a-zA-Z0-9_./-]+\.(?:py|ts|js|sh))\s*:\s*\d+", re.MULTILINE),
    # pytest FAILED tests/test_foo.py::test_bar
    re.compile(r"FAILED\s+([a-zA-Z0-9_./-]+\.(?:py|ts|js|sh))", re.MULTILINE),
    # Error in file: src/main.py
    re.compile(r"(?:Error|error)\s+(?:in\s+file|processing|in)\s*:?\s*([a-zA-Z0-9_./-]+\.(?:py|ts|js|sh))", re.MULTILINE),
    # TypeScript: error TS2345: ... lib/foo.ts
    re.compile(r"error\s+TS\d+:.*?([a-zA-Z0-9_./-]+\.(?:ts|js))", re.MULTILINE),
    # shellcheck: In lib/foo.sh line 42:
    re.compile(r"In\s+([a-zA-Z0-9_./-]+\.sh)\s+line", re.MULTILINE),
]


def extract_failed_files(stderr_path: str) -> list[str]:
    """Parse stderr file for failed file paths. Returns deduplicated list."""
    try:
        text = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    found: list[str] = []
    for pattern in _FILE_PATTERNS:
        for match in pattern.finditer(text):
            path = match.group(1).strip()
            # Filter out noise: must look like a real source file path
            if "/" in path or path.endswith((".py", ".ts", ".js", ".sh")):
                found.append(path)

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def get_failed_files_for_story(results_tsv_path: str, story_id: str) -> list[str]:
    """
    Read failed_files from the last failed row for story_id in results.tsv.

    Returns a list of file path strings, or [] if none found.
    """
    try:
        with open(results_tsv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None or "failed_files" not in reader.fieldnames:
                return []

            last_failed: str = ""
            for row in reader:
                if row.get("story_id") == story_id and row.get("status") in ("failed", "timeout"):
                    last_failed = row.get("failed_files", "")

    except OSError:
        return []

    if not last_failed or last_failed.strip() in ("", "[]"):
        return []

    try:
        parsed = json.loads(last_failed)
        if isinstance(parsed, list):
            return [str(p) for p in parsed if p]
    except json.JSONDecodeError:
        pass
    return []


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: file_aware_retry.py extract <stderr_file>", file=sys.stderr)
        print("       file_aware_retry.py get <results_tsv> <story_id>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "extract":
        if len(sys.argv) < 3:
            print("[]")
            return
        files = extract_failed_files(sys.argv[2])
        print(json.dumps(files))

    elif cmd == "get":
        if len(sys.argv) < 4:
            print("[]")
            return
        files = get_failed_files_for_story(sys.argv[2], sys.argv[3])
        print(json.dumps(files))

    else:
        print("[]")


if __name__ == "__main__":
    main()
