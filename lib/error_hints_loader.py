#!/usr/bin/env python3
"""Load error recovery hints from failure history.

Analyzes results.tsv to find past failures of a story, classifies them using
error_classifier, and maps them to recovery hints from error_hints.json.

Usage:
  python error_hints_loader.py --story-title "US-1234 My Story" --results results.tsv

Returns JSON list of hint strings for the decomposition context.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_error_hints() -> dict[str, list[str]]:
    """Load error hints from lib/error_hints.json.

    Returns:
        Dict mapping error category to list of hint strings.
        Returns empty dict if file not found.
    """
    hints_file = Path(__file__).parent / "error_hints.json"
    if not hints_file.exists():
        return {}

    try:
        with hints_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (json.JSONDecodeError, IOError):
        return {}


def classify_error(error_msg: str) -> str:
    """Classify an error message into a category.

    Uses pattern matching on error text. Maps to error categories for hint lookup.

    Args:
        error_msg: Error text to classify

    Returns:
        Error category: timeout, oom, syntax, import, assertion, network, auth, unknown
    """
    msg = error_msg.lower()

    # Pattern-based classification
    # Order matters: check specific patterns before general ones
    patterns: dict[str, list[str]] = {
        "timeout": ["timeout", "timed out", "time limit", "deadline exceeded"],
        "oom": ["out of memory", "oom", "memoryerror", "heap overflow", "v8 heap"],
        "import": ["importerror", "modulenotfounderror", "no module named", "cannot import"],
        "syntax": ["syntaxerror", "syntax error", "indentation", "unexpected token"],
        "assertion": ["assertionerror", "assert", "failed", "pytest", "test error"],
        "network": ["connectionerror", "socket", "network error", "ssl error", "httperror"],
        "auth": ["unauthorized", "forbidden", "permission denied", "401", "403"],
    }

    for category, pattern_list in patterns.items():
        if any(p in msg for p in pattern_list):
            return category

    return "unknown"


def load_hints_for_story(
    story_title: str,
    results_tsv: str = "results.tsv",
) -> list[str]:
    """Load recovery hints for a story based on past failures.

    Args:
        story_title: Story title/ID to look up in results.tsv
        results_tsv: Path to results.tsv file

    Returns:
        List of recovery hint strings specific to this story's failure patterns.
        Returns empty list if no failures found or file doesn't exist.
    """
    results_path = Path(results_tsv)
    if not results_path.exists():
        return []

    error_hints = load_error_hints()
    if not error_hints:
        return []

    # Count failures by category for this story
    failure_counts: dict[str, int] = defaultdict(int)

    try:
        with results_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return []

            for row in reader:
                story_id = row.get("story_id", "").strip()
                title = row.get("story_title", "").strip()
                status = row.get("status", "").strip().lower()

                # Match story by ID first, then by title
                if not (story_title == story_id or story_title in title or title in story_title):
                    continue

                # Only count failed attempts
                if status not in ("reject", "fail", "failed", "skip"):
                    continue

                # Classify this failure
                # Use story_title as error proxy since results.tsv has no error_msg
                category = classify_error(title)
                failure_counts[category] += 1
    except (IOError, KeyError, csv.Error):
        return []

    if not failure_counts:
        return []

    # Collect hints for detected failure categories
    hints: list[str] = []
    for category, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
        category_hints = error_hints.get(category, [])
        for hint in category_hints:
            hints.append(hint)

    return hints


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Load error recovery hints from failure history")
    parser.add_argument("--story-title", required=True, help="Story title to look up")
    parser.add_argument("--results", default="results.tsv", help="Path to results.tsv")
    args = parser.parse_args()

    hints = load_hints_for_story(args.story_title, args.results)

    # Output as JSON for easy parsing by shell scripts
    output = json.dumps({"hints": hints, "count": len(hints)})
    print(output)


if __name__ == "__main__":
    main()
