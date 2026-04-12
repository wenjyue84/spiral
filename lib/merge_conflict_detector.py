#!/usr/bin/env python3
"""SPIRAL Phase M — Merge Conflict Detector (file-level, technicalNotes-based)

Parses 'File to edit:' lines from each story's technicalNotes to identify
file ownership claims, then finds collisions across stories.

Usage:
    python lib/merge_conflict_detector.py --stories '[...]' --out .spiral/_merge_conflicts.json

Functions:
    extract_story_files(story)      -> list[str]
    build_conflict_matrix(stories)  -> dict[str, list[str]]  (file -> [story_ids])
    write_conflict_report(matrix, path) -> None
    run(stories, out_path) -> int   (0 = no conflicts, 1 = conflicts found)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

# Pattern: "File to edit: path/to/file.py" anywhere in a technicalNotes string
_FILE_EDIT_RE = re.compile(r"File to edit:\s*(\S+)")


def extract_story_files(story: dict[str, Any]) -> list[str]:
    """Return list of file paths claimed by this story.

    Parses 'File to edit: <path>' tokens from every string in
    story['technicalNotes'] (list of strings).  Falls back to
    story['filesTouch'] when technicalNotes is absent.
    """
    notes: list[str] = story.get("technicalNotes", [])
    if notes:
        files: list[str] = []
        for note in notes:
            if isinstance(note, str):
                files.extend(_FILE_EDIT_RE.findall(note))
        return list(dict.fromkeys(files))  # deduplicate, preserve order

    # Fallback: filesTouch list (populated by earlier phases)
    return list(story.get("filesTouch", []))


def build_conflict_matrix(stories: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build a mapping of file path -> [story_ids that own it].

    Only entries with 2+ owners are conflicts, but the full matrix is returned
    so callers can filter as needed.
    """
    matrix: dict[str, list[str]] = {}
    for story in stories:
        sid = story.get("id", "UNKNOWN")
        for fpath in extract_story_files(story):
            matrix.setdefault(fpath, []).append(sid)
    return matrix


def write_conflict_report(
    matrix: dict[str, list[str]],
    path: str,
    *,
    _only_conflicts: bool = True,
) -> None:
    """Write a structured JSON conflict report to *path*.

    Report format (list of objects, one per story that has conflicts):
        [{"story_id": "US-456", "conflicting_story_ids": ["US-457"], "conflicting_files": ["lib/shared.py"]}, ...]

    If *_only_conflicts* is True (default) only stories with overlapping files
    are included.  An empty list is written when there are no conflicts.
    """
    # Invert matrix: story_id -> {conflicting_story_ids} per conflicting file
    conflict_files: dict[str, list[str]] = {fpath: owners for fpath, owners in matrix.items() if len(owners) >= 2}

    # Build per-story records
    story_records: dict[str, dict[str, Any]] = {}
    for fpath, owners in conflict_files.items():
        for sid in owners:
            others = [o for o in owners if o != sid]
            rec = story_records.setdefault(
                sid,
                {"story_id": sid, "conflicting_story_ids": [], "conflicting_files": []},
            )
            for other in others:
                if other not in rec["conflicting_story_ids"]:
                    rec["conflicting_story_ids"].append(other)
            if fpath not in rec["conflicting_files"]:
                rec["conflicting_files"].append(fpath)

    report = sorted(story_records.values(), key=lambda r: r["story_id"])

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


def run(
    stories: list[dict[str, Any]],
    out_path: str = ".spiral/_merge_conflicts.json",
) -> int:
    """Detect conflicts, write report, return 1 if any conflicts found else 0."""
    matrix = build_conflict_matrix(stories)
    write_conflict_report(matrix, out_path)

    with open(out_path, encoding="utf-8") as fh:
        report = json.load(fh)

    return 1 if report else 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Phase M file-level conflict detector")
    parser.add_argument("--stories", required=True, help="JSON array of story objects")
    parser.add_argument(
        "--out",
        default=".spiral/_merge_conflicts.json",
        help="Output path for conflict report",
    )
    args = parser.parse_args()

    stories = json.loads(args.stories)
    return run(stories, args.out)


if __name__ == "__main__":
    sys.exit(main())
