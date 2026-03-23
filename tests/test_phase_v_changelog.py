"""tests/test_phase_v_changelog.py — Phase V CHANGELOG validation tests.

Covers:
- AC1: validate_changelog_stories uses Keep-a-Changelog format check
- AC2: story IDs in CHANGELOG must exist in prd.json with passes=True
- AC3: find_orphan_commits detects commits referencing incomplete stories
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.phases.phase_v import (
    extract_story_ids,
    find_orphan_commits,
    validate_changelog_stories,
)

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

_VALID_CHANGELOG = """\
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Implemented US-100 feature
- Implemented US-101 fix
"""

_PRD: dict = {
    "userStories": [
        {"id": "US-100", "passes": True},
        {"id": "US-101", "passes": True},
        {"id": "US-102", "passes": False},
    ]
}


def _write_changelog(tmp_path: Path, content: str = _VALID_CHANGELOG) -> str:
    p = tmp_path / "CHANGELOG.md"
    p.write_text(content)
    return str(p)


def _write_prd(tmp_path: Path, data: dict = _PRD) -> str:
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(data))
    return str(p)


# ---------------------------------------------------------------------------
# extract_story_ids
# ---------------------------------------------------------------------------


def test_extract_ids_finds_us_ids(tmp_path: Path) -> None:
    cl = _write_changelog(tmp_path)
    ids = extract_story_ids(cl)
    assert "US-100" in ids
    assert "US-101" in ids


def test_extract_ids_empty_for_missing_file(tmp_path: Path) -> None:
    assert extract_story_ids(str(tmp_path / "MISSING.md")) == []


def test_extract_ids_deduplicates(tmp_path: Path) -> None:
    cl = _write_changelog(tmp_path, _VALID_CHANGELOG + "\n- US-100 again\n")
    ids = extract_story_ids(cl)
    assert ids.count("US-100") == 1


# ---------------------------------------------------------------------------
# validate_changelog_stories  (AC1 + AC2)
# ---------------------------------------------------------------------------


def test_validate_all_complete_returns_ok(tmp_path: Path) -> None:
    """AC1+AC2: valid format + all IDs completed → ok=True."""
    cl = _write_changelog(tmp_path)
    prd = _write_prd(tmp_path)
    result = validate_changelog_stories(cl, prd)
    assert result["ok"] is True
    assert result["orphan_ids"] == []


def test_validate_bad_format_fails(tmp_path: Path) -> None:
    """AC1: non-Keep-a-Changelog content → ok=False."""
    cl = _write_changelog(tmp_path, "no heading\n- US-100\n")
    prd = _write_prd(tmp_path)
    result = validate_changelog_stories(cl, prd)
    assert result["ok"] is False
    assert "format" in result["errors"][0].lower()


def test_validate_orphan_id_not_in_prd(tmp_path: Path) -> None:
    """AC2: story ID not in prd.json → orphan_ids contains it."""
    cl = _write_changelog(tmp_path, _VALID_CHANGELOG.replace("US-101", "US-999"))
    prd = _write_prd(tmp_path)
    result = validate_changelog_stories(cl, prd)
    assert result["ok"] is False
    assert "US-999" in result["orphan_ids"]


def test_validate_incomplete_story_is_orphan(tmp_path: Path) -> None:
    """AC2: ID in prd.json but passes=False → treated as orphan."""
    cl = _write_changelog(tmp_path, _VALID_CHANGELOG.replace("US-101", "US-102"))
    prd = _write_prd(tmp_path)
    result = validate_changelog_stories(cl, prd)
    assert result["ok"] is False
    assert "US-102" in result["orphan_ids"]


# ---------------------------------------------------------------------------
# find_orphan_commits  (AC3)
# ---------------------------------------------------------------------------


def _mock_git(stdout: str) -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    return m


def test_find_orphan_commits_none_when_all_complete(tmp_path: Path) -> None:
    """AC3: commits only referencing completed IDs → no orphans."""
    prd = _write_prd(tmp_path)
    log = "abc1234 feat: US-100 implement\ndef5678 feat: US-101 fix\n"
    with patch("subprocess.run", return_value=_mock_git(log)):
        result = find_orphan_commits(prd)
    assert result == []


def test_find_orphan_commits_detects_incomplete_id(tmp_path: Path) -> None:
    """AC3: commit referencing US-999 (not in prd) → returned as orphan."""
    prd = _write_prd(tmp_path)
    log = "abc1234 feat: US-999 orphan\ndef5678 feat: US-100 ok\n"
    with patch("subprocess.run", return_value=_mock_git(log)):
        result = find_orphan_commits(prd)
    assert any("US-999" in line for line in result)
    assert all("US-100" not in line for line in result)


def test_find_orphan_commits_missing_prd(tmp_path: Path) -> None:
    """AC3: returns [] when prd.json is missing (graceful degradation)."""
    result = find_orphan_commits(str(tmp_path / "missing.json"))
    assert result == []
