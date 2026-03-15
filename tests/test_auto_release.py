"""Tests for lib/auto_release.py — semantic version bump on SPIRAL completion."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from auto_release import (
    BUMP_MAJOR,
    BUMP_MINOR,
    BUMP_NONE,
    BUMP_PATCH,
    Commit,
    _classify_bump,
    _last_version_tag,
    _next_version,
    _write_changelog,
    main,
)


# ── _classify_bump ────────────────────────────────────────────────────────────


class TestClassifyBump:
    def test_feat_yields_minor(self):
        commits = [Commit(sha="abc1234", subject="feat: add new thing", body="")]
        assert _classify_bump(commits) == BUMP_MINOR

    def test_fix_yields_patch(self):
        commits = [Commit(sha="abc1234", subject="fix: correct typo", body="")]
        assert _classify_bump(commits) == BUMP_PATCH

    def test_perf_yields_patch(self):
        commits = [Commit(sha="abc1234", subject="perf: faster query", body="")]
        assert _classify_bump(commits) == BUMP_PATCH

    def test_breaking_bang_yields_major(self):
        commits = [Commit(sha="abc1234", subject="feat!: remove old API", body="")]
        assert _classify_bump(commits) == BUMP_MAJOR

    def test_breaking_footer_yields_major(self):
        body = "BREAKING CHANGE: old param removed"
        commits = [Commit(sha="abc1234", subject="fix: remove param", body=body)]
        assert _classify_bump(commits) == BUMP_MAJOR

    def test_chore_does_not_bump(self):
        commits = [Commit(sha="abc1234", subject="chore: update deps", body="")]
        assert _classify_bump(commits) == BUMP_NONE

    def test_docs_does_not_bump(self):
        commits = [Commit(sha="abc1234", subject="docs: update readme", body="")]
        assert _classify_bump(commits) == BUMP_NONE

    def test_feat_beats_fix(self):
        commits = [
            Commit(sha="abc1234", subject="fix: patch thing", body=""),
            Commit(sha="def5678", subject="feat: new feature", body=""),
        ]
        assert _classify_bump(commits) == BUMP_MINOR

    def test_breaking_beats_feat(self):
        commits = [
            Commit(sha="abc1234", subject="feat: new feature", body=""),
            Commit(sha="def5678", subject="fix!: breaking fix", body=""),
        ]
        assert _classify_bump(commits) == BUMP_MAJOR

    def test_empty_commits_no_bump(self):
        assert _classify_bump([]) == BUMP_NONE

    def test_refactor_yields_patch(self):
        commits = [Commit(sha="abc1234", subject="refactor: clean up module", body="")]
        assert _classify_bump(commits) == BUMP_PATCH


# ── _next_version ─────────────────────────────────────────────────────────────


class TestNextVersion:
    def test_minor_bump_from_tag(self):
        assert _next_version("v1.2.3", BUMP_MINOR) == "1.3.0"

    def test_patch_bump_from_tag(self):
        assert _next_version("v1.2.3", BUMP_PATCH) == "1.2.4"

    def test_major_bump_from_tag(self):
        assert _next_version("v1.2.3", BUMP_MAJOR) == "2.0.0"

    def test_first_minor_release(self):
        assert _next_version(None, BUMP_MINOR) == "0.1.0"

    def test_first_patch_release(self):
        assert _next_version(None, BUMP_PATCH) == "0.0.1"

    def test_first_major_release(self):
        assert _next_version(None, BUMP_MAJOR) == "1.0.0"

    def test_tag_without_leading_v(self):
        assert _next_version("1.0.0", BUMP_PATCH) == "1.0.1"


# ── _write_changelog ──────────────────────────────────────────────────────────


class TestWriteChangelog:
    def test_creates_new_changelog(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        commits = [Commit(sha="abc1234", subject="feat: new thing", body="")]
        _write_changelog(cl, "1.1.0", commits, ["Story A"])
        content = cl.read_text()
        assert "## [1.1.0]" in content
        assert "Story A" in content
        assert "abc1234" in content
        assert "new thing" in content

    def test_prepends_to_existing_changelog(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        cl.write_text("# Changelog\n\n## [1.0.0] - 2025-01-01\n\n- old entry\n")
        commits = [Commit(sha="def5678", subject="fix: something", body="")]
        _write_changelog(cl, "1.0.1", commits, [])
        content = cl.read_text()
        # New section should appear before old section
        assert content.index("## [1.0.1]") < content.index("## [1.0.0]")

    def test_no_releasable_commits_section_still_written(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        commits = [Commit(sha="aaa1111", subject="chore: boring", body="")]
        _write_changelog(cl, "0.1.0", commits, ["Story X"])
        content = cl.read_text()
        assert "## [0.1.0]" in content
        assert "Story X" in content

    def test_multiple_commit_types_grouped(self, tmp_path):
        cl = tmp_path / "CHANGELOG.md"
        commits = [
            Commit(sha="aaa1111", subject="feat: feature one", body=""),
            Commit(sha="bbb2222", subject="fix: bug fix", body=""),
            Commit(sha="ccc3333", subject="perf: faster", body=""),
        ]
        _write_changelog(cl, "2.0.0", commits, [])
        content = cl.read_text()
        assert "### Features" in content
        assert "### Bug Fixes" in content
        assert "### Performance" in content


# ── main() integration (uses a real git repo in tmp_path) ────────────────────


def _init_git_repo(path: Path) -> None:
    """Create a bare git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "chore: initial commit"],
        check=True, capture_output=True,
    )


