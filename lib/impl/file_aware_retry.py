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


def store_failed_files(results_tsv_path: str, story_id: str, failed_files_json: str) -> bool:
    """
    Update the last row for story_id in results.tsv, setting failed_files column.

    If the column doesn't exist, appends it to the header.
    Returns True if a row was found and updated, False otherwise.
    """
    try:
        with open(results_tsv_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        if not lines:
            return False

        header_parts = lines[0].rstrip("\n\r").split("\t")

        # Find or add failed_files column
        if "failed_files" not in header_parts:
            header_parts.append("failed_files")
            lines[0] = "\t".join(header_parts) + "\n"

        failed_idx = header_parts.index("failed_files")

        story_id_idx = -1
        for i, h in enumerate(header_parts):
            if h == "story_id":
                story_id_idx = i
                break

        if story_id_idx == -1:
            return False

        # Find last row matching story_id
        last_row_idx = -1
        for i in range(1, len(lines)):
            row = lines[i].rstrip("\n\r").split("\t")
            if len(row) > story_id_idx and row[story_id_idx] == story_id:
                last_row_idx = i

        if last_row_idx == -1:
            return False

        row = lines[last_row_idx].rstrip("\n\r").split("\t")
        while len(row) <= failed_idx:
            row.append("")
        row[failed_idx] = failed_files_json
        lines[last_row_idx] = "\t".join(row) + "\n"

        with open(results_tsv_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return True

    except (OSError, ValueError, IndexError):
        return False


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: file_aware_retry.py extract <stderr_file>", file=sys.stderr)
        print("       file_aware_retry.py get <results_tsv> <story_id>", file=sys.stderr)
        print("       file_aware_retry.py store <results_tsv> <story_id> <json>", file=sys.stderr)
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

    elif cmd == "store":
        if len(sys.argv) < 5:
            return
        ok = store_failed_files(sys.argv[2], sys.argv[3], sys.argv[4])
        sys.exit(0 if ok else 1)

    else:
        print("[]")


if __name__ == "__main__":
    main()
