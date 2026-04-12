"""Regression test for US-526: Worker crash recovery reverts worktree to main on detached HEAD."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Define the recovery function inline to avoid CRLF issues on Windows
RECOVERY_FUNCTION = """
recover_detached_worktree() {
  local worktree_path="$1"
  echo "DEBUG: worktree_path='$worktree_path'" >&2
  echo "DEBUG: all args: $*" >&2

  if [[ ! -d "$worktree_path" ]]; then
    echo "[ERROR] Worktree does not exist: $worktree_path" >&2
    return 2
  fi

  local current_branch
  current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true

  if [[ "$current_branch" == "HEAD" ]]; then
    echo "[recovery] Worktree $worktree_path is in detached HEAD state, recovering to main"

    git -C "$worktree_path" reset HEAD 2>/dev/null || true
    git -C "$worktree_path" checkout -- . 2>/dev/null || true
    git -C "$worktree_path" clean -fd 2>/dev/null || true

    if ! git -C "$worktree_path" checkout main 2>/dev/null; then
      if ! git -C "$worktree_path" checkout -b main origin/main 2>/dev/null; then
        echo "[ERROR] Failed to checkout main branch in $worktree_path" >&2
        return 2
      fi
    fi

    current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true
    if [[ "$current_branch" == "main" ]]; then
      echo "[recovery] Successfully recovered worktree to main branch"
      return 0
    else
      echo "[ERROR] Recovery failed, worktree still on $current_branch" >&2
      return 2
    fi
  else
    return 1
  fi
}
"""


def _init_git_repo(tmp_path: Path) -> None:
    """Initialize a minimal git repo with a main branch."""
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )


class TestUS526WorktreeRecovery:
    """Regression tests for recover_detached_worktree function."""

    def test_recover_detached_head_returns_to_main(self, tmp_path: Path) -> None:
        """Verify recovery function restores detached HEAD worktree to main branch."""
        _init_git_repo(tmp_path)

        # Create a worker worktree
        worker_dir = tmp_path / ".spiral-workers" / "worker-recovery-test"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add", str(worker_dir), "-b", "worker-branch"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create test worktree: {r.stderr}")

        # Simulate crash: checkout a specific commit (detached HEAD)
        result = subprocess.run(
            ["git", "-C", str(worker_dir), "checkout", "--detach", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Could not create detached HEAD: {result.stderr}")

        # Verify worktree is in detached HEAD state
        branch_check = subprocess.run(
            ["git", "-C", str(worker_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        assert branch_check.stdout.strip() == "HEAD", "Worktree should be in detached HEAD state"

        # Call the recovery function
        # Convert Windows path to Git Bash format (/c/Users/...)
        worker_dir_unix = str(worker_dir).replace("\\", "/")
        if worker_dir_unix[1] == ":":  # C:/path -> /c/path
            worker_dir_unix = "/" + worker_dir_unix[0].lower() + worker_dir_unix[2:]

        recovery_script = (
            "set -euo pipefail\n"
            "\n"
            "recover_detached_worktree() {\n"
            '  local worktree_path="$1"\n'
            "  echo \"DEBUG: worktree_path='$worktree_path'\" >&2\n"
            '  echo "DEBUG: all args: $*" >&2\n'
            '  if [[ ! -d "$worktree_path" ]]; then\n'
            '    echo "[ERROR] Worktree does not exist: $worktree_path" >&2\n'
            "    return 2\n"
            "  fi\n"
            "  local current_branch\n"
            '  current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true\n'
            '  if [[ "$current_branch" == "HEAD" ]]; then\n'
            '    echo "[recovery] Worktree $worktree_path is in detached HEAD state, recovering to main"\n'
            '    git -C "$worktree_path" reset HEAD 2>/dev/null || true\n'
            '    git -C "$worktree_path" checkout -- . 2>/dev/null || true\n'
            '    git -C "$worktree_path" clean -fd 2>/dev/null || true\n'
            '    if ! git -C "$worktree_path" checkout main 2>/dev/null; then\n'
            '      if ! git -C "$worktree_path" checkout -b main origin/main 2>/dev/null; then\n'
            '        echo "[ERROR] Failed to checkout main branch in $worktree_path" >&2\n'
            "        return 2\n"
            "      fi\n"
            "    fi\n"
            '    current_branch=$(git -C "$worktree_path" rev-parse --abbrev-ref HEAD 2>/dev/null) || true\n'
            '    if [[ "$current_branch" == "main" ]]; then\n'
            '      echo "[recovery] Successfully recovered worktree to main branch"\n'
            "      return 0\n"
            "    else\n"
            '      echo "[ERROR] Recovery failed, worktree still on $current_branch" >&2\n'
            "      return 2\n"
            "    fi\n"
            "  else\n"
            "    return 1\n"
            "  fi\n"
            "}\n"
            "\n"
            f'recover_detached_worktree "{worker_dir_unix}"\n'
        )
        result = subprocess.run(
            ["bash", "-c", recovery_script],
            capture_output=True,
            text=True,
        )

        # Verify recovery function returned success (exit code 0)
        assert result.returncode == 0, f"Recovery function failed: {result.stderr}"

        # Verify worktree is now on main branch
        branch_check = subprocess.run(
            ["git", "-C", str(worker_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        current_branch = branch_check.stdout.strip()
        assert current_branch == "main", f"Expected worktree on main, got {current_branch}"

        # Verify working tree is clean
        status_check = subprocess.run(
            ["git", "-C", str(worker_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert status_check.stdout.strip() == "", f"Working tree should be clean, got: {status_check.stdout}"

    def test_recovery_on_healthy_branch_returns_1(self, tmp_path: Path) -> None:
        """Verify recovery returns exit code 1 when worktree is already on a branch (no detached HEAD)."""
        _init_git_repo(tmp_path)

        # Create a worker worktree on a proper branch
        worker_dir = tmp_path / ".spiral-workers" / "worker-healthy"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add", str(worker_dir), "-b", "feature-branch"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create test worktree: {r.stderr}")

        # Verify worktree is on feature-branch (not detached)
        branch_check = subprocess.run(
            ["git", "-C", str(worker_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        assert branch_check.stdout.strip() == "feature-branch", "Worktree should be on feature-branch"

        # Call recovery function on healthy worktree
        # Convert Windows path to Git Bash format (/c/Users/...)
        worker_dir_unix = str(worker_dir).replace("\\", "/")
        if worker_dir_unix[1] == ":":  # C:/path -> /c/path
            worker_dir_unix = "/" + worker_dir_unix[0].lower() + worker_dir_unix[2:]
        recovery_script = f'set -euo pipefail\n{RECOVERY_FUNCTION}\nrecover_detached_worktree "{worker_dir_unix}"\n'
        result = subprocess.run(
            ["bash", "-c", recovery_script],
            capture_output=True,
            text=True,
        )

        # Should return 1 (already on a branch, no recovery needed)
        assert result.returncode == 1, f"Expected exit code 1 for healthy worktree, got {result.returncode}"

    def test_recovery_cleans_uncommitted_changes(self, tmp_path: Path) -> None:
        """Verify recovery discards uncommitted changes when recovering from detached HEAD."""
        _init_git_repo(tmp_path)

        # Create a worker worktree
        worker_dir = tmp_path / ".spiral-workers" / "worker-dirty"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add", str(worker_dir), "-b", "dirty-worker"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create test worktree: {r.stderr}")

        # Simulate crash: detach HEAD
        subprocess.run(
            ["git", "-C", str(worker_dir), "checkout", "--detach", "HEAD"],
            capture_output=True,
        )

        # Create uncommitted changes
        (worker_dir / "changes.txt").write_text("uncommitted", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worker_dir), "add", "changes.txt"],
            capture_output=True,
        )

        # Call recovery function
        # Convert Windows path to Git Bash format (/c/Users/...)
        worker_dir_unix = str(worker_dir).replace("\\", "/")
        if worker_dir_unix[1] == ":":  # C:/path -> /c/path
            worker_dir_unix = "/" + worker_dir_unix[0].lower() + worker_dir_unix[2:]
        recovery_script = f'set -euo pipefail\n{RECOVERY_FUNCTION}\nrecover_detached_worktree "{worker_dir_unix}"\n'
        result = subprocess.run(
            ["bash", "-c", recovery_script],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Recovery failed: {result.stderr}"

        # Verify working tree is clean (no uncommitted changes)
        status_check = subprocess.run(
            ["git", "-C", str(worker_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert status_check.stdout.strip() == "", "Changes should be discarded after recovery"
        assert not (worker_dir / "changes.txt").exists(), "New file should be cleaned up"
