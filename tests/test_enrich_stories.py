"""Tests for lib/enrich_stories.py (Phase E story enrichment)."""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.research.enrich_stories import _enrich_one, _should_enrich, enrich_stories


def _story(**overrides) -> dict:
    base = {
        "title": "Add feature X",
        "priority": "medium",
        "description": "Add feature X to the codebase.",
        "acceptanceCriteria": ["Feature X works"],
        "technicalNotes": ["File to edit: lib/x.py (add_x)", "Test command: uv run pytest tests/test_x.py -v"],
        "dependencies": [],
        "estimatedComplexity": "small",
        "_source": "research",
        "passes": False,
    }
    base.update(overrides)
    return base


class TestShouldEnrich:
    """_should_enrich() should return True only for eligible stories."""

    def test_small_with_notes_is_not_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=["note1", "note2"])
        assert _should_enrich(s) is False

    def test_medium_is_enriched(self):
        s = _story(estimatedComplexity="medium")
        assert _should_enrich(s) is True

    def test_large_is_enriched(self):
        s = _story(estimatedComplexity="large")
        assert _should_enrich(s) is True

    def test_small_with_sparse_notes_is_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=["one note only"])
        assert _should_enrich(s) is True

    def test_small_with_no_notes_is_enriched(self):
        s = _story(estimatedComplexity="small", technicalNotes=[])
        assert _should_enrich(s) is True


class TestEnrichOne:
    """_enrich_one() should return a list of 1-2 stories."""

    def _mock_enrich_response(self, story: dict) -> str:
        """Return a valid enrich JSON response."""
        enriched = dict(story)
        enriched["technicalNotes"] = [
            "File to edit: lib/x.py (add_x)",
            "Test command: uv run pytest tests/test_x.py::test_add_x -v",
        ]
        enriched["_enriched"] = True
        return json.dumps({"action": "enrich", "story": enriched})

    def _mock_split_response(self, story: dict) -> str:
        """Return a valid split JSON response with 2 sub-stories."""
        s1 = dict(story)
        s1["title"] = story["title"] + " (part 1)"
        s1["acceptanceCriteria"] = ["Part 1 works"]
        s2 = dict(story)
        s2["title"] = story["title"] + " (part 2)"
        s2["acceptanceCriteria"] = ["Part 2 works"]
        return json.dumps({"action": "split", "stories": [s1, s2]})

    def test_enrich_action_returns_one_story(self):
        story = _story(estimatedComplexity="medium", technicalNotes=[])
        mock_response = self._mock_enrich_response(story)

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 1
        assert result[0].get("_enriched") is True

    def test_split_action_returns_two_stories(self):
        story = _story(estimatedComplexity="medium")
        mock_response = self._mock_split_response(story)

        with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 2
        assert "part 1" in result[0]["title"]
        assert "part 2" in result[1]["title"]

    def test_claude_failure_returns_original(self):
        """When Claude call fails, original story passes through unchanged."""
        story = _story(estimatedComplexity="medium")

        with patch("lib.research.enrich_stories.call_claude", side_effect=RuntimeError("timeout")):
            result = _enrich_one(story, model="sonnet")

        assert len(result) == 1
        assert result[0] is story  # exact same object — not a copy

    def test_dry_run_returns_original(self):
        story = _story(estimatedComplexity="medium")
        result = _enrich_one(story, model="sonnet", dry_run=True)

        assert len(result) == 1
        assert result[0] is story


class TestEnrichStoriesIntegration:
    """enrich_stories() integration tests using temp files."""

    def test_small_well_specified_stories_pass_through(self):
        """Small stories with 2+ technicalNotes should not be enriched (no Claude call)."""
        story = _story(estimatedComplexity="small", technicalNotes=["note1", "note2"])

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": [story]}, f)

            with patch("lib.enrich_stories.call_claude") as mock_claude:
                enrich_count, split_count = enrich_stories(validated, enriched, model="sonnet")
                mock_claude.assert_not_called()  # should not call Claude for small+well-specified

            with open(enriched, encoding="utf-8") as f:
                result = json.load(f)

        assert len(result["stories"]) == 1
        assert enrich_count == 0
        assert split_count == 0

    def test_medium_story_gets_enriched(self):
        story = _story(estimatedComplexity="medium", technicalNotes=[])
        enriched_story = dict(story)
        enriched_story["_enriched"] = True
        enriched_story["technicalNotes"] = [
            "File to edit: lib/x.py (add_x)",
            "Test command: uv run pytest tests/test_x.py -v",
        ]
        mock_response = json.dumps({"action": "enrich", "story": enriched_story})

        with tempfile.TemporaryDirectory() as tmpdir:
            validated = os.path.join(tmpdir, "validated.json")
            enriched_out = os.path.join(tmpdir, "enriched.json")

            with open(validated, "w", encoding="utf-8") as f:
                json.dump({"stories": [story]}, f)

            with patch("lib.research.enrich_stories.call_claude", return_value=mock_response):
                enrich_count, split_count = enrich_stories(validated, enriched_out, model="sonnet")

            with open(enriched_out, encoding="utf-8") as f:
                result = json.load(f)

        assert len(result["stories"]) == 1
        assert result["stories"][0].get("_enriched") is True
        assert enrich_count == 1
