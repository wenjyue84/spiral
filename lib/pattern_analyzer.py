#!/usr/bin/env python3
"""
pattern_analyzer.py — Retry pattern analysis for Phase L.

Analyzes completed user stories, clustering by retry count (0, 1, 2, 3+) and
extracting common traits (AC count, description length, tags, file patterns)
that correlate with easy vs. hard stories.

US-785: Phase L Retry Pattern Analysis
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_prd(prd_path: str) -> list[dict[str, Any]]:
    """Load prd.json and return all stories."""
    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
            stories = data.get("userStories", [])
            return stories if isinstance(stories, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_retry_counts(retry_path: str) -> dict[str, int]:
    """Load retry-counts.json mapping story IDs to retry counts."""
    try:
        with open(retry_path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def extract_traits(story: dict[str, Any]) -> dict[str, Any]:
    """Extract key traits from a story for clustering analysis."""
    ac_list = story.get("acceptanceCriteria", [])
    ac_count = len(ac_list) if isinstance(ac_list, list) else 0

    description = story.get("description", "")
    description_length = len(description) if description else 0

    # Extract tags, handling null/missing
    tags = story.get("tags", [])
    tags = tags if isinstance(tags, list) else []

    # Extract file patterns from description and filesTouch
    file_patterns = extract_file_patterns(story)

    return {
        "ac_count": ac_count,
        "description_length": description_length,
        "tags": tags,
        "file_patterns": file_patterns,
    }


def extract_file_patterns(story: dict[str, Any]) -> list[str]:
    """Extract common file path patterns from story description and filesTouch."""
    patterns = set()

    # Parse filesTouch if present
    files_touch = story.get("filesTouch")
    if isinstance(files_touch, list):
        for filepath in files_touch:
            if isinstance(filepath, str):
                # Extract directory pattern (e.g., 'lib/', 'tests/')
                match = re.match(r"^([^/]+)/", filepath)
                if match:
                    patterns.add(match.group(1))

    # Extract file path patterns from description
    description = story.get("description", "")
    if description:
        # Match patterns like 'lib/foo.py', 'tests/test_bar.py'
        file_matches = re.findall(r"\b([a-z_]+/[a-z_.]+\.py)\b", description)
        for fpath in file_matches:
            match = re.match(r"^([^/]+)/", fpath)
            if match:
                patterns.add(match.group(1))

    return sorted(list(patterns))


def cluster_stories_by_retry(
    stories: list[dict[str, Any]], retry_counts: dict[str, int]
) -> dict[str, list[dict[str, Any]]]:
    """Group stories by retry count: 0, 1, 2, 3+."""
    clusters: dict[str, list[dict[str, Any]]] = {"0": [], "1": [], "2": [], "3+": []}

    for story in stories:
        if not story.get("passes"):
            continue  # Skip incomplete stories

        story_id = story.get("id", "")
        retry_count = retry_counts.get(story_id, 0)

        if retry_count == 0:
            clusters["0"].append(story)
        elif retry_count == 1:
            clusters["1"].append(story)
        elif retry_count == 2:
            clusters["2"].append(story)
        else:
            clusters["3+"].append(story)

    return clusters


def aggregate_traits(
    stories: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate traits across a group of stories."""
    if not stories:
        return {
            "count": 0,
            "avg_ac_count": 0.0,
            "avg_description_length": 0.0,
            "common_tags": [],
            "common_file_patterns": [],
        }

    traits_list = [extract_traits(s) for s in stories]

    # Calculate averages
    avg_ac = sum(t["ac_count"] for t in traits_list) / len(traits_list)
    avg_desc = sum(t["description_length"] for t in traits_list) / len(traits_list)

    # Find common tags (appear in >50% of stories)
    all_tags: dict[str, int] = {}
    for traits in traits_list:
        for tag in traits["tags"]:
            all_tags[tag] = all_tags.get(tag, 0) + 1

    threshold = len(traits_list) * 0.5
    common_tags = sorted(
        [tag for tag, count in all_tags.items() if count >= threshold]
    )

    # Find common file patterns (appear in >50% of stories)
    all_patterns: dict[str, int] = {}
    for traits in traits_list:
        for pattern in traits["file_patterns"]:
            all_patterns[pattern] = all_patterns.get(pattern, 0) + 1

    common_patterns = sorted(
        [p for p, count in all_patterns.items() if count >= threshold]
    )

    return {
        "count": len(stories),
        "avg_ac_count": round(avg_ac, 2),
        "avg_description_length": round(avg_desc, 1),
        "common_tags": common_tags,
        "common_file_patterns": common_patterns,
    }


