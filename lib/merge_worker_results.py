#!/usr/bin/env python3
"""
SPIRAL Parallel Phase — Merge Worker Results
Reads N worker prd.json files and promotes any passes=true story back into
the main prd.json.  Worker prd files are never deleted here — caller cleans up.
"""
import argparse
import json
import os
import shutil
import sys

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge parallel worker prd.json results")
    parser.add_argument("--main", required=True, help="Main prd.json path")
    parser.add_argument("--workers", nargs="+", required=True, help="Worker prd.json paths")
    args = parser.parse_args()

    if not os.path.isfile(args.main):
        print(f"[merge_workers] ERROR: {args.main} not found", file=sys.stderr)
        return 1

    with open(args.main, encoding="utf-8") as f:
        main_prd = json.load(f)

    # Collect all story IDs that passed in ANY worker
    passed_ids: set[str] = set()
    for wpath in args.workers:
        if not os.path.isfile(wpath):
            print(f"[merge_workers] WARNING: {wpath} not found — skipping")
            continue
        with open(wpath, encoding="utf-8") as f:
            worker_prd = json.load(f)
        for s in worker_prd.get("userStories", []):
            if s.get("passes"):
                passed_ids.add(s["id"])

    # Promote passes in main prd
    newly_passed = 0
    for s in main_prd.get("userStories", []):
        if s["id"] in passed_ids and not s.get("passes"):
            s["passes"] = True
            newly_passed += 1
            print(f"[merge_workers]   + {s['id']} — {s.get('title', '')[:60]}")

    # Atomic write
    tmp = args.main + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(main_prd, f, indent=2, ensure_ascii=False)
        f.write("\n")
    shutil.move(tmp, args.main)

    total = len(main_prd.get("userStories", []))
    total_passed = sum(1 for s in main_prd.get("userStories", []) if s.get("passes"))
    pending = total - total_passed
    print(f"[merge_workers] {newly_passed} newly passed. Total: {total_passed}/{total} ({pending} pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
