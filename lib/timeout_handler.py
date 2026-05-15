"""lib/timeout_handler.py — Timeout-based story scope reducer.

Provides timeout_scope_reducer() which strips @optional acceptance criteria
from a story dict so the story can be retried with reduced scope after a
timeout failure.

CLI usage (called by lib/impl/retry.sh):
    python lib/timeout_handler.py <story_json_file>
    Outputs the temp file path to stdout if optional ACs were stripped.
    Exits with code 1 if no optional ACs were found (no temp file written).
"""

import json
import os
import sys
import tempfile
from typing import cast

sys.path.insert(0, os.path.dirname(__file__))

from impl.scope_reducer import strip_optional_ac


def timeout_scope_reducer(story_id: str, story_obj: dict[str, object]) -> dict[str, object]:
    """Strip @optional ACs from story_obj and return reduced story dict.

    Delegates to strip_optional_ac() in lib/impl/scope_reducer.py.

    Args:
        story_id: The story identifier (e.g. 'US-1329'). Used for logging only.
        story_obj: A story dict (as found in prd.json userStories).

    Returns:
        A deep-copied story dict with @optional ACs removed, ready for retry.
    """
    _ = story_id  # reserved for future logging
    return cast(dict[str, object], strip_optional_ac(story_obj))


def reduce_story_for_timeout(story_file: str) -> str:
    """Read story from JSON file, strip @optional ACs, write reduced story to temp file.

    Used by lib/impl/retry.sh try_timeout_scope_reduction() to produce a
    reduced story file before calling decompose_story().

    Args:
        story_file: Path to a JSON file containing a single story dict.

    Returns:
        Path to a temp file with the reduced story, or '' if no optional ACs
        were found (caller should fall through to decompose_story unchanged).
    """
    with open(story_file, encoding="utf-8") as fh:
        story = cast(dict[str, object], json.load(fh))

    story_id = str(story.get("id", "unknown"))
    reduced = timeout_scope_reducer(story_id, story)

    orig_acs = story.get("acceptanceCriteria", [])
    reduced_acs = reduced.get("acceptanceCriteria", [])
    if isinstance(orig_acs, list) and isinstance(reduced_acs, list) and len(reduced_acs) < len(orig_acs):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(reduced, tmp, ensure_ascii=False)
            return tmp.name

    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: timeout_handler.py <story_json_file>", file=sys.stderr)
        sys.exit(1)
    result = reduce_story_for_timeout(sys.argv[1])
    print(result)
    sys.exit(0 if result else 1)
