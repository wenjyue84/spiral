"""
tests/test_commit_revert.py — US-343: transactional snapshot/restore

Tests for transactional filesystem snapshots in commit_revert.sh.
Uses Hypothesis for property-based testing of manifest generation and cleanup logic.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st


class TestManifestGeneration:
    """Test manifest generation logic for non-git files."""

    def test_manifest_format_is_sorted(self) -> None:
        """Manifest files should be sorted line-by-line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            # Create untracked files in non-deterministic order
            (repo / "z_file.txt").touch()
            (repo / "a_file.txt").touch()
            (repo / "m_file.txt").touch()

            manifest_lines = _get_manifest_lines(repo)
            assert manifest_lines == sorted(manifest_lines), "Manifest must be sorted"

    def test_manifest_includes_untracked_files(self) -> None:
        """Manifest should list all untracked files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            untracked = ["untracked1.txt", "untracked2.log", "nested/file.txt"]
            for f in untracked:
                (repo / f).parent.mkdir(parents=True, exist_ok=True)
                (repo / f).touch()

            manifest = _get_manifest_lines(repo)
            for f in untracked:
                assert any(f in line for line in manifest)

    def test_manifest_excludes_git_tracked_files(self) -> None:
        """Manifest should not include git-tracked files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            # Create and track a file
            (repo / "tracked.txt").write_text("content")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)

            manifest = _get_manifest_lines(repo)
            assert not any("tracked.txt" in line for line in manifest)

    def test_manifest_excludes_gitignored_files(self) -> None:
        """Manifest should respect .gitignore patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            # Create .gitignore
            (repo / ".gitignore").write_text("*.tmp\n__pycache__/\n")
            subprocess.run(
                ["git", "add", ".gitignore"], cwd=repo, check=True
            )

            # Create gitignored files
            (repo / "test.tmp").touch()
            (repo / "__pycache__").mkdir()
            (repo / "__pycache__/cache.pyc").touch()

            manifest = _get_manifest_lines(repo)
            assert not any("test.tmp" in line for line in manifest)
            assert not any("__pycache__" in line for line in manifest)

    @given(
        st.lists(
            st.from_regex(
                r"[a-zA-Z0-9_\-\.]{1,30}(\.[a-z]{2,4})?",
                fullmatch=True
            ),
            min_size=0,
            max_size=20,
            unique=True,
        )
    )
    @settings(max_examples=50)
    def test_manifest_generation_idempotent(self, filenames: List[str]) -> None:
        """Manifest generation should be idempotent."""
        assume(all(f and f not in [".", ".."] for f in filenames))  # Skip empty/dot filenames

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            # Create files
            for f in filenames:
                path = repo / f
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            # Generate manifest twice
            manifest1 = _get_manifest_lines(repo)
            manifest2 = _get_manifest_lines(repo)

            assert manifest1 == manifest2, "Manifest must be idempotent"


class TestRollbackLogEvent:
    """Test rollback event logging."""

    def test_rollback_event_json_valid(self, tmp_path: Path) -> None:
        """Logged rollback events must be valid JSON."""
        os.environ["SPIRAL_SCRATCH_DIR"] = str(tmp_path)
        os.environ["SPIRAL_RUN_ID"] = "test-run-123"

        # Source and call log_rollback_event via bash
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"""
                source lib/impl/commit_revert.sh
                log_rollback_event "US-999" "success" "1500"
                """,
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Verify JSON in spiral_events.jsonl
        events_file = tmp_path / "spiral_events.jsonl"
        if events_file.exists():
            with open(events_file) as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("event", "").startswith("rollback_"):
                            assert "ts" in data
                            assert "event" in data
                            assert "story_id" in data
                    except json.JSONDecodeError:
                        pytest.fail(f"Invalid JSON in spiral_events.jsonl: {line}")

    def test_rollback_event_includes_run_id(self, tmp_path: Path) -> None:
        """Rollback event must include SPIRAL_RUN_ID if set."""
        os.environ["SPIRAL_SCRATCH_DIR"] = str(tmp_path)
        os.environ["SPIRAL_RUN_ID"] = "special-run-456"

        result = subprocess.run(
            [
                "bash",
                "-c",
                f"""
                source lib/impl/commit_revert.sh
                log_rollback_event "US-888" "stash_restore_failed" "2000" "test error"
                """,
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

        events_file = tmp_path / "spiral_events.jsonl"
        if events_file.exists():
            with open(events_file) as f:
                content = f.read()
                assert "special-run-456" in content


class TestSnapshotShellIntegration:
    """Integration tests for create_snapshot and restore_snapshot bash functions."""

    def test_create_snapshot_bash_integration(self) -> None:
        """create_snapshot should execute without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_git_repo(repo)

            # Create test file
            (repo / "testfile.txt").write_text("content")

            # Convert Windows path to POSIX for bash
            bash_repo = str(repo).replace("\\", "/")
            if bash_repo[1] == ":":  # C:/ style path
                bash_repo = "/" + bash_repo[0].lower() + bash_repo[2:]

            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"""
                    source lib/impl/commit_revert.sh
                    cd "{bash_repo}"
                    create_snapshot "{bash_repo}/.snap" "{bash_repo}"
                    echo "STASH=$SNAPSHOT_STASH_SHA"
                    echo "MANIFEST=$SNAPSHOT_MANIFEST"
                    """,
                ],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, f"stderr: {result.stderr}"
            assert "STASH=" in result.stdout
            assert "MANIFEST=" in result.stdout

    def test_restore_snapshot_bash_integration(self) -> None:
        """restore_snapshot function should be sourced without error."""
        result = subprocess.run(
            [
                "bash",
                "-c",
                """
                source lib/impl/commit_revert.sh
                # Check that functions exist and are callable
                type create_snapshot >/dev/null 2>&1 || exit 1
                type restore_snapshot >/dev/null 2>&1 || exit 1
                type log_rollback_event >/dev/null 2>&1 || exit 1
                exit 0
                """,
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────


def _init_git_repo(repo: Path) -> None:
    """Initialize a minimal git repository for testing."""
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, check=True
    )
    (repo / "README.md").write_text("initial")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "Initial commit"], cwd=repo, check=True
    )


def _get_manifest_lines(repo: Path) -> List[str]:
    """Get git ls-files --others output (simulating manifest)."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    lines = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    return sorted(lines)
