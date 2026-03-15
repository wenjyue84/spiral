#!/usr/bin/env python3
"""
SPIRAL — Dependency Cascade Skip (US-204)

When a story is marked _skipped: true, propagate that skip to all direct and
transitive dependents in prd.json, marking them _skipped: true with a
_failureReason of 'dependency <ID> was skipped'.

Cascaded skips are logged to spiral_events.jsonl with event_type:
dependency_cascade_skip.

Usage:
  python lib/cascade_skip.py --prd prd.json [--events spiral_events.jsonl]
                             [--iteration N] [--run-id RUN_ID]

Exit codes:
  0 = success (0 or more stories cascaded)
  1 = prd.json not found or invalid JSON
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))
from state_machine import cascade_skip


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cascade _skipped status through the prd.json dependency chain"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--events", default="", help="Path to spiral_events.jsonl (optional)")
    parser.add_argument("--iteration", type=int, default=0, help="Current SPIRAL iteration number")
    parser.add_argument("--run-id", default="", help="SPIRAL_RUN_ID for event correlation")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[cascade_skip] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[cascade_skip] ERROR: cannot read {args.prd}: {e}", file=sys.stderr)
        return 1

    events_path = args.events if args.events else None

    newly = cascade_skip(
        prd,
        events_path=events_path,
        iteration=args.iteration,
        run_id=args.run_id,
    )

    if newly:
        # Atomic write: write to temp then rename
        tmp = args.prd + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(prd, f, indent=2, ensure_ascii=False)
                f.write("\n")
            shutil.move(tmp, args.prd)
        except OSError as e:
            print(f"[cascade_skip] ERROR: cannot write {args.prd}: {e}", file=sys.stderr)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return 1

        for sid in newly:
            story = next((s for s in prd.get("userStories", []) if s.get("id") == sid), {})
            reason = story.get("_failureReason", "")
            print(f"[cascade_skip]   x {sid} — {reason}")
        print(f"[cascade_skip] {len(newly)} story/stories cascaded as _skipped")
    else:
        print("[cascade_skip] no new cascades")

    return 0


if __name__ == "__main__":
    sys.exit(main())
