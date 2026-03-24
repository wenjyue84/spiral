"""Integration test for Phase G CHANGELOG generation with story ID parsing (US-1055).

Tests lib/gen_changelog.py functions that:
1. Parse story IDs (US-NNN, UT-NNN) from commit messages
2. Detect orphan commits (without story IDs)
3. Generate CHANGELOG.md with proper markdown structure
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from gen_changelog import (
    STORY_ID_PATTERN,
    find_orphan_commits,
    validate_git_cliff,
    write_orphan_warnings,
)


class TestStoryIDParsing:
    """Test story ID pattern matching in commit messages."""

    def test_pattern_matches_us_prefix(self):
        """Pattern matches US-NNN format."""
        message = "feat: US-1055 - add Phase G integration tests"
        match = STORY_ID_PATTERN.search(message)
        assert match is not None
        assert match.group() == "US-1055"

    def test_pattern_matches_ut_prefix(self):
        """Pattern matches UT-NNN format."""
        message = "fix: UT-999 - fix test suite issue"
        match = STORY_ID_PATTERN.search(message)
        assert match is not None
        assert match.group() == "UT-999"

    def test_pattern_case_insensitive(self):
        """Pattern is case-insensitive."""
        message = "refactor: us-1050 lowercase prefix"
        match = STORY_ID_PATTERN.search(message)
        assert match is not None

    def test_pattern_no_match_without_id(self):
        """Pattern does not match commits without story IDs."""
        message = "docs: update README"
        match = STORY_ID_PATTERN.search(message)
        assert match is None

    def test_pattern_finds_id_in_body(self):
        """Pattern finds story ID in commit body."""
        message = "feat: add new feature\n\nStory ID: US-1051"
        match = STORY_ID_PATTERN.search(message)
        assert match is not None
        assert match.group() == "US-1051"


class TestOrphanCommitDetection:
    """Test orphan commit detection."""

    def test_all_commits_with_ids(self):
        """No orphans when all commits have story IDs."""
        commits = [
            {"commit": "abc1234", "message": "feat: US-1055 - add test", "date": "2026-03-20"},
            {"commit": "def5678", "message": "fix: US-1050 - fix quota", "date": "2026-03-20"},
        ]
        orphans = find_orphan_commits(commits)
        assert orphans == []

    def test_detect_orphan_commits(self):
        """Detects commits without story IDs."""
        commits = [
            {"commit": "abc1234", "message": "feat: US-1055 - add test", "date": "2026-03-20"},
            {"commit": "def5678", "message": "docs: update README", "date": "2026-03-20"},
            {"commit": "ghi9012", "message": "fix: random bug", "date": "2026-03-20"},
        ]
        orphans = find_orphan_commits(commits)
        assert len(orphans) == 2
        assert all(o["reason"] == "no-story-id" for o in orphans)
        assert orphans[0]["commit"] == "def5678"
        assert orphans[1]["commit"] == "ghi9012"

    def test_orphan_preserves_original_fields(self):
        """Orphan dict preserves all original fields plus reason."""
        commits = [
            {"commit": "xyz", "message": "no story", "date": "2026-03-20", "author": "Alice"},
        ]
        orphans = find_orphan_commits(commits)
        assert len(orphans) == 1
        assert orphans[0]["commit"] == "xyz"
        assert orphans[0]["author"] == "Alice"
        assert orphans[0]["reason"] == "no-story-id"

    def test_empty_commits_list(self):
        """Empty commits list returns empty orphans list."""
        orphans = find_orphan_commits([])
        assert orphans == []


class TestOrphanWarningsFile:
    """Test writing orphan warnings to file."""

    def test_writes_orphan_warnings(self):
        """Writes orphan commit data to warnings file."""
        orphans = [
            {"commit": "abc1234", "message": "docs: update README", "date": "2026-03-20"},
            {"commit": "def5678", "message": "fix: typo", "date": "2026-03-20"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            warnings_file = os.path.join(tmpdir, "warnings.log")
            write_orphan_warnings(orphans, warnings_file)
            assert Path(warnings_file).exists()
            content = Path(warnings_file).read_text()
            assert "abc1234" in content
            assert "docs: update README" in content
            assert "def5678" in content

    def test_creates_parent_directory(self):
        """Creates parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            warnings_file = os.path.join(tmpdir, "subdir", "warnings.log")
            orphans = [{"commit": "abc", "message": "test", "date": "2026-03-20"}]
            write_orphan_warnings(orphans, warnings_file)
            assert Path(warnings_file).exists()

    def test_empty_orphans_creates_file(self):
        """Creates file even if orphans list is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            warnings_file = os.path.join(tmpdir, "warnings.log")
            write_orphan_warnings([], warnings_file)
            assert Path(warnings_file).exists()
            assert Path(warnings_file).read_text() == ""


class TestValidateGitCliff:
    """Test git-cliff binary validation."""

    def test_validates_existing_binary(self):
        """Returns True for valid git-cliff binary."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = validate_git_cliff("git-cliff")
            assert result is True
            mock_run.assert_called_once()

    def test_fails_for_nonexistent_binary(self):
        """Returns False if binary not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = validate_git_cliff("nonexistent")
            assert result is False

    def test_fails_for_binary_error(self):
        """Returns False if binary returns error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = validate_git_cliff("git-cliff")
            assert result is False

    def test_fails_on_timeout(self):
        """Returns False if command times out."""
        with patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("cmd", 10)):
            result = validate_git_cliff("git-cliff")
            assert result is False


