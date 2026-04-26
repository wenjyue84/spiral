"""Tests for lib/federated_search.py and lib/cli/search_stories.py (US-1286)."""

from __future__ import annotations

import json
import os
import tempfile

from lib.cli.search_stories import FederatedStorySearch
from lib.federated_search import search_across_projects


# ── Fixtures ─────────────────────────────────────────────────────────────────

_MAIN_PRD: dict = {
    "userStories": [
        {
            "id": "US-1",
            "title": "Add authentication middleware",
            "description": "Secure API with JWT tokens",
            "acceptanceCriteria": ["Returns 401 when token missing"],
            "passes": False,
        },
        {
            "id": "US-2",
            "title": "User dashboard",
            "description": "Show user profile and settings",
            "acceptanceCriteria": ["Dashboard loads without errors"],
            "passes": False,
        },
    ]
}

_SUB_PRD: dict = {
    "userStories": [
        {
            "id": "SUB-1",
            "title": "OAuth2 authentication flow",
            "description": "Implement OAuth2 for third-party login",
            "acceptanceCriteria": ["Redirect to provider and back"],
            "passes": False,
        },
    ]
}


def _write_prd(directory: str, filename: str, data: dict) -> str:  # type: ignore[type-arg]
    """Write a prd JSON file and return its path."""
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


# ── Core search tests ─────────────────────────────────────────────────────────


def test_search_finds_stories_in_main_and_subprojects() -> None:
    """Required test: search returns matches from main prd.json and prd.include."""
    with tempfile.TemporaryDirectory() as tmp:
        sub_path = _write_prd(tmp, "sub.json", _SUB_PRD)
        main_data = dict(_MAIN_PRD)
        main_data["prd.include"] = ["sub.json"]
        main_path = _write_prd(tmp, "prd.json", main_data)

        results = search_across_projects("authentication", main_path)

        ids = [r["story_id"] for r in results]
        assert "US-1" in ids, "Should match main project authentication story"
        assert "SUB-1" in ids, "Should match sub-project OAuth2 story"


def test_search_no_match_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        results = search_across_projects("xyzzy_no_match_ever", main_path)
        assert results == []


def test_search_results_sorted_by_score_descending() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        results = search_across_projects("authentication", main_path)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)


def test_search_project_filter() -> None:
    """--project filter returns only stories from specified sub-project."""
    with tempfile.TemporaryDirectory() as tmp:
        sub_path = _write_prd(tmp, "sub.json", _SUB_PRD)
        main_data = dict(_MAIN_PRD)
        main_data["prd.include"] = ["sub.json"]
        main_path = _write_prd(tmp, "prd.json", main_data)

        results = search_across_projects("authentication", main_path, project_filter="sub")

        ids = [r["story_id"] for r in results]
        assert "SUB-1" in ids
        assert "US-1" not in ids, "Should exclude main project when filtering by sub"


def test_search_circular_include_does_not_loop() -> None:
    """Circular prd.include references should not cause infinite recursion."""
    with tempfile.TemporaryDirectory() as tmp:
        # a.json includes b.json, b.json includes a.json
        a_data = {
            "userStories": [{"id": "A-1", "title": "auth feature", "description": "", "acceptanceCriteria": []}],
            "prd.include": ["b.json"],
        }
        b_data = {
            "userStories": [{"id": "B-1", "title": "auth backend", "description": "", "acceptanceCriteria": []}],
            "prd.include": ["a.json"],
        }
        _write_prd(tmp, "a.json", a_data)
        _write_prd(tmp, "b.json", b_data)
        main_data = dict(_MAIN_PRD)
        main_data["prd.include"] = ["a.json"]
        main_path = _write_prd(tmp, "prd.json", main_data)

        # Should not raise RecursionError
        results = search_across_projects("auth", main_path)
        ids = [r["story_id"] for r in results]
        assert "A-1" in ids
        assert "B-1" in ids
        # No duplicates
        assert len(ids) == len(set(ids))


def test_search_missing_include_file_skipped() -> None:
    """Missing prd.include file should be silently skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        main_data = dict(_MAIN_PRD)
        main_data["prd.include"] = ["nonexistent.json"]
        main_path = _write_prd(tmp, "prd.json", main_data)

        results = search_across_projects("authentication", main_path)
        assert any(r["story_id"] == "US-1" for r in results)


# ── Format tests ──────────────────────────────────────────────────────────────


def test_format_table_has_header() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        searcher = FederatedStorySearch("authentication", main_path)
        output = searcher.render("table")
        assert "ID" in output
        assert "PROJECT" in output
        assert "SCORE" in output


def test_format_json_valid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        searcher = FederatedStorySearch("authentication", main_path)
        output = searcher.render("json")
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        if parsed:
            assert "story_id" in parsed[0]
            assert "score" in parsed[0]


def test_format_csv_has_header() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        searcher = FederatedStorySearch("authentication", main_path)
        output = searcher.render("csv")
        assert output.startswith("story_id,project,title,score,description")


def test_no_results_table_message() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_path = _write_prd(tmp, "prd.json", _MAIN_PRD)
        searcher = FederatedStorySearch("zzznotfound", main_path)
        output = searcher.render("table")
        assert "No stories matched" in output
