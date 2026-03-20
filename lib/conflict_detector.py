#!/usr/bin/env python3
"""SPIRAL Phase M — Detect and Report Story File Conflicts

Compares filesToTouch across stories in prd.json to find pairs that modify
overlapping files.  Returns conflict records with pipe-separated file paths.

Usage:
  python lib/conflict_detector.py --prd prd.json [--log-file .spiral/conflict_report.jsonl]

Output JSON:
  {"conflicts": [{"storyA": "US-501", "storyB": "US-502", "conflict_files": "src/auth.ts"}], "total": 1}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from story_helpers import get_files_to_touch


def detect_conflicts(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find all pairs of incomplete stories that share filesToTouch entries.

    Returns a list of conflict records:
        {"storyA": str, "storyB": str, "conflict_files": str}
    where conflict_files is a pipe-separated string of overlapping paths.
    """
    # Filter to incomplete stories only (stories still to be implemented)
    pending = [s for s in stories if not s.get("passes") and not s.get("_decomposed") and not s.get("_skipped")]

    conflicts: list[dict[str, Any]] = []
    for i in range(len(pending)):
        files_a = get_files_to_touch(pending[i])
        if not files_a:
            continue
        for j in range(i + 1, len(pending)):
            files_b = get_files_to_touch(pending[j])
            if not files_b:
                continue
            overlap = files_a & files_b
            if overlap:
                conflicts.append(
                    {
                        "storyA": pending[i]["id"],
                        "storyB": pending[j]["id"],
                        "conflict_files": "|".join(sorted(overlap)),
                    }
                )
    return conflicts


def log_conflicts(conflicts: list[dict[str, Any]], log_file: str) -> None:
    """Append conflict records to a JSONL log file."""
    if not conflicts:
        return
    log_dir = os.path.dirname(os.path.abspath(log_file))
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with open(log_file, "a", encoding="utf-8") as fh:
        for c in conflicts:
            entry = {"ts": ts, "event": "file_conflict_detected", **c}
            fh.write(json.dumps(entry) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL Phase M file conflict detector")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--log-file", default="", help="Path to conflict log JSONL (optional)")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    conflicts = detect_conflicts(stories)

    if args.log_file and conflicts:
        log_conflicts(conflicts, args.log_file)

    result = {"conflicts": conflicts, "total": len(conflicts)}
    print(json.dumps(result))

    if conflicts:
        for c in conflicts:
            print(
                f"  [conflict-detector] {c['storyA']} ↔ {c['storyB']}: {c['conflict_files']}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
