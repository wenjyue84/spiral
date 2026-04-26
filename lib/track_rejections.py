#!/usr/bin/env python3
"""lib/track_rejections.py — Track story rejections in prd.json and .spiral/rejections.jsonl.

After Phase S validation, reads .spiral/_story_rejected.json and:
  1. Updates prd.json to add _rejectionLog entries to rejected stories
  2. Writes to .spiral/rejections.jsonl for telemetry

Usage:
  python lib/track_rejections.py --prd prd.json --rejected .spiral/_story_rejected.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _normalize_reason(reason: str) -> str:
    """Normalize rejection reason to standard forms."""
    reason_lower = reason.lower()
    if "constitution" in reason_lower:
        return "constitution_mismatch"
    if "goal" in reason_lower or "misalign" in reason_lower:
        return "goal_misaligned"
    if "duplicate" in reason_lower:
        return "duplicate_detected"
    if "measurable" in reason_lower or "acceptance" in reason_lower or "too_simple" in reason_lower:
        return "acceptance_criteria_incomplete"
    if "quality" in reason_lower:
        return "quality_score_too_low"
    return "validation_failed"


def track_rejections(prd_path: str, rejected_json_path: str, rejections_jsonl_path: str | None = None) -> int:
    """Update prd.json with rejection logs and write telemetry.

    Parameters
    ----------
    prd_path : str
        Path to prd.json
    rejected_json_path : str
        Path to .spiral/_story_rejected.json from Phase S
    rejections_jsonl_path : str | None
        Path to .spiral/rejections.jsonl (optional)

    Returns
    -------
    int
        0 on success, 1 on error
    """
    # Load prd.json
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Could not load prd.json: {e}", file=sys.stderr)
        return 1

    # Load rejected stories
    rejected_stories: list[dict[str, Any]] = []
    if os.path.exists(rejected_json_path):
        try:
            with open(rejected_json_path, encoding="utf-8") as f:
                rejected_data = json.load(f)
                rejected_stories = rejected_data.get("stories", [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ERROR: Could not load rejected stories: {e}", file=sys.stderr)
            return 1

    if not rejected_stories:
        return 0  # No rejections to track

    # Build map of story_id -> story in prd.json
    story_map: dict[str, dict[str, Any]] = {}
    for story in prd.get("userStories", []):
        sid = story.get("id", "")
        if sid:
            story_map[sid] = story

    # Update prd.json with rejection logs
    ts = datetime.now(timezone.utc).isoformat()
    rejection_log_entries: list[dict[str, Any]] = []

    for rejected in rejected_stories:
        story_id = rejected.get("id", "")
        reason = rejected.get("_rejection_reason", "")
        title = rejected.get("title", "")

        if not story_id or story_id not in story_map:
            continue

        story = story_map[story_id]

        # Add to _rejectionLog
        normalized_reason = _normalize_reason(reason)
        log_entry = {
            "timestamp": ts,
            "reason": normalized_reason,
            "details": reason,  # Full raw reason
        }

        if "_rejectionLog" not in story:
            story["_rejectionLog"] = []
        story["_rejectionLog"].append(log_entry)

        # Collect for telemetry
        rejection_log_entries.append(
            {
                "timestamp": ts,
                "story_id": story_id,
                "title": title,
                "reason": normalized_reason,
                "details": reason,
                "source": rejected.get("_source", "unknown"),
            }
        )

    # Write updated prd.json
    try:
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"ERROR: Could not write prd.json: {e}", file=sys.stderr)
        return 1

    # Write telemetry to .spiral/rejections.jsonl
    if rejections_jsonl_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(rejections_jsonl_path)), exist_ok=True)
            with open(rejections_jsonl_path, "a", encoding="utf-8") as f:
                for entry in rejection_log_entries:
                    f.write(json.dumps(entry) + "\n")
        except OSError as e:
            print(f"WARNING: Could not write rejections.jsonl: {e}", file=sys.stderr)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Track story rejections in prd.json and telemetry")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--rejected", required=True, help="Path to .spiral/_story_rejected.json")
    parser.add_argument("--rejections-jsonl", default="", help="Path to .spiral/rejections.jsonl (optional)")
    args = parser.parse_args()

    rejections_jsonl = args.rejections_jsonl or ""
    return track_rejections(args.prd, args.rejected, rejections_jsonl)


if __name__ == "__main__":
    sys.exit(main())
