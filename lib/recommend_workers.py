#!/usr/bin/env python3
"""
SPIRAL — Dynamic Worker Count Recommendation
Analyzes pending story independence ratio and recommends 1-3 workers.

Independence = story has 0 pending dependencies (all deps passed or no deps).
Thresholds:
  independence_ratio >= 0.6 → 3 workers
  independence_ratio >= 0.3 → 2 workers
  else                      → 1 worker
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import configure_utf8_stdout
configure_utf8_stdout()


def recommend_workers(stories: list[dict]) -> tuple[int, int, int]:
    """Compute recommended worker count from pending story independence.

    Args:
        stories: list of story dicts from prd.json userStories

    Returns:
        (recommended_workers, independent_count, pending_count)
    """
    passed_ids = {
        s["id"] for s in stories
        if isinstance(s, dict) and s.get("passes") is True
    }
    pending = [
        s for s in stories
        if isinstance(s, dict) and s.get("passes") is not True and "id" in s
    ]
    pending_count = len(pending)

    if pending_count == 0:
        return (1, 0, 0)

    independent_count = 0
    for s in pending:
        deps = s.get("dependencies", [])
        # A story is independent if all its deps are already passed or it has no deps
        pending_deps = [d for d in deps if d not in passed_ids]
        if len(pending_deps) == 0:
            independent_count += 1

    ratio = independent_count / pending_count

    if ratio >= 0.6:
        recommended = 3
    elif ratio >= 0.3:
        recommended = 2
    else:
        recommended = 1

    return (recommended, independent_count, pending_count)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Recommend worker count based on story independence"
    )
    parser.add_argument("prd", help="Path to prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[workers] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    try:
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[workers] ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    stories = prd.get("userStories", [])
    recommended, independent, pending = recommend_workers(stories)

    print(
        f"[workers] {independent} of {pending} pending stories are independent"
        f" — recommending {recommended} workers"
    )
    # Output just the number on the last line for shell parsing
    print(recommended)
    return 0


if __name__ == "__main__":
    sys.exit(main())
