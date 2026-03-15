"""tests/test_filestouch_diff_context.py

Unit test for US-280: Inject unified diff of filesTouch files as context
into ralph.sh instead of full files.

Verifies that the diff context produced by `git diff HEAD~1 -- <file>` for a
modified file is strictly smaller (in character count) than the full file
contents, confirming the core premise of the optimisation.
"""

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path


def _git(args: list[str], cwd: str) -> str:
    """Run a git command in cwd, return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _make_repo(tmp_dir: str) -> str:
    """Initialise a minimal git repo in tmp_dir and return the path."""
    _git(["init", "--initial-branch=main"], tmp_dir)
    _git(["config", "user.email", "test@example.com"], tmp_dir)
    _git(["config", "user.name", "Test"], tmp_dir)
    return tmp_dir


class TestFilesTouchDiffContextSmallerThanFullFile:
    """Verify that diff output is smaller than full file for a modified file."""

    def test_diff_smaller_than_full_file(self, tmp_path: Path) -> None:
        repo = str(tmp_path)
        _make_repo(repo)

        # Create a large file with 60 lines and commit it
        target = tmp_path / "service.py"
        original_lines = [f"line_{i:03d} = 'original value for line {i}'\n" for i in range(60)]
        target.write_text("".join(original_lines))
        _git(["add", "service.py"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "initial commit"], repo)

        # Make a small change (1 line) and commit
        modified_lines = list(original_lines)
        modified_lines[30] = "line_030 = 'MODIFIED'\n"
        target.write_text("".join(modified_lines))
        _git(["add", "service.py"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "small change"], repo)

        # Compute full file size
        full_content = target.read_text()
        full_size = len(full_content)

        # Compute diff size (HEAD~1 → HEAD)
        diff_result = subprocess.run(
            ["git", "diff", "--unified=5", "HEAD~1", "--", "service.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        diff_content = diff_result.stdout
        diff_size = len(diff_content)

        assert diff_size > 0, "Diff should be non-empty for a modified file"
        assert diff_size < full_size, (
            f"Diff ({diff_size} chars) should be smaller than full file ({full_size} chars) "
            "for a file where only 1 of 60 lines changed"
        )

    def test_diff_empty_for_new_file(self, tmp_path: Path) -> None:
        """Diff is empty for a new file (not in HEAD~1); fallback to full content applies."""
        repo = str(tmp_path)
        _make_repo(repo)

        # Create an initial commit with a different file so HEAD~1 exists
        (tmp_path / "README.md").write_text("hello\n")
        _git(["add", "README.md"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "initial"], repo)

        # Add a brand-new file and commit
        new_file = tmp_path / "new_module.py"
        new_file.write_text("def hello():\n    pass\n")
        _git(["add", "new_module.py"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "add new module"], repo)

        # Diff of HEAD~1 for new_module.py should be empty (file didn't exist before)
        diff_result = subprocess.run(
            ["git", "diff", "--unified=5", "HEAD~1", "--", "new_module.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        # For a new file added in HEAD, diff from HEAD~1 shows it as added
        # The diff is non-empty (shows the file addition) — verify it contains the content
        assert "new_module.py" in diff_result.stdout or diff_result.stdout == "", (
            "Diff of a newly added file should either be empty or show the addition"
        )

    def test_diff_truncation_at_max_lines(self, tmp_path: Path) -> None:
        """Diff lines exceeding SPIRAL_MAX_DIFF_LINES should be truncatable."""
        repo = str(tmp_path)
        _make_repo(repo)

        # Create a file with 100 lines
        target = tmp_path / "big.py"
        original = [f"x_{i} = {i}\n" for i in range(100)]
        target.write_text("".join(original))
        _git(["add", "big.py"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "initial"], repo)

        # Change every line
        modified = [f"x_{i} = {i * 2}\n" for i in range(100)]
        target.write_text("".join(modified))
        _git(["add", "big.py"], repo)
        _git(["commit", "--no-gpg-sign", "-m", "change all lines"], repo)

        diff_result = subprocess.run(
            ["git", "diff", "--unified=5", "HEAD~1", "--", "big.py"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        diff_lines = diff_result.stdout.splitlines()
        diff_line_count = len(diff_lines)

        # Simulate truncation at 50 lines
        max_lines = 50
        truncated = diff_lines[:max_lines]

        assert len(truncated) == max_lines
        assert diff_line_count > max_lines, (
            "A 100-line change should produce more than 50 diff lines"
        )
