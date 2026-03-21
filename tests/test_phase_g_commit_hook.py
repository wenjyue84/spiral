"""Tests for Phase G commit hook installer."""

import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


class TestCommitHookInstaller:
    """Test commit hook installation and validation."""

    @pytest.fixture
    def temp_git_repo(self) -> Generator[Path, None, None]:
        """Create temporary git repository with hook installed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )

            # Configure git user for commits
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )

            # Create initial commit so we can test hook
            (repo_path / "README.md").write_text("# Test Repo\n")
            subprocess.run(
                ["git", "add", "README.md"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )

            # Install the hook
            installer_path = (
                Path(__file__).parent.parent
                / "lib/phases/phase_g/commit_hook_installer.sh"
            )
            bash_path = shutil.which("bash")
            if not bash_path:
                raise RuntimeError("bash not found in PATH")

            # Convert to POSIX path for bash on Windows
            hooks_dir = repo_path / ".git/hooks"
            hooks_dir_posix = hooks_dir.as_posix()
            installer_posix = installer_path.as_posix()

            subprocess.run(
                [bash_path, installer_posix, hooks_dir_posix],
                check=True,
                capture_output=True,
                text=True,
            )

            yield repo_path

    def test_hook_installed(self, temp_git_repo: Path) -> None:
        """Test that hook is installed."""
        hook_path = temp_git_repo / ".git/hooks/prepare-commit-msg"
        assert hook_path.exists(), "Hook file should exist"
        # Windows doesn't use Unix execute bits; executability is determined by extension
        # The actual executability is verified by test_valid_commit_with_us_prefix etc.

    def test_valid_commit_with_us_prefix(self, temp_git_repo: Path) -> None:
        """Test commit with valid US-NNN: prefix is accepted."""
        # Create a test file
        (temp_git_repo / "test.txt").write_text("test content")

        # Try to commit with valid message
        subprocess.run(
            ["git", "add", "test.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        # Commit with valid US prefix
        result = subprocess.run(
            ["git", "commit", "-m", "US-123: test commit"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"Commit should succeed with valid prefix. "
            f"stderr: {result.stderr}"
        )

    def test_valid_commit_with_ut_prefix(self, temp_git_repo: Path) -> None:
        """Test commit with valid UT-NNN: prefix is accepted."""
        # Create a test file
        (temp_git_repo / "test2.txt").write_text("test content 2")

        # Try to commit with valid message
        subprocess.run(
            ["git", "add", "test2.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        # Commit with valid UT prefix
        result = subprocess.run(
            ["git", "commit", "-m", "UT-456: test automation"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"Commit should succeed with valid UT prefix. "
            f"stderr: {result.stderr}"
        )

    def test_invalid_commit_missing_prefix(self, temp_git_repo: Path) -> None:
        """Test commit without story ID prefix is rejected."""
        # Create a test file
        (temp_git_repo / "test3.txt").write_text("test content 3")

        # Try to commit with valid message
        subprocess.run(
            ["git", "add", "test3.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        # Commit with invalid message (missing prefix)
        result = subprocess.run(
            ["git", "commit", "-m", "forgot the story ID"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode != 0
        ), "Commit should fail without story ID prefix"
        assert "Commit message must start with" in result.stderr, (
            f"Error message should explain requirement. "
            f"stderr: {result.stderr}"
        )
        assert "US-NNN:" in result.stderr and "UT-NNN:" in result.stderr, (
            "Error message should show valid formats"
        )

    def test_invalid_commit_wrong_format(self, temp_git_repo: Path) -> None:
        """Test commit with wrong story ID format is rejected."""
        # Create a test file
        (temp_git_repo / "test4.txt").write_text("test content 4")

        # Try to commit with valid message
        subprocess.run(
            ["git", "add", "test4.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        # Commit with invalid format (no colon, or US without dash)
        result = subprocess.run(
            ["git", "commit", "-m", "US123 without colon"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode != 0
        ), "Commit should fail with wrong format"
        assert "Commit message must start with" in result.stderr

    def test_error_message_displayed(self, temp_git_repo: Path) -> None:
        """Test that correct error message is displayed on rejection."""
        # Create a test file
        (temp_git_repo / "test5.txt").write_text("test content 5")

        # Try to commit with valid message
        subprocess.run(
            ["git", "add", "test5.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True,
            text=True,
        )

        # Commit with invalid message
        result = subprocess.run(
            ["git", "commit", "-m", "invalid message"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
        )

        expected_error = "Commit message must start with US-NNN: or UT-NNN:"
        assert expected_error in result.stderr, (
            f"Error message '{expected_error}' should be in stderr. "
            f"Got: {result.stderr}"
        )
