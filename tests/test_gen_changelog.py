"""Tests for lib/gen_changelog.py — Phase G changelog generation.

Verifies:
- AC1: git-cliff binary validation via SPIRAL_GIT_CLIFF_BIN
- AC2: CHANGELOG.md generation with feat/fix/docs/refactor sections
- AC3: Orphan commit detection and warning log
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from lib.gen_changelog import (
    STORY_ID_PATTERN,
    find_orphan_commits,
    run,
    validate_git_cliff,
    write_orphan_warnings,
)


# ── AC1: Binary validation tests ────────────────────────────────────────────


class TestAC1BinaryValidation:
    """AC1: gen_changelog validates git-cliff binary exists via SPIRAL_GIT_CLIFF_BIN."""

    def test_validate_git_cliff_returns_false_for_missing_binary(self) -> None:
        """Returns False when binary does not exist."""
        assert validate_git_cliff("/nonexistent/git-cliff-fake") is False

    def test_validate_git_cliff_returns_false_on_timeout(self) -> None:
        """Returns False when binary check times out."""
        with patch(
            "lib.gen_changelog.subprocess.run",
            side_effect=subprocess.TimeoutExpired("cmd", 10),
        ):
            assert validate_git_cliff("git-cliff") is False

    def test_run_fails_when_binary_not_found(self, tmp_path: Path) -> None:
        """run() returns 1 when git-cliff binary is missing."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")

        result = run(
            spiral_home=str(tmp_path),
            cliff_bin="/nonexistent/git-cliff-fake",
        )
        assert result == 1

    def test_run_fails_when_cliff_toml_missing(self, tmp_path: Path) -> None:
        """run() returns 1 when cliff.toml is not found."""
        with patch("lib.gen_changelog.validate_git_cliff", return_value=True):
            result = run(spiral_home=str(tmp_path), cliff_bin="git-cliff")
        assert result == 1

    def test_run_uses_spiral_git_cliff_bin_env(self, tmp_path: Path) -> None:
        """run() reads SPIRAL_GIT_CLIFF_BIN from environment."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")

        with patch.dict(os.environ, {"SPIRAL_GIT_CLIFF_BIN": "/custom/git-cliff"}):
            with patch("lib.gen_changelog.validate_git_cliff", return_value=False):
                result = run(spiral_home=str(tmp_path))

        assert result == 1


# ── AC2: CHANGELOG.md generation tests ──────────────────────────────────────


class TestAC2ChangelogGeneration:
    """AC2: CHANGELOG.md generated with sections for feat/fix/docs/refactor."""

    def test_run_generates_changelog(self, tmp_path: Path) -> None:
        """run() creates CHANGELOG.md when git-cliff succeeds."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")
        (tmp_path / ".spiral").mkdir()

        def fake_generate(
            cliff_bin: str, cliff_config: str, output_file: str
        ) -> bool:
            Path(output_file).write_text(
                "# Changelog\n\n## [Unreleased]\n\n"
                "### Features\n- **US-100**: Add feature (abc1234)\n\n"
                "### Bug Fixes\n- **US-101**: Fix bug (def5678)\n\n"
                "### Documentation\n- **US-102**: Update docs (ghi9012)\n\n"
                "### Refactoring\n- **US-103**: Refactor code (jkl3456)\n",
                encoding="utf-8",
            )
            return True

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch(
                "lib.gen_changelog.generate_changelog", side_effect=fake_generate
            ),
            patch("lib.gen_changelog.find_orphan_commits", return_value=[]),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 0
        changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "Features" in changelog
        assert "Bug Fixes" in changelog
        assert "Documentation" in changelog
        assert "Refactoring" in changelog

    def test_run_fails_when_changelog_not_created(self, tmp_path: Path) -> None:
        """run() returns 1 when git-cliff fails to create CHANGELOG.md."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch("lib.gen_changelog.generate_changelog", return_value=False),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 1

    def test_changelog_contains_commit_hashes_and_messages(
        self, tmp_path: Path
    ) -> None:
        """CHANGELOG.md entries include commit hashes and messages."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")
        (tmp_path / ".spiral").mkdir()

        def fake_generate(
            cliff_bin: str, cliff_config: str, output_file: str
        ) -> bool:
            Path(output_file).write_text(
                "# Changelog\n\n### Features\n"
                "- **US-100**: Add new login flow (abc1234)\n"
                "- **US-101**: Implement dashboard (def5678)\n",
                encoding="utf-8",
            )
            return True

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch(
                "lib.gen_changelog.generate_changelog", side_effect=fake_generate
            ),
            patch("lib.gen_changelog.find_orphan_commits", return_value=[]),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 0
        changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "abc1234" in changelog
        assert "def5678" in changelog
        assert "Add new login flow" in changelog

    def test_changelog_groups_by_story_id(self, tmp_path: Path) -> None:
        """CHANGELOG.md shows story IDs as scope prefixes for grouping."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")
        (tmp_path / ".spiral").mkdir()

        def fake_generate(
            cliff_bin: str, cliff_config: str, output_file: str
        ) -> bool:
            Path(output_file).write_text(
                "# Changelog\n\n### Features\n"
                "- **US-042**: Add batch size config (abc1234)\n"
                "- **US-042**: Add batch size validation (abc5678)\n"
                "- **US-043**: Add cost ceiling (def1234)\n",
                encoding="utf-8",
            )
            return True

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch(
                "lib.gen_changelog.generate_changelog", side_effect=fake_generate
            ),
            patch("lib.gen_changelog.find_orphan_commits", return_value=[]),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 0
        changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "**US-042**" in changelog
        assert "**US-043**" in changelog


# ── AC3: Orphan commit detection tests ──────────────────────────────────────


class TestAC3OrphanCommitDetection:
    """AC3: Orphan commits logged to .spiral/phase_g_warnings.log."""

    def test_story_id_pattern_matches_us_prefix(self) -> None:
        """Pattern matches US-NNN story IDs."""
        assert STORY_ID_PATTERN.search("Story ID: US-100") is not None
        assert STORY_ID_PATTERN.search("feat: US-42 add feature") is not None

    def test_story_id_pattern_matches_ut_prefix(self) -> None:
        """Pattern matches UT-NNN story IDs."""
        assert STORY_ID_PATTERN.search("Story ID: UT-200") is not None
        assert STORY_ID_PATTERN.search("test: UT-1 add test") is not None

    def test_story_id_pattern_no_match_for_orphan(self) -> None:
        """Pattern does not match commits without story IDs."""
        assert STORY_ID_PATTERN.search("feat: add feature") is None
        assert STORY_ID_PATTERN.search("fix: random bugfix") is None

    def test_write_orphan_warnings_creates_file(self, tmp_path: Path) -> None:
        """write_orphan_warnings creates the warnings log file."""
        warnings_file = str(tmp_path / ".spiral" / "phase_g_warnings.log")
        orphans = [
            {"hash": "abc1234", "subject": "fix: random fix"},
            {"hash": "def5678", "subject": "docs: orphan doc update"},
        ]

        write_orphan_warnings(orphans, warnings_file)

        log_path = Path(warnings_file)
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "abc1234 fix: random fix" in content
        assert "def5678 docs: orphan doc update" in content

    def test_write_orphan_warnings_creates_parent_dirs(
        self, tmp_path: Path
    ) -> None:
        """write_orphan_warnings creates parent directories if needed."""
        warnings_file = str(tmp_path / "deep" / "nested" / "warnings.log")
        write_orphan_warnings(
            [{"hash": "abc", "subject": "test"}], warnings_file
        )
        assert Path(warnings_file).exists()

    def test_run_logs_orphan_commits(self, tmp_path: Path) -> None:
        """run() logs orphan commits to .spiral/phase_g_warnings.log."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")
        (tmp_path / ".spiral").mkdir()

        orphans = [
            {
                "hash": "abc1234",
                "subject": "fix: random fix without story id",
            },
            {
                "hash": "def5678",
                "subject": "docs: orphan documentation update",
            },
        ]

        def fake_generate(
            cliff_bin: str, cliff_config: str, output_file: str
        ) -> bool:
            Path(output_file).write_text("# Changelog\n", encoding="utf-8")
            return True

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch(
                "lib.gen_changelog.generate_changelog", side_effect=fake_generate
            ),
            patch(
                "lib.gen_changelog.find_orphan_commits", return_value=orphans
            ),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 0
        warnings_file = tmp_path / ".spiral" / "phase_g_warnings.log"
        assert warnings_file.exists()
        content = warnings_file.read_text(encoding="utf-8")
        assert "random fix without story id" in content
        assert "orphan documentation update" in content

    def test_run_reports_no_orphans_when_all_have_ids(
        self, tmp_path: Path
    ) -> None:
        """run() succeeds when no orphan commits found."""
        (tmp_path / "cliff.toml").write_text("[changelog]\n", encoding="utf-8")
        (tmp_path / ".spiral").mkdir()

        def fake_generate(
            cliff_bin: str, cliff_config: str, output_file: str
        ) -> bool:
            Path(output_file).write_text("# Changelog\n", encoding="utf-8")
            return True

        with (
            patch("lib.gen_changelog.validate_git_cliff", return_value=True),
            patch(
                "lib.gen_changelog.generate_changelog", side_effect=fake_generate
            ),
            patch("lib.gen_changelog.find_orphan_commits", return_value=[]),
        ):
            result = run(spiral_home=str(tmp_path))

        assert result == 0

    def test_find_orphan_commits_with_mock_git(self) -> None:
        """find_orphan_commits identifies orphan commits from git log."""
        git_log_output = (
            "abc1234hash feat: add feature\ndef5678hash fix: random fix\n"
        )
        us_body = "feat: add feature\n\nStory ID: US-100\n"
        orphan_body = "fix: random fix\n"

        def mock_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["git", "log"] and "--format=%H %s" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=git_log_output, stderr=""
                )
            if cmd[:2] == ["git", "log"] and "--format=%B" in cmd:
                commit = cmd[-1] if len(cmd) > 3 else ""
                if commit.startswith("abc"):
                    return subprocess.CompletedProcess(
                        cmd, 0, stdout=us_body, stderr=""
                    )
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=orphan_body, stderr=""
                )
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="error"
            )

        with patch(
            "lib.gen_changelog.subprocess.run", side_effect=mock_run
        ):
            orphans = find_orphan_commits("/fake/repo")

        assert len(orphans) == 1
        assert orphans[0]["hash"] == "def5678"
        assert orphans[0]["subject"] == "fix: random fix"
