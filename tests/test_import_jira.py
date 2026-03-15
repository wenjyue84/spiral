"""Tests for lib/import_jira.py — Jira Issues importer."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import import_jira as ij  # noqa: E402
import main  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_issue(
    key: str = "ENG-1",
    summary: str = "Test story",
    description: str | dict | None = "Description here.",
    priority_name: str = "Medium",
) -> dict:
    desc: dict | None
    if isinstance(description, dict):
        desc = description
    elif description:
        # Minimal ADF-like dict with a single text node
        desc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }
    else:
        desc = None

    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": desc,
            "priority": {"name": priority_name},
        },
    }


def _make_prd(tmp_path: Path, stories: list[dict]) -> Path:
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd), encoding="utf-8")
    return p


# ── Priority extraction ───────────────────────────────────────────────────────


class TestExtractPriority:
    def test_highest_maps_to_critical(self):
        issue = _make_issue(priority_name="Highest")
        assert ij._extract_priority(issue) == "critical"

    def test_high_maps_to_high(self):
        issue = _make_issue(priority_name="High")
        assert ij._extract_priority(issue) == "high"

    def test_medium_maps_to_medium(self):
        issue = _make_issue(priority_name="Medium")
        assert ij._extract_priority(issue) == "medium"

    def test_low_maps_to_low(self):
        issue = _make_issue(priority_name="Low")
        assert ij._extract_priority(issue) == "low"

    def test_lowest_maps_to_low(self):
        issue = _make_issue(priority_name="Lowest")
        assert ij._extract_priority(issue) == "low"

    def test_unknown_priority_defaults_to_medium(self):
        issue = _make_issue(priority_name="Blocker")
        assert ij._extract_priority(issue) == "medium"

    def test_missing_priority_field_defaults_to_medium(self):
        issue = {"key": "ENG-1", "fields": {"summary": "x", "description": None}}
        assert ij._extract_priority(issue) == "medium"

    def test_case_insensitive_matching(self):
        issue = _make_issue(priority_name="HIGH")
        assert ij._extract_priority(issue) == "high"


# ── ADF text extraction ───────────────────────────────────────────────────────


class TestAdfToText:
    def test_plain_text_node(self):
        node = {"type": "text", "text": "hello"}
        assert ij._adf_to_text(node) == "hello"

    def test_paragraph_with_text(self):
        node = {
            "type": "paragraph",
            "content": [{"type": "text", "text": "world"}],
        }
        assert "world" in ij._adf_to_text(node)

    def test_nested_doc(self):
        node = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "line1"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "line2"}]},
            ],
        }
        result = ij._adf_to_text(node)
        assert "line1" in result
        assert "line2" in result

    def test_empty_node(self):
        assert ij._adf_to_text({}) == ""


# ── Description extraction ────────────────────────────────────────────────────


class TestExtractDescription:
    def test_adf_description(self):
        issue = _make_issue(description="my desc")
        result = ij._extract_description(issue)
        assert "my desc" in result

    def test_plain_string_description(self):
        issue = {"key": "ENG-1", "fields": {"summary": "x", "description": "plain text"}}
        assert ij._extract_description(issue) == "plain text"

    def test_none_description(self):
        issue = _make_issue(description=None)
        assert ij._extract_description(issue) == ""


# ── ID generation ─────────────────────────────────────────────────────────────


class TestNextStoryId:
    def test_empty_list_returns_us_1(self):
        assert ij._next_story_id([]) == "US-1"

    def test_increments_from_highest(self):
        stories = [{"id": "US-5"}, {"id": "US-3"}, {"id": "US-10"}]
        assert ij._next_story_id(stories) == "US-11"

    def test_ignores_non_matching_ids(self):
        stories = [{"id": "US-2"}, {"id": "CUSTOM-99"}]
        assert ij._next_story_id(stories) == "US-3"


# ── Issue mapping ─────────────────────────────────────────────────────────────


class TestMapIssueToStory:
    def test_basic_mapping(self):
        issue = _make_issue(key="ENG-42", summary="Add login", description="Must support OAuth")
        story = ij.map_issue_to_story(issue, set(), "US-10")
        assert story is not None
        assert story["id"] == "US-10"
        assert story["title"] == "Add login"
        assert "Must support OAuth" in story["description"]
        assert story["passes"] is False
        assert story["_jiraKey"] == "ENG-42"
        assert story["_source"] == "jira-import"

    def test_duplicate_returns_none(self):
        issue = _make_issue(summary="Existing story")
        result = ij.map_issue_to_story(issue, {"Existing story"}, "US-99")
        assert result is None

    def test_empty_summary_returns_none(self):
        issue = _make_issue(summary="   ")
        result = ij.map_issue_to_story(issue, set(), "US-1")
        assert result is None

    def test_priority_propagated(self):
        issue = _make_issue(priority_name="High")
        story = ij.map_issue_to_story(issue, set(), "US-1")
        assert story is not None
        assert story["priority"] == "high"

    def test_jira_key_stored_in_metadata(self):
        issue = _make_issue(key="PROJ-7")
        story = ij.map_issue_to_story(issue, set(), "US-1")
        assert story is not None
        assert story["_jiraKey"] == "PROJ-7"

    def test_title_stripped_of_whitespace(self):
        issue = _make_issue(summary="  Trim me  ")
        story = ij.map_issue_to_story(issue, set(), "US-1")
        assert story is not None
        assert story["title"] == "Trim me"


# ── Auth header ───────────────────────────────────────────────────────────────


class TestBuildAuthHeader:
    def test_basic_auth_format(self):
        header = ij._build_auth_header("user@example.com", "mytoken")
        assert header.startswith("Basic ")
        import base64
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        assert decoded == "user@example.com:mytoken"


# ── import_jira_issues (integration with mocked fetch) ───────────────────────


class TestImportJiraIssues:
    def _mock_fetch(self, issues: list[dict]):
        def _fake_fetch(host, jql, email, api_token):
            yield from issues
        return _fake_fetch

    def test_adds_new_stories(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue("ENG-1", "Story A"), _make_issue("ENG-2", "Story B")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
                dry_run=False,
            )
        assert len(added) == 2
        assert len(skipped) == 0
        data = json.loads(prd_path.read_text())
        assert len(data["userStories"]) == 2

    def test_skips_duplicates(self, tmp_path):
        existing = [{"id": "US-1", "title": "Already here", "passes": True}]
        prd_path = _make_prd(tmp_path, existing)
        issues = [_make_issue("ENG-1", "Already here"), _make_issue("ENG-2", "New story")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )
        assert len(added) == 1
        assert added[0]["title"] == "New story"
        assert "Already here" in skipped

    def test_dry_run_does_not_write(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue(summary="Ghost story")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, skipped = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
                dry_run=True,
            )
        assert len(added) == 1
        data = json.loads(prd_path.read_text())
        assert len(data["userStories"]) == 0

    def test_ids_are_sequential(self, tmp_path):
        existing = [{"id": "US-5", "title": "Old", "passes": True}]
        prd_path = _make_prd(tmp_path, existing)
        issues = [_make_issue("ENG-1", "First new"), _make_issue("ENG-2", "Second new")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, _ = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )
        assert added[0]["id"] == "US-6"
        assert added[1]["id"] == "US-7"

    def test_empty_host_raises(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        with pytest.raises(ValueError, match="host"):
            ij.import_jira_issues(
                host="",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )

    def test_neither_project_nor_jql_raises(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        with pytest.raises(ValueError, match="project"):
            ij.import_jira_issues(
                host="acme.atlassian.net",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )

    def test_project_builds_default_jql(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        captured_jql: list[str] = []

        def _capture_fetch(host, jql, email, api_token):
            captured_jql.append(jql)
            return iter([])

        with patch.object(ij, "fetch_issues", _capture_fetch):
            ij.import_jira_issues(
                host="acme.atlassian.net",
                project="ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )

        assert len(captured_jql) == 1
        assert "ENG" in captured_jql[0]

    def test_jql_overrides_project(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        captured_jql: list[str] = []

        def _capture_fetch(host, jql, email, api_token):
            captured_jql.append(jql)
            return iter([])

        with patch.object(ij, "fetch_issues", _capture_fetch):
            ij.import_jira_issues(
                host="acme.atlassian.net",
                project="IGNORED",
                jql="labels=spiral AND status=Backlog",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )

        assert captured_jql[0] == "labels=spiral AND status=Backlog"

    def test_missing_prd_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(tmp_path / "missing.json"),
                email="u@e.com",
                api_token="tok",
            )

    def test_empty_issues_returns_empty(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        with patch.object(ij, "fetch_issues", self._mock_fetch([])):
            added, skipped = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )
        assert added == []
        assert skipped == []

    def test_jira_key_stored_in_story(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue(key="PROJ-99", summary="Feature X")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, _ = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=PROJ",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )
        assert added[0]["_jiraKey"] == "PROJ-99"

    def test_priority_mapping_highest_to_critical(self, tmp_path):
        prd_path = _make_prd(tmp_path, [])
        issues = [_make_issue(priority_name="Highest", summary="Critical feature")]
        with patch.object(ij, "fetch_issues", self._mock_fetch(issues)):
            added, _ = ij.import_jira_issues(
                host="acme.atlassian.net",
                jql="project=ENG",
                prd_path=str(prd_path),
                email="u@e.com",
                api_token="tok",
            )
        assert added[0]["priority"] == "critical"


# ── CLI (main.py import-jira) ─────────────────────────────────────────────────


class TestCmdImportJira:
    def _args(self, host="acme.atlassian.net", project=None, jql="project=ENG", dry_run=False):
        return SimpleNamespace(host=host, project=project, jql=jql, dry_run=dry_run)

    def test_exits_1_without_credentials(self, tmp_path, capsys):
        with patch.object(main, "PRD_FILE", tmp_path / "prd.json"), \
             patch.dict(os.environ, {}, clear=False):
            env_backup_email = os.environ.pop("JIRA_USER_EMAIL", None)
            env_backup_token = os.environ.pop("JIRA_API_TOKEN", None)
            try:
                with pytest.raises(SystemExit) as exc:
                    main.cmd_import_jira(self._args())
                assert exc.value.code == 1
            finally:
                if env_backup_email is not None:
                    os.environ["JIRA_USER_EMAIL"] = env_backup_email
                if env_backup_token is not None:
                    os.environ["JIRA_API_TOKEN"] = env_backup_token

        err = capsys.readouterr().err
        assert "JIRA_USER_EMAIL" in err or "JIRA_API_TOKEN" in err

    def test_exits_1_when_prd_missing(self, tmp_path, capsys):
        with patch.object(main, "PRD_FILE", tmp_path / "missing.json"), \
             patch.dict(os.environ, {"JIRA_USER_EMAIL": "u@e.com", "JIRA_API_TOKEN": "tok"}):
            with pytest.raises(SystemExit) as exc:
                main.cmd_import_jira(self._args())
            assert exc.value.code == 1

    def test_dry_run_output(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path, [])
        mock_added = [{"id": "US-1", "title": "Story X", "priority": "medium", "_jiraKey": "ENG-1"}]
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.dict(os.environ, {"JIRA_USER_EMAIL": "u@e.com", "JIRA_API_TOKEN": "tok"}), \
             patch.object(ij, "import_jira_issues", return_value=(mock_added, [])):
            main.cmd_import_jira(self._args(dry_run=True))

        out = capsys.readouterr().out
        assert "[dry-run]" in out
        assert "Story X" in out

    def test_reports_skipped_duplicates(self, tmp_path, capsys):
        prd_path = _make_prd(tmp_path, [])
        with patch.object(main, "PRD_FILE", prd_path), \
             patch.dict(os.environ, {"JIRA_USER_EMAIL": "u@e.com", "JIRA_API_TOKEN": "tok"}), \
             patch.object(ij, "import_jira_issues", return_value=([], ["Duplicate title"])):
            main.cmd_import_jira(self._args())

        out = capsys.readouterr().out
        assert "Duplicate title" in out
        assert "[skip]" in out

    def test_import_jira_subcommand_registered(self):
        """spiral import-jira parses --host, --project, --jql correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p = sub.add_parser("import-jira")
        p.add_argument("--host", required=True)
        p.add_argument("--project", default=None)
        p.add_argument("--jql", default=None)
        p.add_argument("--dry-run", action="store_true", dest="dry_run")
        parsed = parser.parse_args(["import-jira", "--host", "acme.atlassian.net", "--project", "ENG"])
        assert parsed.host == "acme.atlassian.net"
        assert parsed.project == "ENG"
        assert parsed.jql is None
        assert parsed.dry_run is False
