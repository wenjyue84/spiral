#!/usr/bin/env python3
"""
Hint recommender from story attempt history.

Analyzes results.tsv to extract lessons from past story attempts and recommends:
  - Whether a story should be decomposed (if similar stories have high failure rates)
  - Which model tier to use (if haiku pass rate is low for the complexity band)
  - Recommended retry count (based on historical retry patterns)

Usage:
  python hint_recommender.py --results results.tsv --prd prd.json \\
    --story-id US-123 --complexity small

Returns JSON with keys: decomposition_suggested, recommended_model, recommended_retries
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from typing import Any


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


def load_results_tsv(path: str) -> list[dict[str, str]]:
    """Load results.tsv and return list of attempt records."""
    try:
        records = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return []
            for row in reader:
                if row:
                    records.append(row)
        return records
    except (FileNotFoundError, Exception) as e:
        print(f"WARNING: Failed to load {path}: {e}", file=sys.stderr)
        return []


def analyze_story_cohort(results: list[dict[str, str]], complexity: str) -> dict[str, dict[str, Any]]:
    """
    Analyze pass rates by model for a given complexity band.

    Args:
        results: List of attempt records from results.tsv
        complexity: Complexity band (small, medium, large)

    Returns:
        Dict mapping model name to {pass_count, fail_count, pass_rate}
    """
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"pass_count": 0, "fail_count": 0})

    for record in results:
        record_complexity = record.get("estimatedComplexity", "").strip()
        if not record_complexity:
            # Try to infer from story title/description if available
            continue
        if record_complexity != complexity:
            continue

        model = record.get("model", "").strip().lower()
        status = record.get("status", "").strip().lower()

        if not model:
            continue

        if status == "pass":
            stats[model]["pass_count"] += 1
        elif status in ("reject", "fail"):
            stats[model]["fail_count"] += 1

    # Calculate pass rates
    for model in stats:
        total = stats[model]["pass_count"] + stats[model]["fail_count"]
        stats[model]["pass_rate"] = stats[model]["pass_count"] / total if total > 0 else 0.0

    return dict(stats)


def suggest_hints_from_history(story: dict[str, Any], results: list[dict[str, str]]) -> dict[str, Any]:
    """
    Suggest hints for a story based on historical attempt data.

    Args:
        story: Story dict from prd.json with id, complexity, title
        results: List of attempt records from results.tsv

    Returns:
        Dict with keys:
          - decomposition_suggested: bool or str recommendation
          - recommended_model: str (haiku, sonnet, opus)
          - recommended_retries: int
    """
    hints: dict[str, Any] = {
        "decomposition_suggested": False,
        "recommended_model": "haiku",
        "recommended_retries": 1,
    }

    story_id = story.get("id", "")
    complexity = story.get("estimatedComplexity", "medium").lower()

    # Step 1: Find all attempts for this exact story
    story_attempts = [r for r in results if r.get("story_id", "").strip() == story_id]

    if story_attempts:
        # If this story has been attempted before, check retry history
        max_retry = max(int(r.get("retry_num", 0)) for r in story_attempts if r.get("retry_num"))
        if max_retry >= 2:
            hints["decomposition_suggested"] = True
            hints["recommended_retries"] = min(3, max_retry + 1)

    # Step 2: Analyze cohort pass rates for the complexity band
    cohort_stats = analyze_story_cohort(results, complexity)

    # If we have haiku data and pass rate is low, recommend escalation
    if "haiku" in cohort_stats:
        haiku_pass_rate = cohort_stats["haiku"].get("pass_rate", 0.0)
        if haiku_pass_rate < 0.5:
            # Low haiku pass rate -> escalate to sonnet
            hints["recommended_model"] = "sonnet"

            # If sonnet also has low pass rate, escalate to opus
            if "sonnet" in cohort_stats:
                sonnet_pass_rate = cohort_stats["sonnet"].get("pass_rate", 0.0)
                if sonnet_pass_rate < 0.5 and "opus" in cohort_stats:
                    hints["recommended_model"] = "opus"

    # Step 3: If story has many files to touch, suggest decomposition
    files_to_touch = story.get("filesTouch", [])
    if len(files_to_touch) > 5:
        hints["decomposition_suggested"] = "Consider splitting: touches many files"

    return hints


def enrich_stories_with_hints(stories: list[dict[str, Any]], results: list[dict[str, str]]) -> list[dict[str, Any]]:
    """
    Enrich a list of stories with hints from attempt history.

    Args:
        stories: List of story dicts
        results: List of results.tsv records

    Returns:
        List of stories with _hints added to each
    """
    enriched = []
    for story in stories:
        enriched_story = dict(story)
        hints = suggest_hints_from_history(story, results)
        enriched_story.setdefault("_hints", [])
        enriched_story["_hints"].append(hints)
        enriched.append(enriched_story)
    return enriched


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Analyze story attempt history and recommend hints for implementation")
    parser.add_argument("--results", required=True, help="Path to results.tsv")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--story-id", help="Optional: specific story ID to get hints for (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing")

    args = parser.parse_args()

    results = load_results_tsv(args.results)

    if args.story_id:
        # Single story mode (for testing)
        stories_by_id = load_prd(args.prd)
        if args.story_id not in stories_by_id:
            print(f"ERROR: Story {args.story_id} not found in {args.prd}", file=sys.stderr)
            return 1

        story = stories_by_id[args.story_id]
        hints = suggest_hints_from_history(story, results)
        print(json.dumps(hints, indent=2))
        return 0

    # Otherwise, would enrich all stories (integration with Phase E)
    # This is handled by phase_e_enrich.sh calling the function programmatically
    return 0


if __name__ == "__main__":
    sys.exit(main())
