#!/usr/bin/env python3
"""
merge_events.py — Merge per-worker event JSONL files into the main spiral_events.jsonl.

After parallel Ralph workers finish, each worker's event file at
.spiral/events/worker-N.jsonl is merged into the main spiral_events.jsonl.
This eliminates the Windows concurrent-append corruption risk by giving each
worker its own event file (mirrors the results.tsv worker isolation pattern).

Usage:
    python lib/observability/merge_events.py \
        --main .spiral/spiral_events.jsonl \
        --events-dir .spiral/events
"""

import argparse
import json
import os
import sys


def merge_events(main_path: str, events_dir: str) -> int:
    """Merge per-worker event files into main, sorted by timestamp."""
    # Collect all worker event files
    worker_files = []
    if os.path.isdir(events_dir):
        for f in sorted(os.listdir(events_dir)):
            if f.startswith("worker-") and f.endswith(".jsonl"):
                worker_files.append(os.path.join(events_dir, f))

    if not worker_files:
        return 0

    # Read existing main events
    main_events: list[str] = []
    if os.path.isfile(main_path):
        with open(main_path, encoding="utf-8", errors="replace") as fh:
            main_events = [line for line in fh if line.strip()]

    # Read worker events
    worker_events: list[str] = []
    workers_merged = 0
    for wpath in worker_files:
        try:
            with open(wpath, encoding="utf-8", errors="replace") as fh:
                lines = [line for line in fh if line.strip()]
                worker_events.extend(lines)
                workers_merged += 1
        except OSError:
            print(f"[merge_events] WARNING: {wpath} not readable — skipping", file=sys.stderr)

    if not worker_events:
        return 0

    # Merge all events and sort by timestamp
    all_lines = main_events + worker_events

    def sort_key(line: str) -> str:
        try:
            return json.loads(line).get("ts", "")
        except (json.JSONDecodeError, AttributeError):
            return ""

    all_lines.sort(key=sort_key)

    # Write merged file
    parent = os.path.dirname(os.path.abspath(main_path))
    os.makedirs(parent, exist_ok=True)
    with open(main_path, "w", encoding="utf-8") as fh:
        for line in all_lines:
            line = line.rstrip("\n")
            fh.write(line + "\n")

    # Clean up worker files after successful merge
    for wpath in worker_files:
        try:
            os.unlink(wpath)
        except OSError:
            pass

    rows_added = len(worker_events)
    print(
        f"[merge_events] Merged {workers_merged} worker event file(s): "
        f"{rows_added} events added, {len(all_lines)} total events"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge per-worker event JSONL files into main spiral_events.jsonl")
    parser.add_argument("--main", required=True, help="Main spiral_events.jsonl path")
    parser.add_argument("--events-dir", required=True, help="Directory containing worker-N.jsonl files")
    args = parser.parse_args()
    return merge_events(args.main, args.events_dir)


if __name__ == "__main__":
    sys.exit(main())
