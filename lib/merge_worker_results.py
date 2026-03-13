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

sys.path.insert(0, os.path.dirname(__file__))
from prd_schema import validate_prd

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

    errors = validate_prd(main_prd)
    if errors:
        print("[schema] Main PRD validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    main_ids = {s["id"] for s in main_prd.get("userStories", [])}

    # Collect passes, decomposition flags, skipped flags, and new sub-stories from workers
    passed_ids: set[str] = set()
    decomposed_map: dict[str, list[str]] = {}  # parent_id → child_ids
    skipped_map: dict[str, str] = {}  # story_id → _skipReason
    new_substories: list[dict] = []

    for wpath in args.workers:
        if not os.path.isfile(wpath):
            print(f"[merge_workers] WARNING: {wpath} not found — skipping")
            continue
        with open(wpath, encoding="utf-8") as f:
            worker_prd = json.load(f)
        w_errors = validate_prd(worker_prd)
        if w_errors:
            print(f"[merge_workers] WARNING: Worker PRD validation failed ({wpath}) — skipping")
            for e in w_errors:
                print(f"  - {e}")
            continue
        for s in worker_prd.get("userStories", []):
            if s.get("passes"):
                passed_ids.add(s["id"])
            # Collect decomposition flags from workers
            if s.get("_decomposed") and s["id"] in main_ids:
                decomposed_map[s["id"]] = s.get("_decomposedInto", [])
            # Collect skipped flags from workers
            if s.get("_skipped") and s["id"] in main_ids:
                skipped_map[s["id"]] = s.get("_skipReason", "MAX_RETRIES exhausted")
            # Collect new sub-stories created by decomposition in workers
            if s.get("_decomposedFrom") and s["id"] not in main_ids:
                new_substories.append(s)

    # Promote passes in main prd
    newly_passed = 0
    for s in main_prd.get("userStories", []):
        if s["id"] in passed_ids and not s.get("passes"):
            s["passes"] = True
            newly_passed += 1
            print(f"[merge_workers]   + {s['id']} — {s.get('title', '')[:60]}")
        # Apply decomposition flags from workers
        if s["id"] in decomposed_map:
            s["_decomposed"] = True
            s["_decomposedInto"] = decomposed_map[s["id"]]
            print(f"[merge_workers]   ~ {s['id']} decomposed → [{', '.join(decomposed_map[s['id']])}]")
        # Apply skipped flags from workers
        if s["id"] in skipped_map and not s.get("_skipped"):
            s["_skipped"] = True
            s["_skipReason"] = skipped_map[s["id"]]
            print(f"[merge_workers]   x {s['id']} skipped — {s['_skipReason']}")

    # Append new sub-stories from worker decompositions
    if new_substories:
        main_prd["userStories"].extend(new_substories)
        for ss in new_substories:
            print(f"[merge_workers]   + {ss['id']} (sub-story of {ss.get('_decomposedFrom')}) — {ss.get('title', '')[:60]}")

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
