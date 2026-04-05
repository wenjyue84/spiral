#!/usr/bin/env python3
"""Handle patch rollback: reset stories and log event to spiral_events.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.core.spiral_io import atomic_write_json, locked_append_jsonl


def reset_stories_to_pending(prd_path: str, story_ids: list[str]) -> None:
    """Reset specified stories to passes=false in prd.json.

    Parameters
    ----------
    prd_path : str
        Path to prd.json
    story_ids : list[str]
        List of story IDs to reset (e.g. ['US-123', 'US-124'])
    """
    if not Path(prd_path).exists():
        print(f"ERROR: prd.json not found at {prd_path}", file=sys.stderr)
        sys.exit(1)

    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    story_ids_set = set(story_ids)
    found_count = 0

    for story in prd.get("userStories", []):
        if story.get("id") in story_ids_set:
            story["passes"] = False
            # Remove _passedCommit if it exists (story is no longer passed)
            story.pop("_passedCommit", None)
            found_count += 1

    if found_count < len(story_ids):
        missing = story_ids_set - {
            s.get("id") for s in prd.get("userStories", [])
        }
        print(
            f"WARNING: {len(missing)} story IDs not found in prd.json: {missing}",
            file=sys.stderr,
        )

    atomic_write_json(prd_path, prd)


def log_patch_rollback_event(
    events_path: str, story_ids: list[str], sha: str, reason: str
) -> None:
    """Log a patch_rollback event to spiral_events.jsonl.

    Parameters
    ----------
    events_path : str
        Path to spiral_events.jsonl
    story_ids : list[str]
        List of story IDs affected by rollback
    sha : str
        Git SHA that was reverted to
    reason : str
        Reason for rollback (e.g. "git apply failed" or "merge conflict")
    """
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event": "patch_rollback",
        "story_ids": story_ids,
        "sha": sha,
        "reason": reason,
    }
    locked_append_jsonl(events_path, event)


def main() -> int:
    """Parse args and execute rollback logic."""
    parser = argparse.ArgumentParser(
        description="Reset rolled-back stories and log patch_rollback event"
    )
    parser.add_argument(
        "--prd",
        required=True,
        help="Path to prd.json",
    )
    parser.add_argument(
        "--events",
        required=True,
        help="Path to spiral_events.jsonl",
    )
    parser.add_argument(
        "--story-ids",
        nargs="+",
        required=True,
        help="Space-separated list of story IDs to reset",
    )
    parser.add_argument(
        "--sha",
        required=True,
        help="Git SHA reverted to",
    )
    parser.add_argument(
        "--reason",
        default="patch application failed",
        help="Reason for rollback",
    )

    args = parser.parse_args()

    try:
        reset_stories_to_pending(args.prd, args.story_ids)
        log_patch_rollback_event(args.events, args.story_ids, args.sha, args.reason)
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: patch rollback failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
