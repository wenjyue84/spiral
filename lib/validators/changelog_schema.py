"""lib/validators/changelog_schema.py — Keep-a-Changelog schema validator.

Validates CHANGELOG.md files for Keep-a-Changelog compliance and checks
semantic version increments based on story complexity scores.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Semver bump rules
CRITICAL_SCORE_THRESHOLD = 5  # Stories with score >= critical
MAJOR_BUMP_CRITICAL_COUNT = 5  # Major if > 5 critical stories
MINOR_BUMP_TOTAL_COUNT = 10  # Minor if > 10 total stories

# Keep-a-Changelog pattern: starts with # Changelog, then ## [version]
CHANGELOG_PATTERN = re.compile(r"^\s*#\s+Changelog", re.MULTILINE)
VERSION_HEADER_PATTERN = re.compile(r"^##\s+\[\d+\.\d+\.\d+\]", re.MULTILINE)
UNRELEASED_SECTION_PATTERN = re.compile(r"^##\s+\[?Unreleased\]?", re.MULTILINE)


def validate_changelog_format(path: str) -> bool:
    """Check a CHANGELOG.md file for Keep-a-Changelog compliance.

    Validates:
    - File exists and is readable
    - Contains "# Changelog" heading
    - Contains at least one version header (## [X.Y.Z] or ## Unreleased)
    - Has standard sections (Added, Changed, Deprecated, Removed, Fixed, Security)

    Args:
        path: Path to CHANGELOG.md file

    Returns:
        True if CHANGELOG.md conforms to Keep-a-Changelog, False otherwise
    """
    p = Path(path)

    # Check file exists
    if not p.exists():
        return False

    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    # Must start with # Changelog heading
    if not CHANGELOG_PATTERN.search(content):
        return False

    # Must have at least one version header or Unreleased section
    has_version_header = VERSION_HEADER_PATTERN.search(content) is not None
    has_unreleased = UNRELEASED_SECTION_PATTERN.search(content) is not None

    if not (has_version_header or has_unreleased):
        return False

    # Should have at least one standard section (case-insensitive)
    standard_sections = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
    has_section = any(
        re.search(rf"^###\s+{section}", content, re.MULTILINE | re.IGNORECASE) for section in standard_sections
    )

    return has_section


def validate_version_incrementing(old_ver: str, new_ver: str, scores: list[dict[str, Any]]) -> bool:
    """Verify semantic version increment is correct based on story complexity.

    Semver bump rules:
    - Major: if > 5 stories have complexity_score >= critical threshold (5)
    - Minor: if > 10 total stories
    - Patch: otherwise

    Args:
        old_ver: Previous version (e.g., "1.2.3")
        new_ver: New version (e.g., "2.0.0")
        scores: List of story dicts with 'complexity_score' key

    Returns:
        True if version increment is correct for given complexity, False otherwise
    """
    # Parse versions
    try:
        old_parts = [int(x) for x in old_ver.split(".")]
        new_parts = [int(x) for x in new_ver.split(".")]
        if len(old_parts) != 3 or len(new_parts) != 3:
            return False
    except (ValueError, AttributeError):
        return False

    # Count stories by complexity
    critical_count = sum(1 for s in scores if s.get("complexity_score", 0) >= CRITICAL_SCORE_THRESHOLD)
    total_count = len(scores)

    # Determine expected bump type
    if critical_count > MAJOR_BUMP_CRITICAL_COUNT:
        # Major bump expected
        expected_major = old_parts[0] + 1
        if new_parts[0] != expected_major or new_parts[1] != 0 or new_parts[2] != 0:
            return False
    elif total_count > MINOR_BUMP_TOTAL_COUNT:
        # Minor bump expected
        expected_minor = old_parts[1] + 1
        if new_parts[0] != old_parts[0] or new_parts[1] != expected_minor or new_parts[2] != 0:
            return False
    else:
        # Patch bump expected
        expected_patch = old_parts[2] + 1
        if new_parts[0] != old_parts[0] or new_parts[1] != old_parts[1] or new_parts[2] != expected_patch:
            return False

    return True
