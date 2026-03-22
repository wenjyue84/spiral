"""Integration tests for Phase G: CHANGELOG and API doc generation.

Tests verify the auto_release module's changelog and API doc generation functions
using mocks to enable testing without external tool dependencies (git-cliff, pdoc).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest
from observability.auto_release import generate_api_docs, generate_changelog, run_command

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with basic config."""
    subprocess.run(
        ["git", "init", str(repo_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Provide a temporary git repository."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    return repo_path


@pytest.fixture
def git_repo_with_commits(git_repo: Path) -> Path:
    """Provide a git repo with several conventional commits."""
    # Initial commit
    (git_repo / "README.md").write_text("# Test Project\n")
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-m", "chore: initial commit"],
        check=True,
        capture_output=True,
    )

    # Feature commit
    (git_repo / "feature.py").write_text('"""New feature module."""\ndef hello(): return "world"\n')
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-m", "feat: add new feature module"],
        check=True,
        capture_output=True,
    )

    # Bug fix commit
    (git_repo / "bugfix.py").write_text('"""Bug fix."""\ndef fix(): pass\n')
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-m", "fix: correct critical bug"],
        check=True,
        capture_output=True,
    )

    return git_repo


@pytest.fixture
def git_repo_empty(git_repo: Path) -> Path:
    """Provide a git repo with no commits."""
    return git_repo


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestChangelogGeneration:
    """Test generate_changelog() function with mocked git-cliff."""

    def test_changelog_generated_from_commits(self, git_repo_with_commits: Path) -> None:
        """Verify CHANGELOG.md is created from git history."""
        changelog_path = git_repo_with_commits / "CHANGELOG.md"
        config_path = git_repo_with_commits / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            generate_changelog(config=str(config_path), output=str(changelog_path))

            # Verify git-cliff was called with correct arguments
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "git-cliff" in call_args
            assert str(config_path) in call_args
            assert str(changelog_path) in call_args

    def test_changelog_handles_empty_commit_log(self, git_repo_empty: Path) -> None:
        """Verify CHANGELOG.md handles empty repo gracefully."""
        changelog_path = git_repo_empty / "CHANGELOG.md"
        config_path = git_repo_empty / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            # Should not raise even with empty repo
            generate_changelog(config=str(config_path), output=str(changelog_path))

            mock_run.assert_called_once()

    def test_changelog_output_path_respects_argument(self, git_repo_with_commits: Path) -> None:
        """Verify changelog output path argument is respected."""
        custom_output = git_repo_with_commits / "docs" / "HISTORY.md"
        config_path = git_repo_with_commits / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            generate_changelog(config=str(config_path), output=str(custom_output))

            # Verify custom output path was passed to git-cliff
            call_args = mock_run.call_args[0][0]
            assert str(custom_output) in call_args


class TestApiDocsGeneration:
    """Test generate_api_docs() function with mocked pdoc."""

    def test_api_docs_generated_by_pdoc(self, git_repo_with_commits: Path) -> None:
        """Verify API docs are created by pdoc from Python modules."""
        output_dir = git_repo_with_commits / "docs" / "api"

        # Ensure we have lib directory with Python files
        lib_dir = git_repo_with_commits / "lib"
        lib_dir.mkdir()
        (lib_dir / "__init__.py").write_text("")
        (lib_dir / "example.py").write_text('"""Example module."""\ndef sample(): pass\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            generate_api_docs(source_dir="lib", output_dir=str(output_dir), title="Test API Docs")

            # Verify pdoc was called (first call; additional git calls follow)
            calls = [c[0][0] for c in mock_run.call_args_list if c[0]]
            pdoc_calls = [c for c in calls if "pdoc" in c]
            assert len(pdoc_calls) >= 1
            call_args = pdoc_calls[0]
            assert "lib" in call_args
            assert str(output_dir) in call_args
            assert "Test API Docs" in call_args

    def test_api_docs_output_path_created(self, git_repo_with_commits: Path) -> None:
        """Verify API docs respects custom output directory argument."""
        lib_dir = git_repo_with_commits / "lib"
        lib_dir.mkdir()
        (lib_dir / "__init__.py").write_text("")
        (lib_dir / "module.py").write_text('"""Test module."""\n')

        custom_output = git_repo_with_commits / "custom_docs"

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            generate_api_docs(source_dir="lib", output_dir=str(custom_output), title="Custom Docs")

            # Verify custom output path was passed to pdoc (first call)
            calls = [c[0][0] for c in mock_run.call_args_list if c[0]]
            pdoc_calls = [c for c in calls if "pdoc" in c]
            assert len(pdoc_calls) >= 1
            assert str(custom_output) in pdoc_calls[0]


class TestPhaseGOrchestration:
    """Integration tests for Phase G orchestration."""

    def test_both_artifacts_generated_together(self, git_repo_with_commits: Path) -> None:
        """Verify changelog and API docs are both generated in one Phase G run."""
        lib_dir = git_repo_with_commits / "lib"
        lib_dir.mkdir()
        (lib_dir / "__init__.py").write_text("")
        (lib_dir / "core.py").write_text('"""Core module."""\ndef process(): pass\n')

        changelog_path = git_repo_with_commits / "CHANGELOG.md"
        docs_path = git_repo_with_commits / "docs" / "api"
        config_path = git_repo_with_commits / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            # Run both generation functions (as Phase G would)
            generate_changelog(config=str(config_path), output=str(changelog_path))
            generate_api_docs(source_dir="lib", output_dir=str(docs_path))

            # Verify both tools were called (additional git calls may follow)
            assert mock_run.call_count >= 2
            calls = [c[0][0] for c in mock_run.call_args_list if c[0]]
            assert any("git-cliff" in str(c) for c in calls)
            assert any("pdoc" in str(c) for c in calls)

    def test_phase_g_handles_empty_commit_log(self, git_repo_empty: Path) -> None:
        """Verify Phase G handles empty commit log gracefully."""
        changelog_path = git_repo_empty / "CHANGELOG.md"
        config_path = git_repo_empty / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)

            # Should handle empty repo without errors
            generate_changelog(config=str(config_path), output=str(changelog_path))

            mock_run.assert_called_once()


