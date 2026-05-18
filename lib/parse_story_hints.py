"""Parse @spiral:* markers from story descriptions.

Supported markers:
  @spiral:hint-complexity-band:small
  @spiral:hint-complexity-band:medium
  @spiral:hint-complexity-band:large
"""

import re

VALID_BANDS = ("small", "medium", "large")
_BAND_PATTERN = re.compile(r"@spiral:hint-complexity-band:(small|medium|large)", re.IGNORECASE)

_BAND_GUIDANCE: dict[str, str] = {
    "small": (
        "This story is hinted as SMALL scope. Each sub-story should be completable in "
        "under 10 minutes with 1-2 file changes max. Prefer 2 sub-stories."
    ),
    "medium": (
        "This story is hinted as MEDIUM scope. Sub-stories can touch 2-3 files each. "
        "Prefer 3 sub-stories with clear boundaries."
    ),
    "large": (
        "This story is hinted as LARGE scope. Decompose aggressively into 4 sub-stories, "
        "each independently testable. Minimize cross-dependencies between sub-stories."
    ),
}


def extract_complexity_band(text: str) -> str | None:
    """Extract @spiral:hint-complexity-band value from text.

    Returns the band ('small', 'medium', 'large') or None if not found.
    """
    match = _BAND_PATTERN.search(text)
    if match:
        return match.group(1).lower()
    return None


def build_hint_context(band: str) -> str:
    """Build a prompt section for the given complexity band hint.

    Returns empty string if band is invalid.
    """
    guidance = _BAND_GUIDANCE.get(band)
    if not guidance:
        return ""
    return f"\n<complexity_hint band=\"{band}\">\n{guidance}\n</complexity_hint>\n"
