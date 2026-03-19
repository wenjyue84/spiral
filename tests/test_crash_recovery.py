"""
tests/test_crash_recovery.py — US-526: Worker crash recovery regression tests

Tests for detached HEAD recovery logic in lib/impl/commit_revert.sh (US-461).
Verifies that workers can recover from crashes that leave them in detached HEAD state.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

import pytest


def _find_git_bash() -> str:
    """Find git bash executable on Windows or return bash."""
    for candidate in [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\usr\bin\bash.exe"),
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("bash") or "bash"


_BASH = _find_git_bash()


class TestDetachedHeadRecovery:
    """Tests for crash recovery with detached HEAD worktrees."""

    def test_detached_head_triggers_recovery(self) -> None:
        """Test that recovery function detects and recovers from detached HEAD state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path, worktree_path = _create_repo_with_worktree(tmpdir)

            # Put worktree in detached HEAD state (simulating crash)
            _put_worktree_in_detached_head(worktree_path)

            # Verify worktree is in detached HEAD state before recovery
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert current_branch == "HEAD", "Worktree should be in detached HEAD state before recovery"

            # Call recovery function via bash
            bash_wtree = str(worktree_path).replace("\\", "/")
            if bash_wtree[1:3] == ":\\":  # C:\ style path
                bash_wtree = "/" + bash_wtree[0].lower() + bash_wtree[2:]

            result = subprocess.run(
                [
                    _BASH,
                    "-c",
                    f"""
                    source lib/impl/commit_revert.sh
                    recover_detached_worktree "{bash_wtree}"
                    exit $?
                    """,
                ],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"Recovery should succeed. stderr: {result.stderr}"

            # Verify worktree is back on main after recovery
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert current_branch == "main", "Worktree should be back on main branch after recovery"

    def test_recovery_leaves_clean_worktree(self) -> None:
        """Test that recovery leaves the worktree with a clean working tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path, worktree_path = _create_repo_with_worktree(tmpdir)

            # Put worktree in detached HEAD and create dirty state
            _put_worktree_in_detached_head(worktree_path)
            _create_dirty_worktree(worktree_path)

            # Verify worktree has dirty state before recovery
            status_before = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert len(status_before) > 0, "Worktree should have dirty state before recovery"

            # Call recovery function via bash
            bash_wtree = str(worktree_path).replace("\\", "/")
            if bash_wtree[1:3] == ":\\":  # C:\ style path
                bash_wtree = "/" + bash_wtree[0].lower() + bash_wtree[2:]

            result = subprocess.run(
                [
                    _BASH,
                    "-c",
                    f"""
                    source lib/impl/commit_revert.sh
                    recover_detached_worktree "{bash_wtree}"
                    exit $?
                    """,
                ],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"Recovery should succeed. stderr: {result.stderr}"

            # Verify working tree is clean after recovery
            status_after = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert len(status_after) == 0, f"Worktree should be clean after recovery, but has: {status_after}"

    def test_recovery_noop_on_clean_branch(self) -> None:
        """Test that recovery returns 1 (no-op) when worktree is already on a clean branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path, worktree_path = _create_repo_with_worktree(tmpdir)

            # Worktree starts on main branch (clean state from creation)
            current_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert current_branch == "main", "Worktree should be on main initially"

            # Call recovery function via bash (should be no-op)
            bash_wtree = str(worktree_path).replace("\\", "/")
            if bash_wtree[1:3] == ":\\":  # C:\ style path
                bash_wtree = "/" + bash_wtree[0].lower() + bash_wtree[2:]

            result = subprocess.run(
                [
                    _BASH,
                    "-c",
                    f"""
                    source lib/impl/commit_revert.sh
                    recover_detached_worktree "{bash_wtree}"
                    exit $?
                    """,
                ],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )

            # Return code 1 means "already on a branch — no recovery needed"
            assert result.returncode == 1, "Recovery should return 1 for clean branch (no-op case)"

    def test_recovery_fails_on_nonexistent_worktree(self) -> None:
        """Test that recovery fails gracefully with nonexistent worktree."""
        nonexistent = "/nonexistent/worktree/path"

        result = subprocess.run(
            [
                _BASH,
                "-c",
                f"""
                source lib/impl/commit_revert.sh
                recover_detached_worktree "{nonexistent}"
                exit $?
                """,
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        # Should return 2 (failure)
        assert result.returncode == 2, "Recovery should return 2 for nonexistent worktree"
        assert "does not exist" in result.stderr.lower(), "Should mention missing worktree in error"


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────


def _create_repo_with_worktree(tmpdir: str) -> Tuple[Path, Path]:
    """Create a git repository and a worktree for testing.

    Returns: (repo_path, worktree_path)
    """
    tmpdir_path = Path(tmpdir)
    repo_path = tmpdir_path / "repo"
    worktree_path = tmpdir_path / "worktree"

    # Initialize main repo
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)

    # Create initial commit
    (repo_path / "README.md").write_text("initial commit")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-qm", "Initial commit"], cwd=repo_path, check=True)

    # Create worktree on main branch
    subprocess.run(
        ["git", "worktree", "add", "-b", "main", str(worktree_path), "HEAD"],
        cwd=repo_path,
        check=True,
    )

    return repo_path, worktree_path


def _put_worktree_in_detached_head(worktree_path: Path) -> None:
    """Put a worktree in detached HEAD state by checking out a commit hash.

    Simulates what happens when a worker crashes and leaves the worktree in a bad state.
    """
    # Get the current commit hash
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Check out the commit by hash (creates detached HEAD state)
    subprocess.run(
        ["git", "checkout", "-q", current_commit],
        cwd=worktree_path,
        check=True,
    )


def _create_dirty_worktree(worktree_path: Path) -> None:
    """Create a dirty worktree with staged and unstaged changes.

    Simulates what happens when a worker crash leaves uncommitted changes.
    """
    # Create a new file
    (worktree_path / "dirty_file.txt").write_text("this file should be cleaned up")

    # Modify an existing file and stage the change
    (worktree_path / "README.md").write_text("modified content")
    subprocess.run(["git", "add", "README.md"], cwd=worktree_path, check=True)
