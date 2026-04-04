"""Apply overflow guard to stories in PRD.

Reads prd.json, applies context overflow guard to each story,
updates prd.json with _context_trimmed field for trimmed stories.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from context.overflow_guard import guard_story_context


def main() -> int:
    """Apply overflow guard to all stories in PRD."""
    parser = argparse.ArgumentParser(description="Apply context overflow guard to PRD stories")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument(
        "--budget",
        type=int,
        default=180000,
        help="Token budget (default 180000)",
    )
    args = parser.parse_args()

    prd_path = Path(args.prd)

    # Read PRD
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error reading PRD: {e}", file=sys.stderr)
        return 1

    if "userStories" not in prd:
        print("No userStories found in PRD", file=sys.stderr)
        return 0

    # Apply guard to each story
    trimmed_count = 0
    for story in prd["userStories"]:
        guarded_story = guard_story_context(story, budget_tokens=args.budget)

        # Check if story was trimmed
        if guarded_story.get("_context_trimmed"):
            trimmed_count += 1
            story_id = story.get("id", "unknown")
            print(f"  [overflow-guard] Trimmed story {story_id}", file=sys.stderr)

        # Update story in PRD
        story.update(guarded_story)

    # Write updated PRD
    try:
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f, indent=2)
    except IOError as e:
        print(f"Error writing PRD: {e}", file=sys.stderr)
        return 1

    print(
        f"  [overflow-guard] Applied to {len(prd['userStories'])} stories ({trimmed_count} trimmed)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