def analyze_patterns(
    prd_path: str, retry_path: str, iteration: int = 0
) -> dict[str, Any]:
    """Main analysis function: cluster stories and extract patterns."""
    stories = load_prd(prd_path)
    retry_counts = load_retry_counts(retry_path)

    # Cluster stories by retry count
    clusters = cluster_stories_by_retry(stories, retry_counts)

    # Aggregate traits per cluster
    patterns = {
        "iteration": iteration,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "0_retries": aggregate_traits(clusters["0"]),
            "1_retry": aggregate_traits(clusters["1"]),
            "2_retries": aggregate_traits(clusters["2"]),
            "3plus_retries": aggregate_traits(clusters["3+"]),
        },
        "insights": generate_insights(clusters),
    }

    return patterns


def generate_insights(clusters: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Generate actionable insights from the clustered data."""
    easy_stories = clusters["0"] + clusters["1"]
    hard_stories = clusters["3+"]

    insights: dict[str, Any] = {
        "total_analyzed": sum(len(s) for s in clusters.values()),
        "easy_count": len(easy_stories),
        "hard_count": len(hard_stories),
    }

    # Compare average AC count: easy vs hard
    if easy_stories and hard_stories:
        easy_acs = [
            len(s.get("acceptanceCriteria", []) or []) for s in easy_stories
        ]
        hard_acs = [
            len(s.get("acceptanceCriteria", []) or []) for s in hard_stories
        ]
        easy_avg_ac = sum(easy_acs) / len(easy_acs)
        hard_avg_ac = sum(hard_acs) / len(hard_acs)

        insights["easy_avg_ac_count"] = round(easy_avg_ac, 2)
        insights["hard_avg_ac_count"] = round(hard_avg_ac, 2)

    return insights


def save_patterns(
    patterns: dict[str, Any], output_path: str
) -> None:
    """Save learned patterns to .spiral/learned_patterns.json."""
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(patterns, f, indent=2)


def show_patterns(output_path: str) -> None:
    """Display learned patterns in human-readable format."""
    if not Path(output_path).exists():
        print(f"  [L] No patterns file found: {output_path}")
        print("     Run spiral.sh to generate patterns from completed stories.")
        return

    with open(output_path, "r", encoding="utf-8") as f:
        patterns = json.load(f)

    print("")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  📊 RETRY PATTERN ANALYSIS")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Iteration: {patterns.get('iteration', 'N/A')}")
    print(f"  Timestamp: {patterns.get('timestamp', 'N/A')}")
    print("")

    summary = patterns.get("summary", {})
    print("  EASY STORIES (0-1 retries):")
    easy_0 = summary.get("0_retries", {})
    easy_1 = summary.get("1_retry", {})
    print(
        f"    • 0 retries: {easy_0.get('count', 0)} stories, "
        f"avg ACs: {easy_0.get('avg_ac_count', 0)}, "
        f"avg desc length: {easy_0.get('avg_description_length', 0)}"
    )
    print(
        f"    • 1 retry: {easy_1.get('count', 0)} stories, "
        f"avg ACs: {easy_1.get('avg_ac_count', 0)}, "
        f"avg desc length: {easy_1.get('avg_description_length', 0)}"
    )

    hard_3 = summary.get("3plus_retries", {})
    print("  HARD STORIES (3+ retries):")
    print(
        f"    • 3+ retries: {hard_3.get('count', 0)} stories, "
        f"avg ACs: {hard_3.get('avg_ac_count', 0)}, "
        f"avg desc length: {hard_3.get('avg_description_length', 0)}"
    )

    print("")
    insights = patterns.get("insights", {})
    if insights.get("easy_avg_ac_count"):
        print("  KEY INSIGHTS:")
        print(
            f"    • Easy stories avg {insights.get('easy_avg_ac_count')} ACs, "
            f"hard stories avg {insights.get('hard_avg_ac_count')} ACs"
        )
        print(
            f"    • {insights.get('easy_count', 0)} easy stories vs "
            f"{insights.get('hard_count', 0)} hard stories analyzed"
        )

    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: pattern_analyzer.py <prd.json> [retry-counts.json] [iteration]")
        print("       pattern_analyzer.py show <learned_patterns.json>")
        sys.exit(1)

    if sys.argv[1] == "show":
        if len(sys.argv) < 3:
            print("Usage: pattern_analyzer.py show <learned_patterns.json>")
            sys.exit(1)
        show_patterns(sys.argv[2])
    else:
        prd_file = sys.argv[1]
        retry_file = sys.argv[2] if len(sys.argv) > 2 else "retry-counts.json"
        iteration = int(sys.argv[3]) if len(sys.argv) > 3 else 0

        patterns = analyze_patterns(prd_file, retry_file, iteration)
        print(json.dumps(patterns, indent=2))
