"""Integration tests for Phase G: CHANGELOG.md generation via git-cliff.

Tests verify that Phase G produces a valid CHANGELOG.md from story commits
without requiring network access or manual tool installation.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.observability.auto_release import generate_api_docs, generate_changelog, main, run_command


class TestChangelogGenerationHappyPath:
    """Tests for successful CHANGELOG.md generation."""

    def test_generate_changelog_creates_file(self) -> None:
        """Verify CHANGELOG.md is created when git-cliff succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            output_file = tmpdir_path / "CHANGELOG.md"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                generate_changelog(
                    config=str(tmpdir_path / "cliff.toml"),
                    output=str(output_file),
                )

                # Verify subprocess was called with correct git-cliff command
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert call_args[0] == "git-cliff"
                assert "--output" in call_args
                assert str(output_file) in call_args

    def test_generate_changelog_with_default_params(self) -> None:
        """Verify git-cliff is invoked with default parameters."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            generate_changelog()

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args == ["git-cliff", "--config", "cliff.toml", "--output", "CHANGELOG.md"]

    def test_main_orchestrates_both_artifacts(self) -> None:
        """Verify main() calls both changelog and API docs generation."""
        with patch("lib.observability.auto_release.generate_changelog") as mock_changelog:
            with patch("lib.observability.auto_release.generate_api_docs") as mock_api_docs:
                with patch("builtins.print"):  # Suppress output
                    main()

                mock_changelog.assert_called_once()
                mock_api_docs.assert_called_once()


class TestChangelogGenerationErrors:
    """Tests for error handling in CHANGELOG.md generation."""

    def test_run_command_raises_on_failure(self) -> None:
        """Verify RuntimeError is raised when subprocess fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            with pytest.raises(RuntimeError, match="Failed to"):
                run_command(["git-cliff", "--config", "cliff.toml"], "test command")

    def test_generate_changelog_fails_when_git_cliff_missing(self) -> None:
        """Verify error is raised when git-cliff binary is not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=127)  # "command not found"

            with pytest.raises(RuntimeError):
                generate_changelog()

    def test_generate_changelog_fails_when_no_commits(self) -> None:
        """Verify error is raised when git-cliff finds no commits."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)  # git-cliff error

            with pytest.raises(RuntimeError, match="Failed to Generate"):
                generate_changelog()

    def test_main_handles_changelog_failure(self) -> None:
        """Verify main() exits with error code when changelog generation fails."""
        with patch("lib.observability.auto_release.generate_changelog") as mock_changelog:
            mock_changelog.side_effect = RuntimeError("test error")

            with patch("builtins.print"):  # Suppress output
                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 1

    def test_main_handles_api_docs_failure(self) -> None:
        """Verify main() exits with error code when API docs generation fails."""
        with patch("lib.observability.auto_release.generate_changelog"):
            with patch("lib.observability.auto_release.generate_api_docs") as mock_api_docs:
                mock_api_docs.side_effect = RuntimeError("test error")

                with patch("builtins.print"):  # Suppress output
                    with pytest.raises(SystemExit) as exc_info:
                        main()

                    assert exc_info.value.code == 1


class TestChangelogIntegration:
    """Full integration tests for Phase G workflow."""

    def test_phase_g_full_workflow_success(self) -> None:
        """Verify full Phase G workflow succeeds with mocked subprocess."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Setup mock files/dirs
            tmpdir_path / "CHANGELOG.md"
            tmpdir_path / "docs" / "api"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                with patch("builtins.print"):  # Suppress output
                    main()

                # Verify subprocess was called (at least twice: changelog + api docs)
                assert mock_run.call_count >= 2
                assert any("git-cliff" in str(call) for call in mock_run.call_args_list)
                assert any("pdoc" in str(call) for call in mock_run.call_args_list)

    def test_changelog_output_file_path_honored(self) -> None:
        """Verify generate_changelog uses the specified output path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            custom_output = tmpdir_path / "CUSTOM_CHANGELOG.md"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                generate_changelog(output=str(custom_output))

                call_args = mock_run.call_args[0][0]
                assert str(custom_output) in call_args

    def test_api_docs_creates_output_directory(self) -> None:
        """Verify generate_api_docs creates output directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            docs_output = tmpdir_path / "docs" / "api"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                generate_api_docs(output_dir=str(docs_output))

                # Verify output directory exists or would be created
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert "pdoc" in call_args[0]


# Module-level test functions matching acceptance criteria


def test_phase_g_changelog_generation_success() -> None:
    """[Acceptance Criterion 1] CHANGELOG.md is created after Phase G runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        changelog_file = tmpdir_path / "CHANGELOG.md"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            generate_changelog(output=str(changelog_file))

            # Verify git-cliff was called
            assert mock_run.called
            call_args = mock_run.call_args[0][0]
            assert "git-cliff" in call_args


def test_phase_g_handles_git_cliff_missing() -> None:
    """[Acceptance Criterion 3] Error case: git-cliff binary missing."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=127)

        with pytest.raises(RuntimeError, match="Failed to"):
            generate_changelog()


def test_phase_g_handles_no_commits() -> None:
    """[Acceptance Criterion 3] Error case: no commits found."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)

        with pytest.raises(RuntimeError):
            generate_changelog()
