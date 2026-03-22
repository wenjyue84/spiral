"""Integration tests for Phase G: Deploy CHANGELOG and pdoc outputs to gh-pages (US-732).

Tests verify:
  AC1: prepare_changelog_output() creates .spiral/changelog-output/ with
       CHANGELOG.md and pdoc/index.html
  AC2: deploy_to_gh_pages() creates an isolated git worktree, copies outputs,
       commits to the target branch without force push (--dry-run mode used in tests)
  AC3: After Phase G, gh-pages branch has docs/index.html and CHANGELOG.md
       with 3+ story entries
"""

from __future__ import annotations

import json
import subprocess

# Allow import from lib/commands/
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from commands.deploy_docs import deploy_to_gh_pages, prepare_changelog_output

# ── Helpers ────────────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a git repo with one commit so worktrees can be created."""
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(["init"], repo_path)
    _git(["config", "user.email", "test@test.com"], repo_path)
    _git(["config", "user.name", "Test User"], repo_path)
    # Initial commit required so worktree commands work
    (repo_path / "README.md").write_text("# Test\n", encoding="utf-8")
    _git(["add", "README.md"], repo_path)
    _git(["commit", "-m", "chore: initial commit"], repo_path)


def _make_prd_with_stories(spiral_home: Path, count: int = 4) -> Path:
    """Write a minimal prd.json with `count` passing stories."""
    prd = {
        "schemaVersion": 1,
        "projectName": "Test",
        "productName": "Test Product",
        "branchName": "main",
        "description": "test prd",
        "userStories": [
            {
                "id": f"US-{i:03d}",
                "title": f"Story {i} title",
                "description": f"Story {i} description",
                "passes": True,
            }
            for i in range(1, count + 1)
        ],
    }
    prd_path = spiral_home / "prd.json"
    prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return prd_path


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "spiral_test_repo"
    _init_git_repo(repo)
    return repo


# ── AC1: prepare_changelog_output creates correct directory structure ──────────


class TestPrepareChangelogOutput:
    """prepare_changelog_output() stages CHANGELOG.md and pdoc/ correctly."""

    def test_creates_changelog_output_dir(self, git_repo: Path) -> None:
        prd_path = _make_prd_with_stories(git_repo)
        out = prepare_changelog_output(git_repo, prd_path)

        assert out == git_repo / ".spiral" / "changelog-output"
        assert out.is_dir()

    def test_changelog_md_present(self, git_repo: Path) -> None:
        prd_path = _make_prd_with_stories(git_repo)
        out = prepare_changelog_output(git_repo, prd_path)

        assert (out / "CHANGELOG.md").exists()

    def test_pdoc_index_html_present(self, git_repo: Path) -> None:
        prd_path = _make_prd_with_stories(git_repo)
        out = prepare_changelog_output(git_repo, prd_path)

        assert (out / "pdoc" / "index.html").exists()

    def test_copies_existing_changelog(self, git_repo: Path) -> None:
        """If CHANGELOG.md already exists in project root, it is copied as-is."""
        (git_repo / "CHANGELOG.md").write_text(
            "# My Changelog\n\n## v1.0\n\n- feat: US-001 first entry\n",
            encoding="utf-8",
        )
        prd_path = _make_prd_with_stories(git_repo)
        out = prepare_changelog_output(git_repo, prd_path)

        content = (out / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "My Changelog" in content

    def test_copies_pdoc_html_files(self, git_repo: Path) -> None:
        """If .spiral/docs/api/ exists and has HTML, files are copied to pdoc/."""
        api_dir = git_repo / ".spiral" / "docs" / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "index.html").write_text("<html><body>API</body></html>", encoding="utf-8")
        (api_dir / "module.html").write_text("<html><body>Module</body></html>", encoding="utf-8")

        prd_path = _make_prd_with_stories(git_repo)
        out = prepare_changelog_output(git_repo, prd_path)

        assert (out / "pdoc" / "index.html").exists()
        assert (out / "pdoc" / "module.html").exists()

    def test_generates_changelog_from_prd_when_missing(self, git_repo: Path) -> None:
        """If CHANGELOG.md doesn't exist, it is generated from prd.json stories."""
        prd_path = _make_prd_with_stories(git_repo, count=4)
        out = prepare_changelog_output(git_repo, prd_path)

        content = (out / "CHANGELOG.md").read_text(encoding="utf-8")
        # Should contain story IDs from the PRD
        assert "US-001" in content
        assert "US-002" in content


