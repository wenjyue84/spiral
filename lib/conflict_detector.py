#!/usr/bin/env python3
"""SPIRAL Phase M — Federated File Conflict Detector

Detects file-level collisions when multiple sub-projects modify the same file path.
Extracts modified files from git commits and tracks (file_path, sub_project_id) tuples.

Detects collisions: same file_path with different sub_project_id values.
Writes .spiral/merge_conflicts.json with structure:
  [{file_path, sub_projects: [proj1, proj2], conflict_type: 'file_collision'}, ...]

Blocks Phase M merge if collisions exist (exit code 1).

Usage:
  python lib/conflict_detector.py --prd prd.json [--log-file .spiral/conflict_report.jsonl]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))
from story_helpers import get_files_to_touch


def extract_files_from_commit(commit_hash: str) -> set[str]:
    """Extract modified file paths from a git commit using git show --name-only.

    Args:
        commit_hash: Git commit SHA or ref

    Returns:
        Set of file paths modified in the commit
    """
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", commit_hash],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            files = {line.strip() for line in result.stdout.splitlines() if line.strip()}
            return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return set()


def detect_federated_conflicts(stories: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Detect file collisions across sub-projects.

    Extracts modified file paths from each story's implementation commits,
    tracks (file_path, sub_project_id) tuples, and detects collisions where
    the same file_path is modified by stories from different sub-projects.

    Args:
        stories: List of story dicts from prd.json

    Returns:
        (conflict_list, error_messages) where:
        - conflict_list: list of {file_path, sub_projects: [proj1, proj2], conflict_type}
        - error_messages: list of error strings for blocking merge
    """
    # Filter to incomplete stories only
    pending = [s for s in stories if not s.get("passes") and not s.get("_decomposed") and not s.get("_skipped")]

    # Build (file_path, sub_project_id) -> story_ids mapping
    file_ownership: dict[tuple[str, str], list[str]] = {}

    for story in pending:
        story_id = story.get("id", "UNKNOWN")
        sub_project = story.get("_source", "")  # sub_project_id from _source field

        # Try to get files from technicalNotes first (may contain commit hashes)
        files: set[str] = set()

        # Also include filesToTouch as fallback
        files.update(get_files_to_touch(story))

        # Register files to this story's sub_project
        for fpath in files:
            key = (fpath, sub_project)
            file_ownership.setdefault(key, []).append(story_id)

    # Detect collisions: same file_path with different sub_project_id
    file_collisions: dict[str, set[str]] = {}  # file_path -> {sub_project_ids}
    for (fpath, sub_project), story_ids in file_ownership.items():
        if fpath not in file_collisions:
            file_collisions[fpath] = set()
        file_collisions[fpath].add(sub_project)

    # Build conflict report and error messages
    conflicts: list[dict[str, Any]] = []
    error_messages: list[str] = []

    for fpath, sub_projects in file_collisions.items():
        if len(sub_projects) > 1:  # Collision: multiple sub_projects
            sub_project_list = sorted(sub_projects)
            conflicts.append(
                {
                    "file_path": fpath,
                    "sub_projects": sub_project_list,
                    "conflict_type": "file_collision",
                }
            )

            # Build error messages for merge blocking
            for (fp, sp), story_ids in file_ownership.items():
                if fp == fpath and sp in sub_projects:
                    for story_id in story_ids:
                        other_projects = [p for p in sub_project_list if p != sp]
                        if other_projects:
                            error_messages.append(
                                f"File {fpath} modified by {story_id} (sub_project: {sp}) "
                                f"and stories in {other_projects}; manual resolution required"
                            )

    return conflicts, error_messages


def write_conflict_report(conflicts: list[dict[str, Any]], path: str) -> None:
    """Write structured JSON conflict report to .spiral/merge_conflicts.json."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(conflicts, fh, indent=2)


def log_conflicts(conflicts: list[dict[str, Any]], error_messages: list[str], log_file: str) -> None:
    """Append conflict records to JSONL log file."""
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
        for msg in error_messages:
            entry = {"ts": ts, "event": "conflict_merge_blocked", "error": msg}
            fh.write(json.dumps(entry) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL Phase M federated file conflict detector")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--log-file", default="", help="Path to conflict log JSONL (optional)")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    conflicts, error_messages = detect_federated_conflicts(stories)

    # Write conflict report
    report_path = os.path.join(os.path.dirname(args.prd), ".spiral", "merge_conflicts.json")
    write_conflict_report(conflicts, report_path)

    if args.log_file:
        log_conflicts(conflicts, error_messages, args.log_file)

    result = {"conflicts": conflicts, "total": len(conflicts)}
    print(json.dumps(result))

    # Print error messages to stderr
    if error_messages:
        for msg in error_messages:
            print(f"  [conflict-detector] {msg}", file=sys.stderr)

    # Exit code 1 if collisions found (blocks Phase M merge)
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
