#!/usr/bin/env python3
"""
Record calibration data for SPIRAL stories.

Reads results.tsv and prd.json, computes actual vs estimated complexity
for each completed story, and appends records to calibration.jsonl.

Usage:
  ./lib/record_calibration.py --results results.tsv --prd prd.json --calibration calibration.jsonl
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import append_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Record calibration data for SPIRAL stories")
    parser.add_argument("--results", required=True, help="Path to results.tsv")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--calibration", default="calibration.jsonl", help="Path to calibration.jsonl (default: calibration.jsonl)")
    args = parser.parse_args()

    results_path = Path(args.results)
    prd_path = Path(args.prd)
    calibration_path = Path(args.calibration)

    # Load prd.json to get story metadata
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[calibration] ERROR: Failed to read {prd_path}: {exc}", file=sys.stderr)
        return 1

    # Index stories by ID for quick lookup
    story_map: dict[str, dict] = {}
    for story in prd.get("userStories", []):
        story_map[story["id"]] = story

    # Load existing calibration.jsonl to avoid duplicate entries
    existing_records: set[str] = set()
    if calibration_path.exists():
        try:
            with open(calibration_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        # Use story_id + timestamp as unique key to avoid duplicates
                        key = f"{record.get('story_id')}:{record.get('timestamp', '')}"
                        existing_records.add(key)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[calibration] WARNING: Failed to read existing {calibration_path}: {exc}", file=sys.stderr)

    # Process results.tsv
    if not results_path.exists():
        print(f"[calibration] WARNING: {results_path} not found", file=sys.stderr)
        return 0

    new_records = 0
    try:
        with open(results_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                print(f"[calibration] WARNING: {results_path} is empty", file=sys.stderr)
                return 0

            for row in reader:
                story_id = row.get("story_id", "")
                if not story_id:
                    continue

                # Skip if already recorded
                timestamp = row.get("timestamp", "")
                unique_key = f"{story_id}:{timestamp}"
                if unique_key in existing_records:
                    continue

                # Get story details
                story = story_map.get(story_id)
                if not story:
                    continue

                # Extract data
                estimated_complexity = story.get("estimatedComplexity", "unknown")
                actual_duration_s = int(row.get("duration_sec", 0))
                phase_retries = int(row.get("retry_num", 0))
                status = row.get("status", "")
                passed = status == "pass"

                # Create calibration record
                record = {
                    "story_id": story_id,
                    "story_title": row.get("story_title", ""),
                    "timestamp": timestamp,
                    "estimated_complexity": estimated_complexity,
                    "actual_duration_s": actual_duration_s,
                    "phase_retries": phase_retries,
                    "passed": passed,
                    "model": row.get("model", ""),
                    "spiral_iter": int(row.get("spiral_iter", 0)),
                    "ralph_iter": int(row.get("ralph_iter", 0)),
                }

                # Append to calibration.jsonl
                append_jsonl(str(calibration_path), record)

                new_records += 1
                existing_records.add(unique_key)

    except (csv.Error, OSError) as exc:
        print(f"[calibration] ERROR: Failed to process {results_path}: {exc}", file=sys.stderr)
        return 1

    if new_records > 0:
        print(f"[calibration] Recorded {new_records} new calibration entries")

    return 0


if __name__ == "__main__":
    sys.exit(main())
