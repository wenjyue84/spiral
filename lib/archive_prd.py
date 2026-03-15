#!/usr/bin/env python3
"""
archive_prd.py — Move completed stories from prd.json to prd-archive.json.

Archivable: passes=true AND _decomposed != true
Kept:       passes=false, _decomposed=true (parent integrity for _decomposedFrom refs)

Usage:
  python lib/archive_prd.py [--prd prd.json] [--archive prd-archive.json] [--dry-run]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json


def is_archivable(story):
    """True if story should be moved to the archive."""
    return story.get("passes") is True and not story.get("_decomposed", False)


def main():
    parser = argparse.ArgumentParser(description="Archive completed stories from prd.json")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json (default: prd.json)")
    parser.add_argument(
        "--archive",
        default="prd-archive.json",
        help="Path to archive file (default: prd-archive.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be archived without writing files",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[archive_prd] ERROR: {args.prd} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.prd, "r", encoding="utf-8") as f:
        prd = json.load(f)
    stories = prd.get("userStories", [])
    to_archive = [s for s in stories if is_archivable(s)]
    to_keep = [s for s in stories if not is_archivable(s)]

    if not to_archive:
        print(
            f"[archive_prd] Nothing to archive — all {len(stories)} stories are pending or decomposed parents."
        )
        sys.exit(0)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(
        f"[archive_prd] {prefix}Archiving {len(to_archive)} stories -> {args.archive}"
        f" ({len(to_keep)} remaining in {args.prd})"
    )

    if args.dry_run:
        for s in to_archive:
            sid = s.get("id", "?")
            title = s.get("title", "")[:60]
            print(f"  would archive: {sid}  {title}")
        sys.exit(0)

    # Load existing archive (append mode — never overwrites history)
    if os.path.isfile(args.archive):
        with open(args.archive, "r", encoding="utf-8") as f:
            existing = json.load(f)
        existing_entries = existing.get("archivedStories", [])
    else:
        existing_entries = []

    archive_data = {
        "productName": prd.get("productName", ""),
        "archivedStories": existing_entries + to_archive,
    }
    atomic_write_json(args.archive, archive_data)

    slim_prd = {k: v for k, v in prd.items() if k != "userStories"}
    slim_prd["userStories"] = to_keep
    atomic_write_json(args.prd, slim_prd)

    print(f"[archive_prd] Done. {args.prd} now has {len(to_keep)} stories.")


if __name__ == "__main__":
    main()
