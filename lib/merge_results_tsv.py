#!/usr/bin/env python3
"""
merge_results_tsv.py — Merge worker results.tsv files into the main results.tsv.

After parallel Ralph workers finish, each worker's worktree contains its own
results.tsv with telemetry rows. This script:
  1. Reads the main results.tsv (if it exists)
  2. Reads each worker results.tsv
  3. Deduplicates rows by (story_id, timestamp) composite key
  4. Sorts all rows chronologically by timestamp
  5. Writes the merged result back to the main results.tsv

Usage:
    python lib/merge_results_tsv.py --main results.tsv --workers wt1/results.tsv wt2/results.tsv
"""
import argparse
import csv
import os
import sys

HEADER = [
    "timestamp", "spiral_iter", "ralph_iter", "story_id", "story_title",
    "status", "duration_sec", "model", "retry_num", "commit_sha", "run_id",
]


def read_tsv(path: str) -> list[dict]:
    """Read a results.tsv file, returning list of row dicts. Returns [] if missing."""
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)
    return rows


def dedup_key(row: dict) -> tuple:
    """Composite key for deduplication: (story_id, timestamp)."""
    return (row.get("story_id", ""), row.get("timestamp", ""))


def merge(main_path: str, worker_paths: list[str]) -> int:
    """Merge worker results.tsv files into main, with dedup and sort."""
    # Load existing main rows
    main_rows = read_tsv(main_path)

    # Track seen keys for deduplication
    seen = set()
    unique_rows: list[dict] = []

    for row in main_rows:
        key = dedup_key(row)
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    # Load and merge each worker file
    workers_merged = 0
    rows_added = 0
    for wpath in worker_paths:
        if not os.path.isfile(wpath):
            print(f"[merge_results] WARNING: {wpath} not found — skipping")
            continue
        worker_rows = read_tsv(wpath)
        workers_merged += 1
        for row in worker_rows:
            key = dedup_key(row)
            if key not in seen:
                seen.add(key)
                unique_rows.append(row)
                rows_added += 1

    if not unique_rows:
        print("[merge_results] No results rows to write")
        return 0

    # Sort by timestamp (ISO 8601 strings sort lexicographically)
    unique_rows.sort(key=lambda r: r.get("timestamp", ""))

    # Write merged results
    with open(main_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=HEADER, delimiter="\t",
            extrasaction="ignore", lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(unique_rows)

    print(f"[merge_results] Merged {workers_merged} worker file(s): "
          f"{rows_added} new rows added, {len(unique_rows)} total rows")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge parallel worker results.tsv into main results.tsv")
    parser.add_argument("--main", required=True, help="Main results.tsv path")
    parser.add_argument("--workers", nargs="+", required=True,
                        help="Worker results.tsv paths")
    args = parser.parse_args()
    return merge(args.main, args.workers)


if __name__ == "__main__":
    sys.exit(main())
