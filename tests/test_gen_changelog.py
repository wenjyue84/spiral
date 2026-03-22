"""Integration tests for lib/gen_changelog.py — Phase G changelog generation.

Covers:
- STORY_ID_PATTERN: parsing commit messages for US-NNN/UT-NNN story IDs
- find_orphan_commits: detects commits without story IDs (AC3: warning emitted)
- write_orphan_warnings: logs orphan commits to a warnings file
- generate_changelog: produces CHANGELOG.md with conventional-commit section headers (AC2)
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib.gen_changelog import (
    STORY_ID_PATTERN,
    find_orphan_commits,
    generate_changelog,
    write_orphan_warnings,
)

# ── STORY_ID_PATTERN ──────────────────────────────────────────────────────────


def test_pattern_matches_us_id() -> None:
    """STORY_ID_PATTERN matches US-NNN story IDs in commit messages."""
    assert STORY_ID_PATTERN.search("feat: add feature\n\nStory ID: US-123") is not None


def test_pattern_matches_ut_id() -> None:
    """STORY_ID_PATTERN matches UT-NNN test IDs in commit messages."""
    assert STORY_ID_PATTERN.search("test: add test case\n\nUT-456 coverage") is not None


def test_pattern_no_match_plain_commit() -> None:
    """STORY_ID_PATTERN returns None for commits without any story ID tag."""
    assert STORY_ID_PATTERN.search("chore: update dependencies") is None


# ── find_orphan_commits ───────────────────────────────────────────────────────

_HASH_WITH_ID = "a" * 40
_HASH_ORPHAN = "b" * 40


def _make_git_run(log_output: str, body_map: dict[str, str]) -> object:
    """Return a side-effect callable for subprocess.run that fakes git log output."""

    def _side_effect(cmd: list[str], **kwargs: object) -> MagicMock:
        m: MagicMock = MagicMock()
        m.returncode = 0
        m.stdout = ""
        if "--format=%H %s" in cmd:
            m.stdout = log_output
        else:
            for h, body in body_map.items():
                if h in cmd:
                    m.stdout = body
                    break
        return m

    return _side_effect


def test_find_orphan_commits_detects_missing_story_id(tmp_path: Path) -> None:
    """find_orphan_commits returns commits without US-NNN/UT-NNN — these would emit a warning (AC3)."""
    log = f"{_HASH_WITH_ID} feat: add feature\n{_HASH_ORPHAN} chore: update deps\n"
    bodies = {
        _HASH_WITH_ID: "feat: add feature\n\nStory ID: US-100\n",
        _HASH_ORPHAN: "chore: update deps\n",
    }
    with patch("lib.gen_changelog.subprocess.run", side_effect=_make_git_run(log, bodies)):
        orphans = find_orphan_commits(str(tmp_path))

    assert len(orphans) == 1
    assert orphans[0]["subject"] == "chore: update deps"
    assert orphans[0]["hash"] == _HASH_ORPHAN[:7]


def test_find_orphan_commits_empty_when_all_have_story_ids(tmp_path: Path) -> None:
    """find_orphan_commits returns empty list when every commit carries a story ID."""
    log = f"{_HASH_WITH_ID} feat: add feature\n"
    bodies = {_HASH_WITH_ID: "feat: add feature\n\nStory ID: US-200\n"}
    with patch("lib.gen_changelog.subprocess.run", side_effect=_make_git_run(log, bodies)):
        orphans = find_orphan_commits(str(tmp_path))

    assert orphans == []


# ── write_orphan_warnings ─────────────────────────────────────────────────────


def test_write_orphan_warnings_creates_file_with_entries(tmp_path: Path) -> None:
    """write_orphan_warnings writes hash+subject lines for each orphan commit."""
    orphans = [
        {"hash": "abc1234", "subject": "chore: no story id"},
        {"hash": "def5678", "subject": "fix: random maintenance"},
    ]
    wf = str(tmp_path / ".spiral" / "phase_g_warnings.log")
    write_orphan_warnings(orphans, wf)
    content = Path(wf).read_text(encoding="utf-8")
    assert "abc1234 chore: no story id" in content
    assert "def5678 fix: random maintenance" in content


# ── generate_changelog ────────────────────────────────────────────────────────


def test_generate_changelog_markdown_contains_section_headers(tmp_path: Path) -> None:
    """generate_changelog produces CHANGELOG.md with conventional-commit section headers (AC2)."""
    output_file = tmp_path / "CHANGELOG.md"
    changelog_content = textwrap.dedent(
        """\
        # Changelog

        ## [Unreleased]

        ### feat
        - add new feature (abc1234) Story ID: US-100

        ### fix
        - resolve bug (def5678) Story ID: US-101

        ### docs
        - update readme (ghi9012) Story ID: US-102

        ### refactor
        - clean up code (jkl3456) Story ID: US-103
        """
    )

    def fake_cliff(cmd: list[str], **kwargs: object) -> MagicMock:
        output_file.write_text(changelog_content, encoding="utf-8")
        m: MagicMock = MagicMock()
        m.returncode = 0
        return m

    with patch("lib.gen_changelog.subprocess.run", side_effect=fake_cliff):
        ok = generate_changelog("git-cliff", str(tmp_path / "cliff.toml"), str(output_file))

    assert ok is True
    md = output_file.read_text(encoding="utf-8")
    # AC2: assert section headers for conventional-commit types
    assert "### feat" in md
    assert "### fix" in md
    assert "### docs" in md
    assert "### refactor" in md