def _make_prd(path: Path, n_passed: int = 2) -> Path:
    stories = [
        {"id": f"US-{i:03d}", "title": f"Story {i}", "passes": True}
        for i in range(n_passed)
    ]
    prd = {"userStories": stories}
    prd_path = path / "prd.json"
    prd_path.write_text(json.dumps(prd))
    return prd_path


class TestMainIntegration:
    def test_no_releasable_commits_exits_2(self, tmp_path):
        _init_git_repo(tmp_path)
        prd = _make_prd(tmp_path)
        rc = main(["--prd", str(prd), "--repo", str(tmp_path)])
        assert rc == 2

    def test_feat_commit_creates_minor_tag(self, tmp_path):
        _init_git_repo(tmp_path)
        # Add a feat commit
        (tmp_path / "feat.txt").write_text("new feature")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "feat: add new feature"],
            check=True, capture_output=True,
        )
        prd = _make_prd(tmp_path)
        rc = main(["--prd", str(prd), "--repo", str(tmp_path)])
        assert rc == 0
        # Check tag exists
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "tag", "-l", "v*"],
            capture_output=True, text=True,
        )
        assert "v0.1.0" in result.stdout

    def test_fix_commit_creates_patch_tag(self, tmp_path):
        _init_git_repo(tmp_path)
        # Tag v1.0.0 first
        subprocess.run(
            ["git", "-C", str(tmp_path), "tag", "-a", "v1.0.0", "-m", "initial"],
            check=True, capture_output=True,
        )
        (tmp_path / "fix.txt").write_text("fix")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "fix: correct a bug"],
            check=True, capture_output=True,
        )
        prd = _make_prd(tmp_path)
        rc = main(["--prd", str(prd), "--repo", str(tmp_path)])
        assert rc == 0
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "tag", "-l", "v*"],
            capture_output=True, text=True,
        )
        assert "v1.0.1" in result.stdout

    def test_dry_run_does_not_create_tag(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "feat: something"],
            check=True, capture_output=True,
        )
        prd = _make_prd(tmp_path)
        rc = main(["--prd", str(prd), "--repo", str(tmp_path), "--dry-run"])
        assert rc == 0
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "tag", "-l", "v*"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == ""

    def test_changelog_updated_on_success(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "x.txt").write_text("x")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "feat: cool feature"],
            check=True, capture_output=True,
        )
        prd = _make_prd(tmp_path, n_passed=3)
        rc = main(["--prd", str(prd), "--repo", str(tmp_path)])
        assert rc == 0
        cl = (tmp_path / "CHANGELOG.md").read_text()
        assert "## [0.1.0]" in cl
        assert "Story 0" in cl
        assert "Story 1" in cl
        assert "cool feature" in cl
