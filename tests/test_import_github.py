"""Tests for lib/import_github.py — GitHub Issues importer."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import import_github as ig  # noqa: E402
import main  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_issue(
    number: int = 1,
    title: str = "Test story",
    body: str = "Description here.",
    milestone_title: str | None = None,
    label_names: list[str] | None = None,
) -> dict:
    return {
        "number": number,
        "title": title,
        "body": body,
        "milestone": {"title": milestone_title} if milestone_title else None,
        "labels": {"nodes": [{"name": n} for n in (label_names or [])]},
    }


def _make_prd(tmp_path: Path, stories: list[dict]) -> Path:
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd), encoding="utf-8")
    return p


# ── Priority extraction ───────────────────────────────────────────────────────

class TestExtractPriority:
    def test_priority_critical_label(self):
        issue = _make_issue(label_names=["priority:critical"])
        assert ig._extract_priority(issue) == "critical"

    def test_priority_high_label(self):
        issue = _make_issue(label_names=["priority:high"])
        assert ig._extract_priority(issue) == "high"

    def test_priority_medium_label(self):
        issue = _make_issue(label_names=["priority:medium"])
        assert ig._extract_priority(issue) == "medium"

    def test_priority_low_label(self):
        issue = _make_issue(label_names=["priority:low"])
        assert ig._extract_priority(issue) == "low"

    def test_priority_from_milestone_high(self):
        issue = _make_issue(milestone_title="High priority milestone")
        assert ig._extract_priority(issue) == "high"

    def test_priority_from_milestone_critical(self):
        issue = _make_issue(milestone_title="Critical fixes")
        assert ig._extract_priority(issue) == "critical"

    def test_priority_defaults_to_medium(self):
        issue = _make_issue(label_names=["bug", "enhancement"])
        assert ig._extract_priority(issue) == "medium"

    def test_label_takes_precedence_over_milestone(self):
        issue = _make_issue(label_names=["priority:low"], milestone_title="High priority")
        assert ig._extract_priority(issue) == "low"


# ── ID generation ─────────────────────────────────────────────────────────────

class TestNextStoryId:
    def test_empty_list_returns_us_1(self):
        assert ig._next_story_id([]) == "US-1"

    def test_increments_from_highest(self):
        stories = [{"id": "US-5"}, {"id": "US-3"}, {"id": "US-10"}]
        assert ig._next_story_id(stories) == "US-11"

    def test_ignores_non_matching_ids(self):
        stories = [{"id": "US-2"}, {"id": "CUSTOM-99"}]
        assert ig._next_story_id(stories) == "US-3"

    def test_handles_missing_id_key(self):
        stories = [{"title": "No ID here"}]
        assert ig._next_story_id(stories) == "US-1"


# ── Issue mapping ─────────────────────────────────────────────────────────────

class TestMapIssueToStory:
    def test_basic_mapping(self):
        issue = _make_issue(number=42, title="Add login", body="Must support OAuth")
        story = ig.map_issue_to_story(issue, set(), "US-10")
        assert story is not None
        assert story["id"] == "US-10"
        assert story["title"] == "Add login"
        assert story["description"] == "Must support OAuth"
        assert story["passes"] is False
        assert story["_githubIssueNumber"] == 42
        assert story["_source"] == "github-import"

    def test_duplicate_returns_none(self):
        issue = _make_issue(title="Existing story")
        result = ig.map_issue_to_story(issue, {"Existing story"}, "US-99")
        assert result is None

    def test_empty_title_returns_none(self):
        issue = _make_issue(title="   ")
        result = ig.map_issue_to_story(issue, set(), "US-1")
        assert result is None

    def test_priority_propagated(self):
        issue = _make_issue(label_names=["priority:high"])
        story = ig.map_issue_to_story(issue, set(), "US-1")
        assert story is not None
        assert story["priority"] == "high"

    def test_title_stripped_of_whitespace(self):
        issue = _make_issue(title="  Trim me  ")
        story = ig.map_issue_to_story(issue, set(), "US-1")
        assert story is not None
        assert story["title"] == "Trim me"


# ── import_github_issues (integration with mocked fetch) ─────────────────────

class TestImportGithubIssues:
    def _mock_fetch(self, issues: list[dict]):
        """Return a mock for ig.fetch_issues that yields *issues*."""
        def _fake_fetch(owner, repo, label, token):
            yield from issues
        return _fake_fetch

    def test_adds_new_stories(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue(number=1, title="Story A"), _make_issue(number=2, title="Story B")]
        with patch.object(ig, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(prd_path), token="tok", dry_run=False,
            )
        assert len(added) == 2
        assert len(skipped) == 0
        data = json.loads(prd_path.read_text())
        assert len(data["userStories"]) == 2

    def test_skips_duplicates(self, tmp_path):
        existing = [{"id": "US-1", "title": "Already here", "passes": True}]
        prd_path = _make_prd(tmp_path, existing)
        issues = [_make_issue(title="Already here"), _make_issue(title="New story")]
        with patch.object(ig, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(prd_path), token="tok", dry_run=False,
            )
        assert len(added) == 1
        assert added[0]["title"] == "New story"
        assert "Already here" in skipped

    def test_dry_run_does_not_write(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue(title="Ghost story")]
        with patch.object(ig, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(prd_path), token="tok", dry_run=True,
            )
        assert len(added) == 1
        # File must be unchanged (empty userStories)
        data = json.loads(prd_path.read_text())
        assert len(data["userStories"]) == 0

    def test_ids_are_sequential(self, tmp_path):
        existing = [{"id": "US-5", "title": "Old", "passes": True}]
        prd_path = _make_prd(tmp_path, existing)
        issues = [_make_issue(title="First new"), _make_issue(title="Second new")]
        with patch.object(ig, "fetch_issues", self._mock_fetch(issues)):
            added, _ = ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(prd_path), token="tok", dry_run=False,
            )
        assert added[0]["id"] == "US-6"
        assert added[1]["id"] == "US-7"

    def test_invalid_repo_format_raises(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        with pytest.raises(ValueError, match="owner/repo"):
            ig.import_github_issues(
                repo="nodash", label="spiral",
                prd_path=str(prd_path), token="tok",
            )

    def test_missing_prd_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(tmp_path / "missing.json"), token="tok",
            )

    def test_empty_issues_returns_empty(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        with patch.object(ig, "fetch_issues", self._mock_fetch([])):
            added, skipped = ig.import_github_issues(
                repo="owner/repo", label="spiral",
                prd_path=str(prd_path), token="tok",
            )
        assert added == []
        assert skipped == []


# ── CLI (main.py import-github) ───────────────────────────────────────────────

class TestCmdImportGithub:
    def _args(self, repo="owner/repo", label="spiral", dry_run=False):
        return SimpleNamespace(repo=repo, label=label, dry_run=dry_run)

    def test_exits_1_without_token(self, tmp_path, capsys):
        with patch.object(main, "PRD_FILE", tmp_path / "prd.json"), \
             patch.dict(os.environ, {}, clear=False):
            env_backup = os.environ.pop("GITHUB_TOKEN", None)
            try:
                with pytest.raises(SystemExit) as exc:
                    main.cmd_import_github(self._args())
                assert exc.value.code == 1
            finally:
                if env_backup is not None:
                    os.environ["GITHUB_TOKEN"] = env_backup

        err = capsys.readouterr().err
        assert "GITHUB_TOKEN" in err

    def test_exits_1_when_prd_missing(self, tmp_path, capsys):
        with patch.object(main, "PRD_FILE", tmp_path / "missing.json"), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}):
            with pytest.raises(SystemExit) as exc:
                main.cmd_import_github(self._args())
            assert exc.value.code == 1

    def test_dry_run_no_write(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path, [])
        mock_added = [{"id": "US-1", "title": "Story X", "priority": "medium"}]
        # cmd_import_github does `from import_github import import_github_issues` locally,
        # so we patch the symbol on the already-loaded ig module (sys.modules['import_github']).
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}), \
             patch.object(ig, "import_github_issues", return_value=(mock_added, [])):
            main.cmd_import_github(self._args(dry_run=True))

        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "Story X" in out

    def test_reports_skipped_duplicates(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path, [])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "tok"}), \
             patch.object(ig, "import_github_issues", return_value=([], ["Duplicate title"])):
            main.cmd_import_github(self._args())

        out = capsys.readouterr().out
        assert "Duplicate title" in out
        assert "[skip]" in out

    def test_import_github_subcommand_registered(self):
        """spiral import-github parses --repo and --label correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("import-github")
        p.add_argument("--repo", required=True)
        p.add_argument("--label", default="spiral")
        p.add_argument("--dry-run", action="store_true", dest="dry_run")
        parsed = parser.parse_args(["import-github", "--repo", "a/b"])
        assert parsed.repo == "a/b"
        assert parsed.label == "spiral"
        assert parsed.dry_run is False
