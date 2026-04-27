#!/usr/bin/env python3
"""batch_operations.py — Batch operations on multiple stories (mark-done, retrigger).

Supports operations:
  mark-done  — Mark stories as complete in prd.json with timestamp
  retrigger  — Reset retry counts and re-queue stories for Phase I
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def validate_story_id(story_id: str) -> bool:
    """Validate story ID format (US-NNN or UT-NNN)."""
    parts = story_id.strip().split("-")
    if len(parts) != 2:
        return False
    prefix, num = parts
    if prefix not in ("US", "UT"):
        return False
    try:
        int(num)
        return True
    except ValueError:
        return False


def parse_story_file(file_path: Path) -> list[str]:
    """Parse story file (one ID per line) into list of story IDs.

    Args:
        file_path: Path to file with story IDs

    Returns:
        List of validated story IDs

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file contains invalid story IDs
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    story_ids: list[str] = []
    invalid_lines: list[tuple[int, str]] = []

    with open(file_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not validate_story_id(line):
                invalid_lines.append((line_num, line))
            else:
                story_ids.append(line)

    if invalid_lines:
        errors = "\n".join(f"  Line {ln}: {sid}" for ln, sid in invalid_lines)
        raise ValueError(f"Invalid story IDs in file:\n{errors}")

    return story_ids


def execute_batch_operation(
    operation: str,
    story_ids: list[str],
    prd_path: Path,
) -> tuple[int, int, str]:
    """Execute batch operation on multiple stories.

    Args:
        operation: "mark-done" or "retrigger"
        story_ids: List of story IDs to operate on
        prd_path: Path to prd.json

    Returns:
        Tuple of (successful_count, skipped_count, summary_message)

    Raises:
        FileNotFoundError: If prd.json not found
        ValueError: If operation is invalid
    """
    if operation not in ("mark-done", "retrigger"):
        raise ValueError(f"Unknown operation: {operation}")

    if not prd_path.exists():
        raise FileNotFoundError(f"prd.json not found: {prd_path}")

    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    stories = prd.get("userStories", [])
    story_map = {s.get("id"): s for s in stories if isinstance(s, dict)}

    successful = 0
    skipped = 0
    timestamp = datetime.now(timezone.utc).isoformat()

    for story_id in story_ids:
        if story_id not in story_map:
            skipped += 1
            continue

        story = story_map[story_id]

        if operation == "mark-done":
            if story.get("passes") is True:
                skipped += 1
                continue
            story["passes"] = True
            story["completedAt"] = timestamp
            successful += 1

        elif operation == "retrigger":
            if story.get("passes") is True:
                skipped += 1
                continue
            story["passes"] = False
            story["retry_num"] = 0
            successful += 1

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2)

    summary = f"{successful} stories {operation.replace('-', ' ')}"
    if skipped > 0:
        summary += f", {skipped} skipped (not pending or already done)"

    return successful, skipped, summary


def run_batch(
    operation: str,
    stories_file: str,
    project_root: str,
) -> int:
    """CLI entry point for batch operations.

    Args:
        operation: "mark-done" or "retrigger"
        stories_file: Path to file with story IDs
        project_root: Root directory of SPIRAL project

    Returns:
        Exit code: 0 on success, 1 on error
    """
    try:
        file_path = Path(stories_file)
        story_ids = parse_story_file(file_path)

        if not story_ids:
            print("No valid story IDs found in file", file=sys.stderr)
            return 1

        prd_path = Path(project_root) / "prd.json"
        successful, skipped, summary = execute_batch_operation(
            operation,
            story_ids,
            prd_path,
        )

        print(summary)
        return 0

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            "Usage: batch_operations.py <operation> --stories-file <file> --project-root <root>",
            file=sys.stderr,
        )
        sys.exit(1)

    op = sys.argv[1]
    stories_file_arg = None
    project_root_arg = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--stories-file":
            stories_file_arg = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--project-root":
            project_root_arg = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    if not stories_file_arg or not project_root_arg:
        print(
            "Error: --stories-file and --project-root are required",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.exit(run_batch(op, stories_file_arg, project_root_arg))
