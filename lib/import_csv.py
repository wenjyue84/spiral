#!/usr/bin/env python3
"""
SPIRAL — import_csv.py
Bulk-import user stories from a CSV spreadsheet into prd.json.

Supported columns (header row required):
    title                  — story title (required)
    description            — story description
    priority               — critical|high|medium|low  (required)
    estimatedComplexity    — trivial|small|medium|large|xlarge
    acceptanceCriteria     — semicolon-separated list
    technicalNotes         — semicolon-separated list

Usage (library):
    from import_csv import import_csv_stories
    added, skipped, errors = import_csv_stories(
        csv_path="stories.csv",
        prd_path="prd.json",
        delimiter=",",
        dry_run=False,
    )

Usage (CLI):
    python lib/import_csv.py stories.csv [--prd prd.json] [--delimiter ,] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

# Valid SPIRAL priority values.
_VALID_PRIORITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low"})

# Valid complexity values.
_VALID_COMPLEXITIES: frozenset[str] = frozenset(
    {"trivial", "small", "medium", "large", "xlarge"}
)

# Story ID prefix respects the same env var as merge_stories.py.
_STORY_PREFIX: str = os.environ.get("SPIRAL_STORY_PREFIX", "US")


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _load_prd(prd_path: str) -> dict[str, Any]:
    path = Path(prd_path)
    if not path.exists():
        raise FileNotFoundError(f"prd.json not found at {prd_path!r}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _next_story_id(existing_stories: list[dict[str, Any]]) -> str:
    """Return the next available US-NNN id not already in *existing_stories*."""
    prefix = re.escape(_STORY_PREFIX)
    pattern = re.compile(rf"^{prefix}-(\d+)$")
    max_num = 0
    for story in existing_stories:
        m = pattern.match(story.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"{_STORY_PREFIX}-{max_num + 1}"


def _split_list_field(value: str) -> list[str]:
    """Split a semicolon-delimited field into a list of non-empty strings."""
    return [item.strip() for item in value.split(";") if item.strip()]


# ── CSV parsing ───────────────────────────────────────────────────────────────


def parse_csv_rows(
    csv_path: str,
    delimiter: str = ",",
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Parse *csv_path* and return (rows, parse_errors).

    Each valid row becomes a raw dict with normalised keys.
    *parse_errors* contains human-readable messages for invalid rows
    (1-indexed row numbers, counting from the header = row 1).
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path!r}")

    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        # DictReader row index starts at 2 (row 1 = header).
        for row_num, raw in enumerate(reader, start=2):
            # Normalise keys: strip whitespace and lowercase.
            row = {k.strip(): (v.strip() if v else "") for k, v in raw.items()}

            title = row.get("title", "").strip()
            priority = row.get("priority", "").strip().lower()

            row_errors: list[str] = []
            if not title:
                row_errors.append("missing title")
            if not priority:
                row_errors.append("missing priority")
            elif priority not in _VALID_PRIORITIES:
                row_errors.append(
                    f"invalid priority {priority!r} (must be one of: "
                    f"{', '.join(sorted(_VALID_PRIORITIES))})"
                )

            if row_errors:
                errors.append(
                    f"Row {row_num}: {'; '.join(row_errors)} — skipped"
                )
                continue

            complexity = row.get("estimatedComplexity", "").strip().lower()
            if complexity and complexity not in _VALID_COMPLEXITIES:
                complexity = "medium"

            rows.append(
                {
                    "title": title,
                    "priority": priority,
                    "description": row.get("description", "").strip(),
                    "estimatedComplexity": complexity or "medium",
                    "acceptanceCriteria": _split_list_field(
                        row.get("acceptanceCriteria", "")
                    ),
                    "technicalNotes": _split_list_field(
                        row.get("technicalNotes", "")
                    ),
                }
            )

    return rows, errors


# ── Public API ────────────────────────────────────────────────────────────────


def import_csv_stories(
    *,
    csv_path: str,
    prd_path: str = "prd.json",
    delimiter: str = ",",
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """
    Parse *csv_path* and append new stories to *prd_path*.

    Returns
    -------
    (added_stories, skipped_titles, parse_errors)
        added_stories  — story dicts that were (or would be) added
        skipped_titles — titles skipped because they already exist
        parse_errors   — human-readable messages for invalid rows
    """
    rows, parse_errors = parse_csv_rows(csv_path, delimiter=delimiter)

    prd_data = _load_prd(prd_path)
    existing_stories: list[dict[str, Any]] = prd_data.get("userStories", [])
    existing_titles: set[str] = {
        (s.get("title") or "").strip() for s in existing_stories
    }

    added: list[dict[str, Any]] = []
    skipped: list[str] = []

    for row in rows:
        title = row["title"]
        if title in existing_titles:
            skipped.append(title)
            continue

        next_id = _next_story_id(existing_stories + added)
        story: dict[str, Any] = {
            "id": next_id,
            "title": title,
            "priority": row["priority"],
            "description": row["description"],
            "estimatedComplexity": row["estimatedComplexity"],
            "acceptanceCriteria": row["acceptanceCriteria"],
            "technicalNotes": row["technicalNotes"],
            "dependencies": [],
            "passes": False,
            "_source": "csv-import",
        }
        added.append(story)
        existing_titles.add(title)

    if not dry_run and added:
        prd_data["userStories"] = existing_stories + added
        atomic_write_json(prd_path, prd_data)

    return added, skipped, parse_errors


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiral import-csv",
        description="Bulk-import stories from a CSV file into prd.json.",
    )
    parser.add_argument(
        "csv_file",
        metavar="CSV_FILE",
        help="Path to the CSV file containing stories",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="PATH",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        metavar="CHAR",
        help="CSV field delimiter (default: comma).  Use '\\t' for TSV files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print stories that would be added without modifying prd.json",
    )

    args = parser.parse_args(argv)

    # Resolve escape sequences so users can pass --delimiter '\t'.
    delimiter = args.delimiter.encode("raw_unicode_escape").decode("unicode_escape")

    try:
        added, skipped, errors = import_csv_stories(
            csv_path=args.csv_file,
            prd_path=args.prd,
            delimiter=delimiter,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for msg in errors:
        print(f"[warn] {msg}")

    for title in skipped:
        print(f"[skip] Duplicate: {title!r}")

    if args.dry_run:
        if added:
            print(f"\n[dry-run] Would add {len(added)} story/stories:")
            for story in added:
                print(
                    f"  {story['id']} ({story['priority']}) — {story['title']}"
                )
        else:
            print("[dry-run] No new stories to add.")
        return 0

    if added:
        print(f"Added {len(added)} story/stories to prd.json:")
        for story in added:
            print(f"  {story['id']} ({story['priority']}) — {story['title']}")
    else:
        print("No new stories to add.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
