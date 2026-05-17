"""lib/impl/scope_reducer.py — Strip @optional-tagged acceptance criteria from a story.

Used by timeout_handler.py to reduce story scope when a story times out,
allowing a retry attempt with fewer required acceptance criteria.
"""

import copy


def strip_optional_ac(story_obj: dict[str, object]) -> dict[str, object]:
    """Return a copy of story_obj with @optional-prefixed ACs removed.

    ACs are matched by the literal prefix '@optional' (case-sensitive).
    Non-optional ACs and all other story fields are preserved unchanged.

    Args:
        story_obj: A story dict (as found in prd.json userStories).

    Returns:
        A deep-copied story dict with @optional ACs removed.
    """
    result: dict[str, object] = copy.deepcopy(story_obj)
    acs = result.get("acceptanceCriteria", [])
    if isinstance(acs, list):
        result["acceptanceCriteria"] = [ac for ac in acs if not (isinstance(ac, str) and ac.startswith("@optional"))]
    return result
