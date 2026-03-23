"""lib/record_rejected_patterns.py — Record rejected story patterns (US-771).

After Phase S rejects stories, this script records their fingerprints to
the cross-iteration rejection cache. Called from Phase S.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(args: list[str] | None = None) -> int:
    """Record rejected stories to the pattern cache.

    Args:
        args: Command-line arguments (for testing)

    Returns:
        0 on success, 1 on error
    """
    parser = argparse.ArgumentParser(
        description="Record rejected story patterns for cross-iteration dedup (US-771)"
    )
    parser.add_argument("--rejected-stories", required=True, help="Path to _story_rejected.json")
    parser.add_argument("--cache-file", required=True, help="Path to rejected_patterns.json cache")
    parser.add_argument("--iteration", type=int, default=0, help="Current SPIRAL iteration")

    parsed = parser.parse_args(args)

    try:
        # Import after arg parsing so we can handle import errors
        from lib.rejected_pattern_cache import (
            record_rejected_story,
        )

        rejected_path = Path(parsed.rejected_stories)
        cache_path = Path(parsed.cache_file)

        if not rejected_path.exists():
            return 0  # No rejected stories file, nothing to do

        # Load rejected stories
        with open(rejected_path, "r", encoding="utf-8") as f:
            rejected_data = json.load(f)

        stories = rejected_data.get("stories", [])
        if not stories:
            return 0  # No rejected stories

        # Record each rejected story
        for story in stories:
            rejection_reason = story.get("_rejectionReason", "unknown")
            record_rejected_story(
                story,
                rejection_reason,
                cache_path,
                iteration=parsed.iteration,
                max_entries=100,
            )

        # Log how many were recorded
        print(f"  [S] Recorded {len(stories)} rejected patterns to cache (US-771)")
        return 0

    except Exception as e:
        print(f"  [S] WARNING: Failed to record rejected patterns: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