# ── AC2: deploy_to_gh_pages uses worktree and commits without force push ───────


class TestDeployToGhPages:
    """deploy_to_gh_pages() creates isolated worktree, commits, no force push."""

    def test_dry_run_commits_without_push(self, git_repo: Path) -> None:
        """--dry-run commits to branch but does not push."""
        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)

        # Should not raise (no remote needed in dry-run)
        deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

        # Branch exists locally after dry-run
        branches = _git(["branch", "--list", "gh-pages"], git_repo)
        assert "gh-pages" in branches

    def test_worktree_is_cleaned_up(self, git_repo: Path) -> None:
        """Worktree directory is removed after deploy_to_gh_pages completes."""
        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)

        wt_dir = git_repo / ".spiral" / "workers" / "gh-pages-deploy"
        deploy_to_gh_pages(git_repo, branch="gh-pages", worktree_dir=wt_dir, dry_run=True)

        assert not wt_dir.exists(), "Worktree directory should be cleaned up after deploy"

    def test_output_dir_missing_raises(self, git_repo: Path) -> None:
        """RuntimeError is raised when .spiral/changelog-output/ is missing."""
        with pytest.raises(RuntimeError, match="Source directory not found"):
            deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

    def test_no_force_push_in_deploy(self, git_repo: Path) -> None:
        """Verify the implementation never calls git push --force."""
        import unittest.mock as mock

        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)

        push_calls: list[list[str]] = []

        original_run = subprocess.run

        def capturing_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
            if isinstance(cmd, list) and "push" in cmd:
                push_calls.append(cmd)
            return original_run(cmd, **kwargs)

        with mock.patch("commands.deploy_docs.subprocess.run", side_effect=capturing_run):
            try:
                deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)
            except Exception:
                pass  # dry-run may skip push — that's fine

        # If any push calls happened, none should have --force
        for call in push_calls:
            assert "--force" not in call, f"Force push detected in: {call}"
            assert "-f" not in call, f"Force push detected in: {call}"


# ── AC3: gh-pages branch has docs/index.html and CHANGELOG.md with 3+ entries ─


class TestGhPagesBranchContent:
    """After Phase G, gh-pages branch has valid structure and CHANGELOG content."""

    def test_gh_pages_has_docs_index_html(self, git_repo: Path) -> None:
        """gh-pages branch contains docs/index.html after deployment."""
        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)
        deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

        # Read docs/index.html from gh-pages branch
        result = subprocess.run(
            ["git", "show", "gh-pages:docs/index.html"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "docs/index.html not found on gh-pages branch"
        assert "<html" in result.stdout.lower() or "html" in result.stdout.lower()

    def test_gh_pages_has_changelog_md(self, git_repo: Path) -> None:
        """gh-pages branch contains CHANGELOG.md after deployment."""
        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)
        deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

        result = subprocess.run(
            ["git", "show", "gh-pages:CHANGELOG.md"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "CHANGELOG.md not found on gh-pages branch"

    def test_changelog_has_3_plus_story_entries(self, git_repo: Path) -> None:
        """CHANGELOG.md on gh-pages has 3+ story entries from prd.json."""
        prd_path = _make_prd_with_stories(git_repo, count=4)
        prepare_changelog_output(git_repo, prd_path)
        deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

        result = subprocess.run(
            ["git", "show", "gh-pages:CHANGELOG.md"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        # Count story ID entries (US-NNN patterns)
        import re

        story_entries = re.findall(r"US-\d+", result.stdout)
        assert len(story_entries) >= 3, (
            f"Expected 3+ story entries in CHANGELOG.md, got {len(story_entries)}:\n{result.stdout}"
        )

    def test_gh_pages_has_nojekyll(self, git_repo: Path) -> None:
        """.nojekyll is committed to gh-pages to disable Jekyll processing."""
        prd_path = _make_prd_with_stories(git_repo)
        prepare_changelog_output(git_repo, prd_path)
        deploy_to_gh_pages(git_repo, branch="gh-pages", dry_run=True)

        result = subprocess.run(
            ["git", "show", "gh-pages:.nojekyll"],
            cwd=str(git_repo),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, ".nojekyll not found on gh-pages branch"
