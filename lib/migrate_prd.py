#!/usr/bin/env python3
"""
SPIRAL — PRD Migration Tool
Upgrades prd.json from any prior version to the current schema version.

Migrations are idempotent: running multiple times produces the same result.

Exit codes:
  0 = migration applied (or already current)
  1 = file/JSON error
  2 = prd.json is on a future schema version (incompatible)

Usage:
  python lib/migrate_prd.py prd.json              # migrate in place
  python lib/migrate_prd.py prd.json --dry-run     # show what would change
  python lib/migrate_prd.py prd.json --check       # exit 0 if current, 2 if needs migration
"""
import json
import os
import sys

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Must match prd_schema.CURRENT_SCHEMA_VERSION
CURRENT_SCHEMA_VERSION = 1


def migrate_prd(prd: dict) -> tuple[dict, list[str]]:
    """
    Migrate a prd dict to the current schema version.

    Returns (migrated_prd, changes_list) where changes_list describes
    what was modified. Empty changes_list means no migration was needed.
    """
    changes: list[str] = []

    if not isinstance(prd, dict):
        return prd, changes

    current = prd.get("schemaVersion")

    # Already at current version — nothing to do
    if current == CURRENT_SCHEMA_VERSION:
        return prd, changes

    # Future version — caller should abort
    if isinstance(current, int) and current > CURRENT_SCHEMA_VERSION:
        return prd, changes  # caller checks version separately

    # ── Migration: unversioned → version 1 ────────────────────────────────
    # (also handles schemaVersion=0 or non-integer schemaVersion)

    # Add schemaVersion
    if "schemaVersion" not in prd or prd.get("schemaVersion") != CURRENT_SCHEMA_VERSION:
        prd["schemaVersion"] = CURRENT_SCHEMA_VERSION
        changes.append(f"Set schemaVersion to {CURRENT_SCHEMA_VERSION}")

    # Ensure every story has dependencies:[]
    stories = prd.get("userStories", [])
    if isinstance(stories, list):
        for i, story in enumerate(stories):
            if isinstance(story, dict) and "dependencies" not in story:
                story["dependencies"] = []
                sid = story.get("id", f"index {i}")
                changes.append(f"Added missing dependencies:[] to {sid}")

    return prd, changes


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Migrate prd.json to current schema version")
    parser.add_argument("prd", help="Path to prd.json")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--check", action="store_true", help="Check if migration needed (exit 0=current, 2=needs migration)")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[migrate] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[migrate] ERROR: Invalid JSON in {args.prd}: {e}", file=sys.stderr)
        return 1

    if not isinstance(prd, dict):
        print(f"[migrate] ERROR: prd.json root must be an object", file=sys.stderr)
        return 1

    # Check for incompatible future version
    current_version = prd.get("schemaVersion")
    if isinstance(current_version, int) and current_version > CURRENT_SCHEMA_VERSION:
        print(
            f"[migrate] ERROR: prd.json schemaVersion {current_version} is newer than "
            f"this SPIRAL version supports (max: {CURRENT_SCHEMA_VERSION}). "
            f"Please update SPIRAL.",
            file=sys.stderr,
        )
        return 2

    if args.check:
        if current_version == CURRENT_SCHEMA_VERSION:
            print(f"[migrate] {args.prd} is at current schema version {CURRENT_SCHEMA_VERSION}")
            return 0
        else:
            print(f"[migrate] {args.prd} needs migration (current: {current_version}, target: {CURRENT_SCHEMA_VERSION})")
            return 2

    migrated, changes = migrate_prd(prd)

    if not changes:
        print(f"[migrate] {args.prd} already at schema version {CURRENT_SCHEMA_VERSION} — no changes needed")
        return 0

    if args.dry_run:
        print(f"[migrate] {args.prd} — {len(changes)} change(s) (dry run):")
        for c in changes:
            print(f"  - {c}")
        return 0

    # Write migrated prd.json
    with open(args.prd, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)
        f.write("\n")  # trailing newline

    print(f"[migrate] {args.prd} — migrated ({len(changes)} change(s)):")
    for c in changes:
        print(f"  - {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
