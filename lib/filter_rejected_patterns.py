"""lib/filter_rejected_patterns.py — Filter Phase A candidates by rejected patterns (US-771).

Called from Phase A to remove candidates matching previously rejected patterns.
Reduces API calls and validation cycles when re-suggesting similar stories.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(args: list[str] | None = None) -> int:
    """Filter candidates by rejected pattern cache.

    Args:
        args: Command-line arguments (for testing)

    Returns:
        0 on success, 1 on error
    """
    parser = argparse.ArgumentParser(
        description="Filter Phase A candidates to skip rejected patterns (US-771)"
    )
    parser.add_argument("--candidates", required=True, help="Path to candidate JSON file")
    parser.add_argument("--cache", required=True, help="Path to rejected_patterns.json cache")
    parser.add_argument("--output", required=True, help="Path to write filtered candidates")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Similarity threshold (0-1) for skipping (default: 0.8)",
    )

    parsed = parser.parse_args(args)

    try:
        # Import after arg parsing
        from lib.rejected_pattern_cache import (
            filter_candidates_by_rejected_patterns,
        )

        candidates_path = Path(parsed.candidates)
        cache_path = Path(parsed.cache)
        output_path = Path(parsed.output)

        if not candidates_path.exists():
            return 0  # No candidates, nothing to do

        # Load candidates
        with open(candidates_path, "r", encoding="utf-8") as f:
            candidates_data = json.load(f)

        # Handle both list and dict with "stories" field
        if isinstance(candidates_data, list):
            candidates = candidates_data
        else:
            candidates = candidates_data.get("stories", [])

        if not candidates:
            # No candidates, write empty output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"stories": []}, f, indent=2)
            return 0

        # Filter by rejected patterns
        kept, skipped = filter_candidates_by_rejected_patterns(
            candidates, cache_path, similarity_threshold=parsed.threshold
        )

        # Write filtered output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {"stories": kept}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)

        # Log results
        if skipped:
            print(
                f"  [A] Filtered {len(skipped)} candidates matching rejected patterns (US-771)",
                file=sys.stderr,
            )
            for story_id, reason in skipped.items():
                print(f"    → {story_id}: {reason}", file=sys.stderr)

        return 0

    except Exception as e:
        print(f"  [A] WARNING: Failed to filter by rejected patterns: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
