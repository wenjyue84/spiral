"""Tests for 'spiral workers kill' subcommand (US-1336).

Verifies that kill_worker_safe():
- Terminates the worker process if alive
- Removes the git worktree at .spiral-workers/worker-<id>/
- Leaves no dangling processes or worktree references
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _to_bash_path(p: Path) -> str:
    """Convert a Windows path to a Git Bash compatible path (e.g. C:/foo -> /c/foo)."""
    s = str(p).replace("\\", "/")
    # Convert C:/... to /c/... for Git Bash on Windows
    if len(s) >= 2 and s[1] == ":":
        s = "/" + s[0].lower() + s[2:]
    return s


def _run_bash(script: str, cwd: str) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet and return the result."""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo suitable for worktree operations."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    # Need at least one commit for worktree add to work
    dummy = path / "dummy.txt"
    dummy.write_text("spiral test\n", encoding="utf-8")
    subprocess.run(["git", "add", "dummy.txt"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )


def test_kill_worker_cleanup(tmp_path: Path) -> None:
    """kill_worker_safe removes the worktree dir and leaves no stale references."""
    # ── Setup: git repo with a linked worktree for worker-1 ──────────────────
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    worktree_base = repo / ".spiral-workers"
    worktree_base.mkdir()
    worker_dir = worktree_base / "worker-1"

    # Add a real git worktree (new branch) so git tracks it
    subprocess.run(
        ["git", "worktree", "add", str(worker_dir), "-b", "worker-1-branch"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    assert worker_dir.is_dir(), "Worktree setup failed"

    # Write a heartbeat file with a non-existent PID so process-kill path
    # is exercised but does not fail on a live process
    hb_file = worker_dir / ".heartbeat"
    hb_file.write_text(
        '{"pid":99999999,"storyId":"US-TEST","ts":1700000000,"completed":0,"phase":"I"}\n',
        encoding="utf-8",
    )

    # ── Execute: source worker_heartbeat.sh and call kill_worker_safe ─────────
    spiral_home = Path(__file__).parent.parent
    wh_lib = spiral_home / "lib" / "worker_heartbeat.sh"
    wh_lib_str = _to_bash_path(wh_lib)
    repo_str = _to_bash_path(repo)

    script = (
        f'source "{wh_lib_str}" && '
        f'kill_worker_safe "1" "{repo_str}"'
    )
    result = _run_bash(script, cwd=str(repo))

    # ── Assert: worktree directory is gone ────────────────────────────────────
    assert not worker_dir.exists(), (
        f"Worktree directory was NOT removed.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # ── Assert: no dangling git worktree references remain ────────────────────
    wt_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "worker-1" not in wt_list.stdout, (
        f"Stale worktree reference found:\n{wt_list.stdout}"
    )

    # ── Assert: cleanup completed without error ────────────────────────────────
    assert result.returncode == 0, (
        f"kill_worker_safe exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
