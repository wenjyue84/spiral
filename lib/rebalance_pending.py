"""rebalance_pending.py — Enforce a cap on pending stories in prd.json.

When the number of incomplete (passes=false) stories exceeds --max-pending,
this script:
  1. Ranks all pending stories by importance (priority, then quick-wins first).
  2. Keeps the top N stories in prd.json.
  3. Moves the rest into candidate_us.json — a priority queue that feeds back
     into Phase M next iteration via --overflow-in.

Usage:
    python rebalance_pending.py --prd prd.json \
        --candidate-out .spiral/candidate_us.json \
        --overflow-out .spiral/_research_overflow.json \
        --max-pending 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, safe_read_json

# ── Priority / complexity score helpers ──────────────────────────────────────

_PRIORITY_ORDER = {"S": 0, "P0": 1, "P1": 2, "P2": 3, "P3": 4, "P4": 5}
_COMPLEXITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _priority_score(story: dict[str, Any]) -> int:
    p = (story.get("priority") or "").strip().upper()
    return _PRIORITY_ORDER.get(p, 6)  # unset = least important


def _complexity_score(story: dict[str, Any]) -> int:
    c = (story.get("complexity") or "").strip().lower()
    return _COMPLEXITY_ORDER.get(c, 3)  # unset = treated like high


def importance_key(idx_story: tuple[int, dict[str, Any]]) -> tuple:
    """Lower = more important. Sort ascending to get most important first."""
    idx, story = idx_story
    return (_priority_score(story), _complexity_score(story), idx)


# ── JSON I/O helpers ─────────────────────────────────────────────────────────


def _story_to_candidate(story: dict[str, Any]) -> dict[str, Any]:
    """Convert a prd.json story entry to merge_stories candidate format."""
    cand: dict[str, Any] = {
        "title": story.get("title", ""),
        "description": story.get("description", ""),
        "_source": story.get("_source", "candidate"),
        "_evictedFromPrd": True,
    }
    for k in ("priority", "complexity", "epicId", "acceptanceCriteria", "filesTouched"):
        if story.get(k) is not None:
            cand[k] = story[k]
    return cand


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce pending story cap in prd.json")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--candidate-out", required=True,
                        help="Path to write/update candidate_us.json")
    parser.add_argument("--overflow-out",
                        help="Also merge evicted candidates here (for Phase M pickup)")
    parser.add_argument("--max-pending", type=int, default=50,
                        help="Maximum allowed pending (incomplete) stories in prd.json (default 50)")
    args = parser.parse_args()

    if args.max_pending <= 0:
        print("[rebalance] max-pending is 0 — skipping (unlimited)")
        return 0

    # ── Load prd.json ─────────────────────────────────────────────────────────
    try:
        prd = safe_read_json(args.prd)
    except Exception as e:
        print(f"[rebalance] ERROR reading prd.json: {e}", file=sys.stderr)
        return 1

    if prd is None or "userStories" not in prd:
        print("[rebalance] prd.json missing or has no userStories — nothing to do")
        return 0

    user_stories: list[dict[str, Any]] = prd["userStories"]
    pending = [s for s in user_stories if not s.get("passes", False)]
    passed  = [s for s in user_stories if s.get("passes", False)]

    print(f"[rebalance] Pending: {len(pending)}, cap: {args.max_pending}")

    if len(pending) <= args.max_pending:
        print(f"[rebalance] Within cap — no eviction needed")
        return 0

    # ── Rank pending by importance ────────────────────────────────────────────
    indexed = list(enumerate(pending))
    indexed.sort(key=importance_key)

    keep = [s for _, s in indexed[: args.max_pending]]
    evict = [s for _, s in indexed[args.max_pending :]]

    print(f"[rebalance] Keeping {len(keep)} stories, evicting {len(evict)} → candidate_us.json")
    for s in evict:
        print(f"[rebalance]   EVICT [{s.get('id','?')}] P={s.get('priority','?')} C={s.get('complexity','?')} — {s.get('title','')[:70]}")

    # ── Update prd.json (keep passed + top-N pending) ─────────────────────────
    prd["userStories"] = passed + keep
    atomic_write_json(args.prd, prd)
    print(f"[rebalance] prd.json updated: {len(prd['userStories'])} stories ({len(passed)} passed + {len(keep)} pending)")

    # ── Convert evicted stories to candidate format ───────────────────────────
    new_candidates = [_story_to_candidate(s) for s in evict]

    # ── Merge into candidate_us.json (carry-forward queue) ───────────────────
    existing_cand = safe_read_json(args.candidate_out, {"stories": []})
    if not isinstance(existing_cand, dict) or "stories" not in existing_cand:
        existing_cand = {"stories": []}

    # Dedup by title (simple check — avoid re-adding what we already have)
    existing_titles = {s.get("title", "").strip().lower() for s in existing_cand["stories"]}
    added = 0
    for c in new_candidates:
        if c["title"].strip().lower() not in existing_titles:
            existing_cand["stories"].append(c)
            existing_titles.add(c["title"].strip().lower())
            added += 1

    atomic_write_json(args.candidate_out, existing_cand)
    print(f"[rebalance] candidate_us.json: {added} new + {len(existing_cand['stories']) - added} existing = {len(existing_cand['stories'])} total")

    # ── Optionally merge into overflow file for Phase M pickup ────────────────
    if args.overflow_out:
        existing_overflow = safe_read_json(args.overflow_out, {"stories": []})
        if not isinstance(existing_overflow, dict) or "stories" not in existing_overflow:
            existing_overflow = {"stories": []}
        overflow_titles = {s.get("title", "").strip().lower() for s in existing_overflow["stories"]}
        overflow_added = 0
        for c in new_candidates:
            if c["title"].strip().lower() not in overflow_titles:
                existing_overflow["stories"].append(c)
                overflow_titles.add(c["title"].strip().lower())
                overflow_added += 1
        atomic_write_json(args.overflow_out, existing_overflow)
        if overflow_added:
            print(f"[rebalance] Also merged {overflow_added} candidates into {args.overflow_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
