#!/usr/bin/env python3
"""
Integrate hint recommender into Phase E enrichment pipeline.

Takes validated (or similar-solutions enriched) stories and adds _hints
from attempt history, then outputs the enriched stories.

Usage:
  python hint_enricher.py --prd prd.json \\
    --results results.tsv \\
    --enriched-in _similar_output.json \\
    --enriched-out _hints_output.json
"""

import argparse
import json
import sys
from typing import Any

from hint_recommender import load_results_tsv, suggest_hints_from_history


def load_json(path: str) -> dict[str, Any]:
    """Load JSON from file."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def load_prd(path: str) -> dict[str, Any]:
    """Load prd.json and return story lookup by ID."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            stories_by_id = {}
            for s in data.get("userStories", []):
                stories_by_id[s.get("id")] = s
            return stories_by_id
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def enrich_with_hints(
    stories: list[dict[str, Any]],
    stories_by_id: dict[str, Any],
    results: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """
    Add _hints to stories from attempt history.

    Args:
        stories: List of enriched stories (from similar_story_finder or validated)
        stories_by_id: Lookup dict of full story details from prd.json
        results: List of results.tsv records

    Returns:
        Stories with _hints added
    """
    enriched = []

    for story in stories:
        enriched_story = dict(story)

        # Get full story details to extract complexity band
        story_id = story.get("id")
        if story_id in stories_by_id:
            full_story = stories_by_id[story_id]
            hints = suggest_hints_from_history(full_story, results)

            # Initialize _hints array if needed
            if "_hints" not in enriched_story:
                enriched_story["_hints"] = []

            # Append hints as a dict
            enriched_story["_hints"].append(hints)

        enriched.append(enriched_story)

    return enriched


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Enrich stories with hints from attempt history (Phase E step 1.5)")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--results", required=True, help="Path to results.tsv")
    parser.add_argument("--enriched-in", required=True, help="Path to input enriched stories")
    parser.add_argument("--enriched-out", required=True, help="Path to output enriched stories")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing")

    args = parser.parse_args()

    # Load data
    enriched_data = load_json(args.enriched_in)
    stories = enriched_data.get("stories", [])
    stories_by_id = load_prd(args.prd)
    results = load_results_tsv(args.results)

    # Enrich with hints
    enriched = enrich_with_hints(stories, stories_by_id, results)

    output = {"stories": enriched}

    if args.dry_run:
        print(json.dumps(output, indent=2))
    else:
        with open(args.enriched_out, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"[hint_enricher] Enriched {len(enriched)} stories with hints -> {args.enriched_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
