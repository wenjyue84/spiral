"""Unit tests for decompose_story.py (ID allocation + JSON extraction)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from decompose_story import find_next_id, extract_json_from_response, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _story(sid, **kwargs):
    base = {
        "id": sid,
        "title": f"Story {sid}",
        "priority": "medium",
        "description": "A story",
        "acceptanceCriteria": ["Works"],
        "technicalNotes": [],
        "dependencies": [],
        "estimatedComplexity": "small",
        "passes": False,
    }
    base.update(kwargs)
    return base


def _write_prd(path, stories):
    prd = {
        "productName": "TestApp",
        "branchName": "main",
        "userStories": stories,
    }
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# find_next_id tests
# ---------------------------------------------------------------------------

class TestFindNextId:
    def test_find_next_id_no_gaps(self):
        """Returns max+1 when IDs are contiguous."""
        stories = [_story("US-001"), _story("US-002"), _story("US-003")]
        assert find_next_id(stories) == 4

    def test_find_next_id_with_gaps(self):
        """Handles non-contiguous IDs — returns max+1, not first gap."""
        stories = [_story("US-001"), _story("US-005"), _story("US-010")]
        assert find_next_id(stories) == 11

    def test_find_next_id_empty(self):
        """Returns 1 when no stories are present."""
        assert find_next_id([]) == 1

    def test_find_next_id_ignores_non_prefix(self):
        """Non-matching IDs (different prefix) are ignored."""
        stories = [_story("TASK-001"), _story("US-003")]
        assert find_next_id(stories) == 4

    def test_find_next_id_single_story(self):
        """Single story → max+1."""
        assert find_next_id([_story("US-007")]) == 8


# ---------------------------------------------------------------------------
# extract_json_from_response tests
# ---------------------------------------------------------------------------

class TestExtractJsonFromResponse:
    def test_extract_json_plain_text(self):
        """Parses bare JSON string."""
        payload = {"ordered": False, "stories": [{"title": "A"}]}
        result = extract_json_from_response(json.dumps(payload))
        assert result["stories"][0]["title"] == "A"

    def test_extract_json_markdown_fence(self):
        """Parses ```json fenced block."""
        inner = json.dumps({"ordered": True, "stories": [{"title": "B"}]})
        text = f"Sure:\n```json\n{inner}\n```"
        result = extract_json_from_response(text)
        assert result["stories"][0]["title"] == "B"

    def test_extract_json_plain_fence(self):
        """Parses plain ``` fence (no language specifier)."""
        inner = json.dumps({"ordered": False, "stories": [{"title": "C"}]})
        text = f"Here:\n```\n{inner}\n```"
        result = extract_json_from_response(text)
        assert result["stories"][0]["title"] == "C"

    def test_extract_json_no_json_raises_value_error(self):
        """Raises ValueError when no JSON can be found."""
        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json_from_response("This is just plain text with no JSON at all.")

    def test_extract_json_with_surrounding_text(self):
        """Finds embedded JSON object with 'stories' key in prose."""
        inner = '{"ordered": false, "stories": [{"title": "D"}]}'
        text = f"Here is my response: {inner} Hope that helps!"
        result = extract_json_from_response(text)
        assert result["stories"][0]["title"] == "D"


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------

class TestMainDryRun:
    def test_main_dry_run_exits_0(self, tmp_path, monkeypatch, capsys):
        """--dry-run exits 0 and prints prompt without writing prd.json."""
        prd_path = tmp_path / "prd.json"
        stories = [
            _story("US-001", passes=True),
            _story("US-002"),
        ]
        _write_prd(prd_path, stories)

        monkeypatch.setattr(
            sys, "argv",
            ["decompose_story.py", "--story-id", "US-002",
             "--prd", str(prd_path), "--dry-run"],
        )

        rc = main()
        assert rc == 0

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

        # prd.json must NOT be modified
        with open(str(prd_path), encoding="utf-8") as f:
            saved = json.load(f)
        ids = [s["id"] for s in saved["userStories"]]
        assert ids == ["US-001", "US-002"]

    def test_main_dry_run_sub_story_refused(self, tmp_path, monkeypatch, capsys):
        """A story with _decomposedFrom is refused (returns exit code 1)."""
        prd_path = tmp_path / "prd.json"
        stories = [
            _story("US-001"),
            _story("US-002", _decomposedFrom="US-001"),
        ]
        _write_prd(prd_path, stories)

        monkeypatch.setattr(
            sys, "argv",
            ["decompose_story.py", "--story-id", "US-002",
             "--prd", str(prd_path), "--dry-run"],
        )

        rc = main()
        assert rc == 1

    def test_main_missing_prd_exits_1(self, tmp_path, monkeypatch):
        """Exits 1 when prd.json file does not exist."""
        monkeypatch.setattr(
            sys, "argv",
            ["decompose_story.py", "--story-id", "US-001",
             "--prd", str(tmp_path / "missing.json"), "--dry-run"],
        )
        rc = main()
        assert rc == 1

    def test_main_story_not_found_exits_1(self, tmp_path, monkeypatch):
        """Exits 1 when requested story ID is not in prd.json."""
        prd_path = tmp_path / "prd.json"
        _write_prd(prd_path, [_story("US-001")])

        monkeypatch.setattr(
            sys, "argv",
            ["decompose_story.py", "--story-id", "US-999",
             "--prd", str(prd_path), "--dry-run"],
        )
        rc = main()
        assert rc == 1
