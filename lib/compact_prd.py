#!/usr/bin/env python3
"""
SPIRAL — compact_prd.py
Strips transient runtime fields from completed/skipped stories in prd.json.

Transient fields accumulate during spiral runs (_lastAttempt, _workerPid, etc.)
and inflate the PRD file size without adding value for human readers or future runs.

Usage (library):
    from compact_prd import compact_prd
    result = compact_prd("prd.json", backup_dir=".spiral")

Usage (CLI):
    python lib/compact_prd.py [--prd prd.json] [--backup-dir .spiral] [--dry-run]
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json

# Fields that are purely runtime state and safe to strip from completed/skipped stories.
TRANSIENT_FIELDS: frozenset[str] = frozenset(
    [
        "_lastAttempt",
        "_workerPid",
        "_researchOutput",
        "_routerScore",
        "_lastResearchAttempt",
    ]
)

# Required schema fields that must never be removed.
REQUIRED_FIELDS: frozenset[str] = frozenset(["id", "title"])

# Statuses whose stories are eligible for compaction.
COMPACTABLE_STATUSES: frozenset[str] = frozenset(["passed", "skipped"])



def _story_is_compactable(story: dict[str, Any]) -> bool:
    """Return True if a story's transient fields should be stripped."""
    status = story.get("status", "")
    passes = story.get("passes", False)
    # Eligible if status is passed/skipped, OR if passes=True (legacy format)
    return status in COMPACTABLE_STATUSES or passes is True


def compact_prd(
    prd_path: str,
    backup_dir: str = ".spiral",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Strip transient fields from completed/skipped stories in prd.json.

    Args:
        prd_path: Path to prd.json.
        backup_dir: Directory to write the pre-compact backup.
        dry_run: If True, compute changes but do not write anything.

    Returns:
        Dict with keys: stories_compacted (int), fields_removed (int),
        bytes_saved (int), backup_path (str | None).
    """
    prd_path = str(prd_path)

    with open(prd_path, encoding="utf-8") as fh:
        prd = json.load(fh)

    stories: list[dict[str, Any]] = prd.get("userStories", [])
    original_size = os.path.getsize(prd_path)

    stories_compacted = 0
    fields_removed = 0

    for story in stories:
        if not _story_is_compactable(story):
            continue
        removed = [f for f in TRANSIENT_FIELDS if f in story]
        if not removed:
            continue
        # Safety guard — never strip required fields (defensive check)
        for f in REQUIRED_FIELDS:
            if f in removed:
                removed.remove(f)
        if not removed:
            continue
        for f in removed:
            del story[f]
        fields_removed += len(removed)
        stories_compacted += 1

    if dry_run:
        return {
            "stories_compacted": stories_compacted,
            "fields_removed": fields_removed,
            "bytes_saved": 0,
            "backup_path": None,
        }

    if fields_removed == 0:
        return {
            "stories_compacted": 0,
            "fields_removed": 0,
            "bytes_saved": 0,
            "backup_path": None,
        }

    # Backup original before modifying
    backup_path: str | None = None
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = int(time.time())
    backup_path = os.path.join(backup_dir, f"prd_pre_compact_{timestamp}.json")
    shutil.copy2(prd_path, backup_path)

    atomic_write_json(prd_path, prd)

    new_size = os.path.getsize(prd_path)
    bytes_saved = original_size - new_size

    return {
        "stories_compacted": stories_compacted,
        "fields_removed": fields_removed,
        "bytes_saved": bytes_saved,
        "backup_path": backup_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip transient runtime fields from completed/skipped stories in prd.json"
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--backup-dir",
        default=".spiral",
        help="Directory for pre-compact backup (default: .spiral)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without writing changes",
    )
    args = parser.parse_args()

    if not os.path.exists(args.prd):
        print(f"Error: {args.prd} not found", file=sys.stderr)
        sys.exit(1)

    result = compact_prd(args.prd, backup_dir=args.backup_dir, dry_run=args.dry_run)

    n = result["stories_compacted"]
    m = result["fields_removed"]
    saved = result["bytes_saved"]
    backup = result["backup_path"]

    if args.dry_run:
        print(f"[dry-run] Would compact {n} stories, remove {m} fields")
        return

    if m == 0:
        print("Nothing to compact — no transient fields found in eligible stories.")
        return

    kb_saved = saved / 1024
    print(f"Compacted {n} stories, removed {m} fields, saved {kb_saved:.1f} KB")
    if backup:
        print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
