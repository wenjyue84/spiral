#!/usr/bin/env python3
"""
lib/constitution_validator_runner.py — Phase S constitution validation runner

Integrates constitution_validator.py into Phase S pipeline.
Reads validated stories, checks against constitution rules, and filters
invalid stories into _rejected_stories.json.

Usage:
  python lib/constitution_validator_runner.py \\
    --constitution .specify/memory/constitution.md \\
    --stories .spiral/_validated_stories.json \\
    --rejected-out .spiral/_rejected_stories.json
"""

import argparse
import json
import os
import sys
from typing import Any

# Add lib to path
sys.path.insert(0, os.path.dirname(__file__))

from constitution_validator import (
    log_rejection,
    parse_constitution_rules,
    validate_story,
)
from spiral_io import configure_utf8_stdout

configure_utf8_stdout()


def run_constitution_validation(
    constitution_file: str,
    stories_file: str,
    rejected_out: str,
) -> None:
    """Run constitution validation on stories and split valid/invalid.

    Args:
        constitution_file: Path to constitution.md
        stories_file: Path to _validated_stories.json
        rejected_out: Path to write _rejected_stories.json
    """
    # Parse constitution rules
    rules = parse_constitution_rules(constitution_file)
    if not rules["antipatterns"] and not rules["forbidden_phrases"]:
        print("  [S] Constitution validation: no rules found, skipping")
        return

    # Load stories
    stories_data: dict[str, Any] = {}
    if os.path.exists(stories_file):
        try:
            with open(stories_file, encoding="utf-8") as fh:
                stories_data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  [S] WARNING: Cannot read {stories_file}: {e}")
            return

    stories = stories_data.get("stories", [])
    if not stories:
        print("  [S] Constitution validation: no stories to validate")
        return

    # Validate each story
    valid_stories: list[dict[str, Any]] = []
    rejected_count = 0

    for story in stories:
        is_valid, reason = validate_story(story, rules)
        if is_valid:
            valid_stories.append(story)
        else:
            rejected_count += 1
            log_rejection(story, reason, phase="S", output_file=rejected_out)
            print(f"  [S] REJECTED (constitution): {story.get('id', '?')} — {reason}")

    # Update stories file with only valid stories
    try:
        os.makedirs(os.path.dirname(stories_file) or ".", exist_ok=True)
        with open(stories_file, "w", encoding="utf-8") as fh:
            json.dump({"stories": valid_stories}, fh, indent=2)
    except OSError as e:
        print(f"  [S] WARNING: Cannot write {stories_file}: {e}")

    # Summary
    print(
        f"  [S] Constitution validation: {len(valid_stories)} valid, "
        f"{rejected_count} rejected"
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Phase S: Constitution Validation Engine"
    )
    parser.add_argument(
        "--constitution",
        required=True,
        help="Path to constitution.md",
    )
    parser.add_argument(
        "--stories",
        required=True,
        help="Path to _validated_stories.json",
    )
    parser.add_argument(
        "--rejected-out",
        required=True,
        help="Path to write _rejected_stories.json",
    )
    args = parser.parse_args()

    run_constitution_validation(
        args.constitution,
        args.stories,
        args.rejected_out,
    )


if __name__ == "__main__":
    main()
