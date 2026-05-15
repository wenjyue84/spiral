"""lib/timeout_handler.py — Timeout-based story scope reducer.

Provides timeout_scope_reducer() which strips @optional acceptance criteria
from a story dict so the story can be retried with reduced scope after a
timeout failure.
"""

import sys
import os

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
    return strip_optional_ac(story_obj)
