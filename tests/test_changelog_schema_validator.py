"""Integration tests for lib/validators/changelog_schema.py.

Covers:
- validate_changelog_format: Keep-a-Changelog compliance (AC1)
- validate_version_incrementing: Semantic version bump logic (AC2)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from lib.validators.changelog_schema import (
    validate_changelog_format,
    validate_version_incrementing,
)

# ─ test_changelog_schema_compliance ──────────────────────────────────────


def test_changelog_schema_compliance_well_formed(tmp_path: Path) -> None:
    """validate_changelog_format returns True for a well-formed CHANGELOG.md (AC1)."""
    changelog_content = textwrap.dedent(
        """\
        # Changelog

        All notable changes to this project will be documented in this file.

        The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
        and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

        ## [Unreleased]

        ### Added
        - New feature for X
        - New feature for Y

        ### Fixed
        - Bug fix for issue #123
        - Bug fix for issue #456

        ### Security
        - Patched SQL injection vulnerability

        ## [1.2.3] - 2026-03-20

        ### Changed
        - Updated dependency to latest version

        ### Deprecated
        - Old function will be removed in v2.0.0

        ### Removed
        - Removed deprecated config option
        """
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_content, encoding="utf-8")

    result = validate_changelog_format(str(changelog_path))
    assert result is True


def test_changelog_schema_compliance_missing_heading(tmp_path: Path) -> None:
    """validate_changelog_format returns False if # Changelog heading is missing."""
    changelog_content = textwrap.dedent(
        """\
        ## [Unreleased]

        ### Added
        - Some feature
        """
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_content, encoding="utf-8")

    result = validate_changelog_format(str(changelog_path))
    assert result is False


def test_changelog_schema_compliance_missing_version_header(tmp_path: Path) -> None:
    """validate_changelog_format returns False if no version headers exist."""
    changelog_content = textwrap.dedent(
        """\
        # Changelog

        ### Added
        - Some feature
        """
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_content, encoding="utf-8")

    result = validate_changelog_format(str(changelog_path))
    assert result is False


def test_changelog_schema_compliance_missing_sections(tmp_path: Path) -> None:
    """validate_changelog_format returns False if no standard sections exist."""
    changelog_content = textwrap.dedent(
        """\
        # Changelog

        ## [Unreleased]

        Some arbitrary text without standard sections.
        """
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_content, encoding="utf-8")

    result = validate_changelog_format(str(changelog_path))
    assert result is False


def test_changelog_schema_compliance_file_not_found(tmp_path: Path) -> None:
    """validate_changelog_format returns False if file does not exist."""
    changelog_path = tmp_path / "NONEXISTENT.md"
    result = validate_changelog_format(str(changelog_path))
    assert result is False


def test_changelog_schema_compliance_case_insensitive_sections(tmp_path: Path) -> None:
    """validate_changelog_format recognizes standard sections case-insensitively."""
    changelog_content = textwrap.dedent(
        """\
        # Changelog

        ## [Unreleased]

        ### added
        - Feature in lowercase

        ### FIXED
        - Bug fix in uppercase
        """
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(changelog_content, encoding="utf-8")

    result = validate_changelog_format(str(changelog_path))
    assert result is True


# ─ test_semver_bump_logic ────────────────────────────────────────────────


def test_semver_bump_logic_major_bump(tmp_path: Path) -> None:
    """validate_version_incrementing returns True for major bump when >5 critical stories (AC2)."""
    # 6 stories with critical score (>= 5), so major bump expected: 1.2.3 -> 2.0.0
    scores = [
        {"complexity_score": 5},
        {"complexity_score": 6},
        {"complexity_score": 7},
        {"complexity_score": 8},
        {"complexity_score": 9},
        {"complexity_score": 10},
    ]

    result = validate_version_incrementing("1.2.3", "2.0.0", scores)
    assert result is True


def test_semver_bump_logic_major_bump_incorrect_version(tmp_path: Path) -> None:
    """validate_version_incrementing returns False if major bump expected but minor given."""
    # 6 critical stories, expecting 2.0.0, but 1.3.0 given
    scores = [
        {"complexity_score": 5},
        {"complexity_score": 6},
        {"complexity_score": 7},
        {"complexity_score": 8},
        {"complexity_score": 9},
        {"complexity_score": 10},
    ]

    result = validate_version_incrementing("1.2.3", "1.3.0", scores)
    assert result is False


def test_semver_bump_logic_minor_bump(tmp_path: Path) -> None:
    """validate_version_incrementing returns True for minor bump when >10 total stories."""
    # 11 stories, no critical ones, so minor bump expected: 1.2.3 -> 1.3.0
    scores = [
        {"complexity_score": 2},
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 3},
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 3},
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 2},
        {"complexity_score": 1},
    ]

    result = validate_version_incrementing("1.2.3", "1.3.0", scores)
    assert result is True


def test_semver_bump_logic_patch_bump(tmp_path: Path) -> None:
    """validate_version_incrementing returns True for patch bump with <=10 stories and no critical."""
    # 5 stories, all low complexity, so patch bump expected: 1.2.3 -> 1.2.4
    scores = [
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 1},
    ]

    result = validate_version_incrementing("1.2.3", "1.2.4", scores)
    assert result is True


def test_semver_bump_logic_patch_bump_incorrect_version(tmp_path: Path) -> None:
    """validate_version_incrementing returns False if patch bump expected but minor given."""
    # 5 stories, expecting 1.2.4, but 1.3.0 given
    scores = [
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 1},
        {"complexity_score": 2},
        {"complexity_score": 1},
    ]

    result = validate_version_incrementing("1.2.3", "1.3.0", scores)
    assert result is False


def test_semver_bump_logic_invalid_old_version(tmp_path: Path) -> None:
    """validate_version_incrementing returns False for invalid old_ver format."""
    scores = [{"complexity_score": 1}]

    result = validate_version_incrementing("1.2", "1.2.1", scores)
    assert result is False


def test_semver_bump_logic_invalid_new_version(tmp_path: Path) -> None:
    """validate_version_incrementing returns False for invalid new_ver format."""
    scores = [{"complexity_score": 1}]

    result = validate_version_incrementing("1.2.3", "1.2", scores)
    assert result is False


def test_semver_bump_logic_empty_scores(tmp_path: Path) -> None:
    """validate_version_incrementing handles empty scores list (patch bump expected)."""
    scores: list[dict[str, int]] = []

    # Empty list means 0 stories, patch bump expected
    result = validate_version_incrementing("1.2.3", "1.2.4", scores)
    assert result is True


def test_semver_bump_logic_scores_at_threshold(tmp_path: Path) -> None:
    """validate_version_incrementing correctly handles boundary cases."""
    # Exactly 5 critical stories (boundary: >5 means major), so patch expected
    scores = [
        {"complexity_score": 5},
        {"complexity_score": 5},
        {"complexity_score": 5},
        {"complexity_score": 5},
        {"complexity_score": 5},
    ]

    # 5 critical is NOT > 5, so patch bump expected: 1.2.3 -> 1.2.4
    result = validate_version_incrementing("1.2.3", "1.2.4", scores)
    assert result is True


def test_semver_bump_logic_missing_complexity_score_key(tmp_path: Path) -> None:
    """validate_version_incrementing treats missing complexity_score as 0."""
    # 2 stories without complexity_score key, treated as 0, patch expected
    scores = [{"id": "US-1"}, {"id": "US-2"}]

    result = validate_version_incrementing("1.2.3", "1.2.4", scores)
    assert result is True
