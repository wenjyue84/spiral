"""Tests for worktree_health_check() function in lib/impl/commit_revert.sh.

This module tests that the worktree_health_check function is correctly integrated
and can be sourced. Comprehensive integration tests with actual git worktrees are
tested via spiral_events.jsonl observability during Phase I execution.
"""

from pathlib import Path


def test_worktree_health_check_function_exists() -> None:
    """Verify worktree_health_check function is defined in commit_revert.sh."""
    commit_revert_path = Path(__file__).parent.parent / "lib" / "impl" / "commit_revert.sh"
    assert commit_revert_path.exists(), f"commit_revert.sh not found at {commit_revert_path}"

    # Read the file and verify the function definition
    content = commit_revert_path.read_text()
    assert "worktree_health_check()" in content, "worktree_health_check function not defined"
    assert "git -C" in content, "Function should use git -C"
    assert "git checkout -B" in content, "Function should have auto-repair logic"
    assert "spiral-worker" not in content or "expected_branch" in content, (
        "Function should accept expected_branch as parameter, not hardcode branch names"
    )


def test_run_parallel_ralph_sources_commit_revert() -> None:
    """Verify run_parallel_ralph.sh sources commit_revert.sh."""
    run_parallel_path = Path(__file__).parent.parent / "lib" / "run_parallel_ralph.sh"
    assert run_parallel_path.exists(), f"run_parallel_ralph.sh not found at {run_parallel_path}"

    content = run_parallel_path.read_text(encoding="utf-8")
    assert "lib/impl/commit_revert.sh" in content, "run_parallel_ralph.sh should source commit_revert.sh"
    assert "source" in content and "commit_revert.sh" in content, (
        "Should have explicit source statement for commit_revert.sh"
    )


def test_launch_worker_calls_health_check() -> None:
    """Verify _launch_worker_i() calls worktree_health_check before executing ralph."""
    run_parallel_path = Path(__file__).parent.parent / "lib" / "run_parallel_ralph.sh"
    assert run_parallel_path.exists()

    content = run_parallel_path.read_text(encoding="utf-8")

    # Verify health check is called
    assert "worktree_health_check" in content, "run_parallel_ralph.sh should call worktree_health_check"

    # Verify it's called in _launch_worker_i (look for the function definition)
    assert "_launch_worker_i() {" in content, "Should define _launch_worker_i function"

    # Find the function definition and verify health check is after cd "$WTREE"
    func_start = content.find("_launch_worker_i() {")
    assert func_start > 0, "Should find _launch_worker_i function definition"

    # Get next 8000 chars to include function body
    func_body = content[func_start : func_start + 8000]

    # Verify cd "$WTREE" comes before worktree_health_check
    cd_wtree = func_body.find('cd "$WTREE"')
    health_check = func_body.find("worktree_health_check")
    assert cd_wtree > 0, "Should find cd to WTREE"
    assert health_check > 0, "Should find worktree_health_check call"
    assert cd_wtree < health_check, "Should cd to WTREE before calling health check"


def test_restart_stalled_worker_calls_health_check() -> None:
    """Verify _restart_stalled_worker() calls worktree_health_check."""
    run_parallel_path = Path(__file__).parent.parent / "lib" / "run_parallel_ralph.sh"
    assert run_parallel_path.exists()

    content = run_parallel_path.read_text(encoding="utf-8")

    # Find _restart_stalled_worker function
    func_start = content.find("_restart_stalled_worker()")
    assert func_start >= 0, "Should define _restart_stalled_worker function"

    # Extract function body (next 4000 chars should contain the entire function)
    func_body = content[func_start : func_start + 4000]

    # Verify health check is called in this function too
    assert "worktree_health_check" in func_body, "worktree_health_check should be called within _restart_stalled_worker"


def test_health_check_expected_branch_parameter() -> None:
    """Verify worktree_health_check is called with correct branch parameter pattern."""
    run_parallel_path = Path(__file__).parent.parent / "lib" / "run_parallel_ralph.sh"
    content = run_parallel_path.read_text(encoding="utf-8")

    # Should pass spiral-worker-${i} or spiral-worker-${worker_num}
    assert "spiral-worker-" in content or "worker_id" in content or "worker_num" in content, (
        "Should reference worker ID to form expected branch name"
    )

    # Verify the pattern worktree_health_check WTREE EXPECTED_BRANCH
    assert "worktree_health_check" in content, "Should call worktree_health_check"

    # Count occurrences - should be at least 2 (one in _launch_worker_i, one in _restart_stalled_worker)
    count = content.count("worktree_health_check")
    assert count >= 2, f"worktree_health_check should be called at least 2 times, found {count}"