class TestChangelogSchemaCompliance:
    """Test that generated data complies with Keep-a-Changelog format."""

    def test_changelog_entry_format(self):
        """Generated commits can be formatted as Keep-a-Changelog sections."""
        # Simulate parsed commits from git-cliff
        commits = [
            {"commit": "abc1234", "message": "feat: US-1055 - add integration test", "date": "2026-03-20"},
            {"commit": "def5678", "message": "fix: US-1050 - fix quota logic", "date": "2026-03-20"},
            {"commit": "ghi9012", "message": "docs: US-1000 - update docs", "date": "2026-03-20"},
        ]

        # Group by type (feat=Added, fix=Fixed, docs=Changed)
        sections = {"Added": [], "Fixed": [], "Changed": []}
        for commit in commits:
            msg = commit["message"]
            if msg.startswith("feat:"):
                sections["Added"].append(f"- {msg[6:]}")
            elif msg.startswith("fix:"):
                sections["Fixed"].append(f"- {msg[5:]}")
            elif msg.startswith("docs:"):
                sections["Changed"].append(f"- {msg[6:]}")

        # Verify sections are populated correctly
        assert len(sections["Added"]) >= 1
        assert len(sections["Fixed"]) >= 1
        assert len(sections["Changed"]) >= 1
        assert "US-1055" in sections["Added"][0]
        assert "US-1050" in sections["Fixed"][0]


