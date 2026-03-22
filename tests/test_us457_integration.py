"""
Integration tests for US-457: Verify SPIRAL hook and worktree protection guards.

Tests the shell hooks that protect SPIRAL system files from being modified
by Ralph workers. Uses subprocess to invoke the hooks with controlled inputs.

Test file: tests/test_us457_integration.py
Run with: uv run pytest tests/test_us457_integration.py -v
"""

import json
import subprocess
from pathlib import Path

import pytest

# Type alias for better readability
PathOrNone = Path | None


@pytest.fixture
def hook_script() -> Path:
    """Get path to protect-spiral-files.sh hook."""
    hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "protect-spiral-files.sh"
    assert hook_path.exists(), f"Hook script not found at {hook_path}"
    return hook_path


@pytest.fixture
def project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def run_hook(hook_path: Path, file_path: str, cwd: PathOrNone = None) -> tuple[int, str, str]:
    """
    Run the protect-spiral-files.sh hook with a file path.

    Args:
        hook_path: Path to the hook script
        file_path: File path to test
        cwd: Working directory for the command (defaults to project root)

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    tool_input = {"tool_input": {"file_path": file_path}}
    input_json = json.dumps(tool_input)

    # Use relative path from project root for better bash compatibility
    if cwd is None:
        cwd = Path(__file__).parent.parent

    # Make hook path relative to cwd
    try:
        hook_relative = hook_path.relative_to(cwd)
    except ValueError:
        hook_relative = hook_path

    hook_path_str = str(hook_relative).replace("\\", "/")

    result = subprocess.run(
        ["bash", hook_path_str],
        input=input_json,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(cwd),
    )

    return result.returncode, result.stdout, result.stderr


class TestProtectSpiralFilesHappyPath:
    """Happy-path tests: protected files are blocked."""

    def test_happy_blocks_spiral_sh(self, hook_script: Path) -> None:
        """Protected file spiral.sh should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, "spiral.sh")
        assert exit_code == 2, f"Expected exit 2, got {exit_code}"
        assert "BLOCKED" in stderr, f"Expected BLOCKED in stderr, got: {stderr}"
        assert "spiral.sh" in stderr, f"Expected spiral.sh in stderr, got: {stderr}"

    def test_happy_blocks_spiral_config_sh(self, hook_script: Path) -> None:
        """Protected file spiral.config.sh should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, "spiral.config.sh")
        assert exit_code == 2
        assert "BLOCKED" in stderr

    def test_happy_blocks_prd_json(self, hook_script: Path) -> None:
        """Protected file prd.json should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, "prd.json")
        assert exit_code == 2
        assert "BLOCKED" in stderr
        assert "prd.json" in stderr

    def test_happy_blocks_ralph_sh(self, hook_script: Path) -> None:
        """Protected file ralph/ralph.sh should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, "ralph/ralph.sh")
        assert exit_code == 2
        assert "BLOCKED" in stderr

    def test_happy_blocks_spiral_directory(self, hook_script: Path) -> None:
        """Files in .spiral/ directory should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, ".spiral/_checkpoint.json")
        assert exit_code == 2
        assert "BLOCKED" in stderr
        assert ".spiral/" in stderr

    def test_happy_blocks_nested_spiral_path(self, hook_script: Path) -> None:
        """Nested paths in .spiral/ should be blocked with exit 2."""
        exit_code, stdout, stderr = run_hook(hook_script, ".spiral/worktrees/worker-1/log")
        assert exit_code == 2
        assert "BLOCKED" in stderr


class TestProtectSpiralFilesEdgeCases:
    """Edge-case tests: non-protected files and invalid inputs."""

    def test_edge_allows_lib_file(self, hook_script: Path) -> None:
        """Non-protected lib file should be allowed with exit 0."""
        exit_code, stdout, stderr = run_hook(hook_script, "lib/merge_stories.py")
        assert exit_code == 0, f"Expected exit 0, got {exit_code}; stderr: {stderr}"
        assert "BLOCKED" not in stderr

    def test_edge_allows_test_file(self, hook_script: Path) -> None:
        """Non-protected test file should be allowed with exit 0."""
        exit_code, stdout, stderr = run_hook(hook_script, "tests/test_merge.py")
        assert exit_code == 0
        assert "BLOCKED" not in stderr

    def test_edge_allows_ralph_claude_md(self, hook_script: Path) -> None:
        """Non-protected ralph/CLAUDE.md should be allowed (not ralph.sh)."""
        exit_code, stdout, stderr = run_hook(hook_script, "ralph/CLAUDE.md")
        assert exit_code == 0
        assert "BLOCKED" not in stderr

    def test_edge_allows_src_file(self, hook_script: Path) -> None:
        """Non-protected src file should be allowed with exit 0."""
        exit_code, stdout, stderr = run_hook(hook_script, "src/main.py")
        assert exit_code == 0

    def test_edge_allows_progress_txt(self, hook_script: Path) -> None:
        """Non-protected progress.txt should be allowed with exit 0."""
        exit_code, stdout, stderr = run_hook(hook_script, "progress.txt")
        assert exit_code == 0


    def test_edge_strips_leading_dot_slash(self, hook_script: Path) -> None:
        """Leading ./ should be stripped before matching."""
        exit_code, stdout, stderr = run_hook(hook_script, "./prd.json")
        assert exit_code == 2, "Expected protected file to be blocked even with ./"
        assert "BLOCKED" in stderr

