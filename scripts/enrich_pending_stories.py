#!/usr/bin/env python3
"""
One-shot enrichment: fill in empty technicalNotes for pending stories in prd.json.

Finds all pending stories where technicalNotes == [] and calls the existing
enrich_stories._enrich_one() to have Claude add file paths and test commands.

Usage:
    uv run python scripts/enrich_pending_stories.py
    uv run python scripts/enrich_pending_stories.py --dry-run
    uv run python scripts/enrich_pending_stories.py --model haiku
"""

import argparse
import json
import os
import re
import sys

# Make lib/ and lib/research/ importable from any working directory
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_root, "lib", "research"))
sys.path.insert(0, os.path.join(_root, "lib"))

from enrich_stories import _enrich_one  # noqa: E402  (path set above)

PRD_PATH = os.path.join(_root, "prd.json")


def _next_id(stories: list[dict]) -> str:  # type: ignore[type-arg]
    """Return the next available US-NNN id not already in stories."""
    nums = []
    for s in stories:
        m = re.match(r"US-(\d+)", s.get("id", ""))
        if m:
            nums.append(int(m.group(1)))
    return f"US-{max(nums, default=0) + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich pending prd.json stories that have empty technicalNotes"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be enriched without calling Claude",
    )
    parser.add_argument(
        "--model",
        default="sonnet",
        help="Claude model to use for enrichment (default: sonnet)",
    )
    args = parser.parse_args()

    with open(PRD_PATH, encoding="utf-8") as f:
        data = json.load(f)

    stories: list[dict] = data["userStories"]  # type: ignore[type-arg]

    targets = [
        s
        for s in stories
        if s.get("passes") is False and not s.get("technicalNotes")
    ]

    if not targets:
        print("No pending stories with empty technicalNotes — nothing to do.")
        return 0

    print(f"Found {len(targets)} stories to enrich:")
    for s in targets:
        print(f"  {s['id']}: {s['title'][:70]}")

    new_stories: list[dict] = []  # type: ignore[type-arg]
    enriched_count = 0
    split_count = 0

    for story in targets:
        print(f"\n[E] {story['id']}: {story['title'][:60]!r}")

        result = _enrich_one(story, model=args.model, dry_run=args.dry_run)

        # Passthrough — enrichment failed or dry-run
        if len(result) == 1 and result[0] is story:
            if not args.dry_run:
                print("  [E] Passthrough — leaving unchanged")
            continue

        # Fields not in prd.json schema that _enrich_one may inject
        _DISALLOWED = {"_enrichedFrom", "_enriched"}

        if len(result) > 1:
            # Split: assign new IDs, mark parent as decomposed
            split_count += 1
            sub_ids: list[str] = []
            for sub in result:
                new_id = _next_id(stories + new_stories)
                sub["id"] = new_id
                sub.setdefault("passes", False)
                sub.setdefault("_source", story.get("_source", "research"))
                sub["_decomposedFrom"] = story["id"]
                # Strip fields not allowed by prd.json schema
                for f in _DISALLOWED:
                    sub.pop(f, None)
                new_stories.append(sub)
                sub_ids.append(new_id)
                print(f"  [E]   + sub-story {new_id}: {sub.get('title', '?')[:60]}")
            story["_decomposed"] = True
            story["_decomposedInto"] = sub_ids
            enriched_count += len(result)
        else:
            # Enrich: patch only technicalNotes and acceptanceCriteria back into the
            # original story so we don't overwrite id, passes, _source, tags, etc.
            enriched = result[0]
            story["technicalNotes"] = enriched.get(
                "technicalNotes", story.get("technicalNotes", [])
            )
            story["acceptanceCriteria"] = enriched.get(
                "acceptanceCriteria", story.get("acceptanceCriteria", [])
            )
            enriched_count += 1
            notes = story["technicalNotes"]
            print(f"  [E]   technicalNotes: {len(notes)} item(s)")
            for note in notes[:3]:
                print(f"    - {note[:80]}")

    if new_stories:
        data["userStories"].extend(new_stories)

    if not args.dry_run:
        if enriched_count > 0 or split_count > 0:
            with open(PRD_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(
                f"\nSaved prd.json — {enriched_count} stories enriched "
                f"({split_count} splits, {len(new_stories)} new sub-stories added)"
            )
        else:
            print("\nNo changes made.")
    else:
        print(f"\n[dry-run] Would have enriched up to {len(targets)} stories.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