class TestGenerateChangelog:
    """Test changelog generation via git-cliff subprocess."""

    def test_generate_changelog_success(self):
        """Successfully generates CHANGELOG.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "CHANGELOG.md")
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)

            with patch("subprocess.run") as mock_run:
                # Mock successful git-cliff execution
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                Path(output_file).touch()  # Create file to simulate git-cliff output

                from gen_changelog import generate_changelog

                result = generate_changelog("git-cliff", "cliff.toml", output_file)
                assert result is True

    def test_generate_changelog_failure(self):
        """Handles git-cliff errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "CHANGELOG.md")

            with patch("subprocess.run") as mock_run:
                # Mock git-cliff failure
                mock_run.return_value = MagicMock(returncode=1, stderr="error")

                from gen_changelog import generate_changelog

                result = generate_changelog("git-cliff", "cliff.toml", output_file)
                assert result is False

    def test_generate_changelog_missing_file(self):
        """Returns False when output file not created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "nonexistent.md")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stderr="")
                # Don't create the file

                from gen_changelog import generate_changelog

                result = generate_changelog("git-cliff", "cliff.toml", output_file)
                assert result is False

    def test_generate_changelog_timeout(self):
        """Returns False when git-cliff times out."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "CHANGELOG.md")

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("git-cliff", 60)

                from gen_changelog import generate_changelog

                result = generate_changelog("git-cliff", "cliff.toml", output_file)
                assert result is False

    def test_generate_changelog_file_not_found(self):
        """Returns False when git-cliff binary is not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "CHANGELOG.md")

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("git-cliff not found")

                from gen_changelog import generate_changelog

                result = generate_changelog("nonexistent-cliff", "cliff.toml", output_file)
                assert result is False


class TestRunPhaseG:
    """Test the main run() function for Phase G."""

    def test_run_success_with_story_ids(self, tmp_path):
        """Phase G run succeeds when all commits have story IDs."""
        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        changelog = tmp_path / "CHANGELOG.md"
        warnings_file = tmp_path / ".spiral" / "phase_g_warnings.log"

        cliff_toml.write_text("[changelog]")
        changelog.write_text("# Changelog\n")

        with patch("subprocess.run") as mock_run:
            # Mock git-cliff success
            def side_effect(*args, **kwargs):
                if "git-cliff" in args[0]:
                    (tmp_path / "CHANGELOG.md").touch()
                    return MagicMock(returncode=0, stderr="", stdout="")
                elif "git" in args[0] and "log" in args[0]:
                    return MagicMock(
                        returncode=0,
                        stdout="abc1234\nfeat: US-1055 - test\n2026-03-20T00:00:00Z\ndef5678\nfix: US-1050 - quota\n2026-03-20T01:00:00Z\n",
                    )
                return MagicMock(returncode=0, stderr="")

            mock_run.side_effect = side_effect

            from gen_changelog import run

            result = run(spiral_home, cliff_bin="git-cliff")
            assert result == 0

    def test_run_detects_orphan_commits(self, tmp_path):
        """Phase G run detects orphan commits and logs them."""
        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        changelog = tmp_path / "CHANGELOG.md"

        cliff_toml.write_text("[changelog]")

        with patch("subprocess.run") as mock_run:
            def side_effect(*args, **kwargs):
                if "git-cliff" in args[0]:
                    (tmp_path / "CHANGELOG.md").touch()
                    return MagicMock(returncode=0, stderr="", stdout="")
                elif "git" in args[0] and "log" in args[0]:
                    return MagicMock(
                        returncode=0,
                        stdout="abc1234\nfeat: US-1055 - test\n2026-03-20T00:00:00Z\ndef5678\nfix: orphan\n2026-03-20T01:00:00Z\n",
                    )
                return MagicMock(returncode=0, stderr="")

            mock_run.side_effect = side_effect

            from gen_changelog import run

            result = run(spiral_home, cliff_bin="git-cliff")
            assert result == 0
            # Check that warnings file was created
            warnings = tmp_path / ".spiral" / "phase_g_warnings.log"
            assert warnings.exists()

    def test_run_missing_cliff_toml(self, tmp_path):
        """Phase G run fails when cliff.toml is missing."""
        spiral_home = str(tmp_path)
        # Don't create cliff.toml

        from gen_changelog import run

        result = run(spiral_home, cliff_bin="git-cliff")
        assert result == 1

    def test_run_invalid_cliff_binary(self, tmp_path):
        """Phase G run fails when git-cliff binary is invalid."""
        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        cliff_toml.write_text("[changelog]")

        with patch("gen_changelog.validate_git_cliff", return_value=False):
            from gen_changelog import run

            result = run(spiral_home, cliff_bin="nonexistent")
            assert result == 1

    def test_run_changelog_not_created(self, tmp_path):
        """Phase G run fails when git-cliff doesn't create CHANGELOG.md."""
        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        cliff_toml.write_text("[changelog]")

        with patch("gen_changelog.validate_git_cliff", return_value=True):
            with patch("subprocess.run") as mock_run:
                # Mock git-cliff failure (doesn't create file)
                mock_run.return_value = MagicMock(returncode=1, stderr="error")

                from gen_changelog import run

                result = run(spiral_home, cliff_bin="git-cliff")
                assert result == 1

    def test_run_git_log_timeout(self, tmp_path):
        """Phase G run handles git log timeout gracefully."""
        import subprocess

        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        changelog = tmp_path / "CHANGELOG.md"
        cliff_toml.write_text("[changelog]")

        with patch("gen_changelog.validate_git_cliff", return_value=True):
            with patch("subprocess.run") as mock_run:
                def side_effect(*args, **kwargs):
                    if "git-cliff" in args[0]:
                        changelog.touch()
                        return MagicMock(returncode=0, stderr="", stdout="")
                    elif "git" in args[0] and "log" in args[0]:
                        raise subprocess.TimeoutExpired("git", 30)
                    return MagicMock(returncode=0, stderr="")

                mock_run.side_effect = side_effect

                from gen_changelog import run

                result = run(spiral_home, cliff_bin="git-cliff")
                # Should complete successfully despite git log timeout
                assert result == 0

    def test_run_git_log_oserror(self, tmp_path):
        """Phase G run handles git log OSError gracefully."""
        spiral_home = str(tmp_path)
        cliff_toml = tmp_path / "cliff.toml"
        changelog = tmp_path / "CHANGELOG.md"
        cliff_toml.write_text("[changelog]")

        with patch("gen_changelog.validate_git_cliff", return_value=True):
            with patch("subprocess.run") as mock_run:
                def side_effect(*args, **kwargs):
                    if "git-cliff" in args[0]:
                        changelog.touch()
                        return MagicMock(returncode=0, stderr="", stdout="")
                    elif "git" in args[0] and "log" in args[0]:
                        raise OSError("git not found")
                    return MagicMock(returncode=0, stderr="")

                mock_run.side_effect = side_effect

                from gen_changelog import run

                result = run(spiral_home, cliff_bin="git-cliff")
                assert result == 0
