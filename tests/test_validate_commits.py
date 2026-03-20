"""Tests for lib/validate_commits.py — Orphan Stories & Squash-Commit Detection (US-554)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing from repo root and lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from validate_commits import _extract_story_ids, validate_commits  # noqa: E402

MAIN_PY = str(Path(__file__).parent.parent / "main.py")


def _make_prd(tmp_path: Path, stories: list[dict]) -> Path:
    """Write a minimal prd.json to tmp_path and return its path."""
    prd = {"schemaVersion": 1, "productName": "Test", "userStories": stories}
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd), encoding="utf-8")
    return prd_path


# ── Unit: story ID extraction ────────────────────────────────────────────────


class TestExtractStoryIds:
    def test_us_pattern(self):
        assert _extract_story_ids("feat(US-123): add widget") == ["US-123"]

    def test_ut_pattern(self):
        assert _extract_story_ids("fix(UT-42): test flake") == ["UT-42"]

    def test_multiple_ids(self):
        ids = _extract_story_ids("US-1 US-2 UT-3")
        assert ids == ["US-1", "US-2", "UT-3"]

    def test_no_match(self):
        assert _extract_story_ids("just a normal commit message") == []


# ── Orphan detection ─────────────────────────────────────────────────────────


class TestOrphanDetection:
    def test_orphan_stories_detected(self, tmp_path: Path):
        """Stories that passed but have no matching commit should appear as orphans."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-100", "passes": True},
                {"id": "US-200", "passes": True},
                {"id": "US-300", "passes": False},  # not passed, should be ignored
            ],
        )
        # Only US-200 has a matching commit
        git_log = [
            {"hash": "aaa111", "message": "feat(US-200): implement widget"},
            {"hash": "bbb222", "message": "chore: unrelated cleanup"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert "US-100" in result["orphans"]
        assert "US-200" not in result["orphans"]
        assert "US-300" not in result["orphans"]  # not in passed set at all

    def test_no_orphans_when_all_have_commits(self, tmp_path: Path):
        """When every passed story has at least one commit, orphans list is empty."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-10", "passes": True},
                {"id": "US-20", "passes": True},
            ],
        )
        git_log = [
            {"hash": "aaa111", "message": "feat(US-10): thing one"},
            {"hash": "bbb222", "message": "feat(US-20): thing two"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert result["orphans"] == []
        assert result["total_stories"] == 2


# ── Squash-commit pattern detection ──────────────────────────────────────────


class TestSquashPatternDetection:
    def test_squash_commit_flagged(self, tmp_path: Path):
        """A commit referencing 2+ stories should appear in squash_patterns."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-1", "passes": True},
                {"id": "US-2", "passes": True},
            ],
        )
        git_log = [
            {"hash": "ccc333", "message": "feat: implement US-1 and US-2 together"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert len(result["squash_patterns"]) == 1
        sp = result["squash_patterns"][0]
        assert sp["commit"] == "ccc333"
        assert "US-1" in sp["stories"]
        assert "US-2" in sp["stories"]

    def test_single_story_commit_not_flagged(self, tmp_path: Path):
        """A commit with only one story ID should NOT appear as a squash pattern."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-5", "passes": True},
            ],
        )
        git_log = [
            {"hash": "ddd444", "message": "feat(US-5): solo implementation"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert result["squash_patterns"] == []

    def test_duplicate_ids_in_commit_not_false_positive(self, tmp_path: Path):
        """Duplicate mentions of the same story ID should not be a squash pattern."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-7", "passes": True},
            ],
        )
        git_log = [
            {"hash": "eee555", "message": "fix(US-7): part 1 of US-7 refactor"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert result["squash_patterns"] == []


# ── Exit code behaviour ──────────────────────────────────────────────────────


class TestExitCode:
    def test_no_orphans_returns_exit_zero(self, tmp_path: Path):
        """validate_commits with no orphans should lead to exit code 0."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-1", "passes": True},
            ],
        )
        git_log = [
            {"hash": "fff666", "message": "feat(US-1): done"},
        ]

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        # The caller (main.py) uses orphans to decide exit code
        assert result["orphans"] == []
        # Simulate exit code logic
        exit_code = 1 if result["orphans"] else 0
        assert exit_code == 0

    def test_orphans_returns_exit_one(self, tmp_path: Path):
        """validate_commits with orphans should lead to exit code 1."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-1", "passes": True},
            ],
        )
        git_log = []  # no commits at all

        result = validate_commits(prd_path=prd_path, git_log=git_log)

        assert len(result["orphans"]) == 1
        exit_code = 1 if result["orphans"] else 0
        assert exit_code == 1


# ── CLI JSON output format ───────────────────────────────────────────────────


class TestCLIJsonOutput:
    def test_cli_json_output_format(self, tmp_path: Path):
        """Running via main.py validate-commits --json should produce valid JSON with expected keys."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-50", "passes": True},
                {"id": "US-51", "passes": True},
            ],
        )
        # Create a minimal git repo so git log works
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
        (tmp_path / "README.md").write_text("init")
        subprocess.run(
            ["git", "add", "."],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat(US-50): initial implementation"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                MAIN_PY,
                "validate-commits",
                "--json",
                "--prd",
                str(prd_path),
                "--repo",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Output is not valid JSON: {exc}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}")

        # Validate expected keys
        assert "orphans" in data
        assert "squash_patterns" in data
        assert "stories_with_commits" in data
        assert "total_stories" in data
        assert "total_commits_scanned" in data

        # US-50 has a commit, US-51 does not
        assert "US-51" in data["orphans"]
        assert "US-50" not in data["orphans"]

        # Exit code 1 because there is an orphan
        assert result.returncode == 1

    def test_cli_exit_zero_when_clean(self, tmp_path: Path):
        """CLI exits 0 when no orphans are detected."""
        prd_path = _make_prd(
            tmp_path,
            [
                {"id": "US-60", "passes": True},
            ],
        )
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
        (tmp_path / "README.md").write_text("init")
        subprocess.run(
            ["git", "add", "."],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat(US-60): all done"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            [
                sys.executable,
                MAIN_PY,
                "validate-commits",
                "--json",
                "--prd",
                str(prd_path),
                "--repo",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["orphans"] == []