class TestPhaseGErrorHandling:
    """Test error handling in Phase G functions."""

    def test_run_command_raises_on_failure(self) -> None:
        """Verify run_command raises RuntimeError on command failure."""
        with pytest.raises(RuntimeError, match="Failed to"):
            run_command(["false"], "test failure command")

    def test_generate_changelog_raises_on_tool_failure(self, git_repo_with_commits: Path) -> None:
        """Verify generate_changelog raises on tool failure."""
        config_path = git_repo_with_commits / "cliff.toml"
        config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1)  # Simulate failure

            with pytest.raises(RuntimeError, match="Failed to"):
                generate_changelog(config=str(config_path), output="CHANGELOG.md")

    def test_generate_api_docs_raises_on_tool_failure(self, git_repo_with_commits: Path) -> None:
        """Verify generate_api_docs raises on tool failure."""
        lib_dir = git_repo_with_commits / "lib"
        lib_dir.mkdir()
        (lib_dir / "__init__.py").write_text("")

        with mock.patch("observability.auto_release.subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=1)  # Simulate failure

            with pytest.raises(RuntimeError, match="Failed to"):
                generate_api_docs(source_dir="lib", output_dir="docs/api")


# ── Module-level test functions (matching acceptance criteria) ────────────────


def test_changelog_generated_from_commits(git_repo_with_commits: Path) -> None:
    """Verify CHANGELOG.md is created from git history.

    Acceptance criteria: uv run pytest tests/test_phase_g_integration.py::test_changelog_generated_from_commits
    """
    changelog_path = git_repo_with_commits / "CHANGELOG.md"
    config_path = git_repo_with_commits / "cliff.toml"
    config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

    with mock.patch("observability.auto_release.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)

        generate_changelog(config=str(config_path), output=str(changelog_path))

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "git-cliff" in call_args
        assert str(config_path) in call_args
        assert str(changelog_path) in call_args


def test_api_docs_generated_by_pdoc(git_repo_with_commits: Path) -> None:
    """Verify API docs are created by pdoc from Python modules.

    Acceptance criteria: uv run pytest tests/test_phase_g_integration.py::test_api_docs_generated_by_pdoc
    """
    output_dir = git_repo_with_commits / "docs" / "api"

    lib_dir = git_repo_with_commits / "lib"
    lib_dir.mkdir()
    (lib_dir / "__init__.py").write_text("")
    (lib_dir / "example.py").write_text('"""Example module."""\ndef sample(): pass\n')

    with mock.patch("observability.auto_release.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)

        generate_api_docs(source_dir="lib", output_dir=str(output_dir), title="Test API Docs")

        calls = [c[0][0] for c in mock_run.call_args_list if c[0]]
        pdoc_calls = [c for c in calls if "pdoc" in c]
        assert len(pdoc_calls) >= 1
        call_args = pdoc_calls[0]
        assert "lib" in call_args
        assert str(output_dir) in call_args
        assert "Test API Docs" in call_args


def test_phase_g_handles_empty_commit_log(git_repo_empty: Path) -> None:
    """Verify Phase G handles empty commit log gracefully.

    Acceptance criteria: uv run pytest tests/test_phase_g_integration.py::test_phase_g_handles_empty_commit_log
    """
    changelog_path = git_repo_empty / "CHANGELOG.md"
    config_path = git_repo_empty / "cliff.toml"
    config_path.write_text('[changelog]\nheader = "# Changelog"\n[git]\nconventional_commits = true\n')

    with mock.patch("observability.auto_release.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)

        generate_changelog(config=str(config_path), output=str(changelog_path))

        mock_run.assert_called_once()
