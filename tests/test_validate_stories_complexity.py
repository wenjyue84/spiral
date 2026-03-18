"""Tests for the Phase S complexity gate and quality warnings added in US-442."""

import io
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.prd.validate_stories import validate_stories


def _make_prd(goals: list[str] | None = None) -> dict:
    """Minimal prd.json dict for testing."""
    return {
        "productName": "test",
        "overview": "test overview",
        "goals": goals or ["build a good product", "add features"],
        "userStories": [],
    }


def _make_research(stories: list[dict]) -> dict:
    return {"stories": stories}


def _base_story(**overrides) -> dict:
    story = {
        "title": "Add a small feature",
        "priority": "medium",
        "description": "Add a small feature to the codebase that improves usability.",
        "acceptanceCriteria": ["Feature works correctly"],
        "technicalNotes": ["File to edit: lib/foo.py (bar)", "Test command: uv run pytest tests/test_foo.py -v"],
        "dependencies": [],
        "estimatedComplexity": "small",
        "_source": "research",
    }
    story.update(overrides)
    return story


def _run_validate(prd: dict, research: dict) -> tuple[list, list]:
    """Write temp files and run validate_stories, return (accepted, rejected)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = os.path.join(tmpdir, "prd.json")
        research_path = os.path.join(tmpdir, "research.json")
        test_stories_path = os.path.join(tmpdir, "test_stories.json")
        validated_path = os.path.join(tmpdir, "validated.json")
        rejected_path = os.path.join(tmpdir, "rejected.json")

        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)
        with open(research_path, "w", encoding="utf-8") as f:
            json.dump(research, f)
        # Empty test stories file (not under test here)
        with open(test_stories_path, "w", encoding="utf-8") as f:
            json.dump({"stories": []}, f)

        validate_stories(
            research_path=research_path,
            test_stories_path=test_stories_path,
            prd_path=prd_path,
            validated_out=validated_path,
            rejected_out=rejected_path,
            min_overlap=0,  # disable goal alignment to isolate complexity gate tests
        )

        with open(validated_path, encoding="utf-8") as f:
            accepted = json.load(f)["stories"]
        with open(rejected_path, encoding="utf-8") as f:
            rejected = json.load(f)["stories"]

    return accepted, rejected


class TestComplexityGate:
    """US-442: Stories with estimatedComplexity='large' must be rejected."""

    def test_large_story_is_rejected(self):
        story = _base_story(estimatedComplexity="large")
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 0, "large story should not be accepted"
        assert len(rejected) == 1
        reason = rejected[0]["_rejection_reason"]
        assert "complexity_too_large" in reason, f"Unexpected rejection reason: {reason}"

    def test_small_story_is_accepted(self):
        story = _base_story(estimatedComplexity="small")
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_medium_story_is_accepted(self):
        story = _base_story(estimatedComplexity="medium")
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1
        assert len(rejected) == 0

    def test_missing_complexity_is_accepted(self):
        """Stories without estimatedComplexity field should not be rejected by the gate."""
        story = _base_story()
        del story["estimatedComplexity"]
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1
        # Should not be in rejected due to complexity gate
        for r in rejected:
            assert "complexity_too_large" not in r.get("_rejection_reason", "")


class TestQualityWarnings:
    """US-442: Stories with >4 ACs or empty technicalNotes should warn but still pass."""

    def test_story_with_5_acs_is_accepted_but_warns(self, capsys):
        story = _base_story(
            acceptanceCriteria=["AC1", "AC2", "AC3", "AC4", "AC5"],
            estimatedComplexity="small",
        )
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1, "story with 5 ACs should still be accepted"
        assert len(rejected) == 0

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "ACs" in captured.out

    def test_story_with_empty_technical_notes_warns(self, capsys):
        story = _base_story(technicalNotes=[], estimatedComplexity="small")
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1, "story with empty technicalNotes should still be accepted"

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "technicalNotes" in captured.out

    def test_story_with_4_acs_does_not_warn(self, capsys):
        story = _base_story(acceptanceCriteria=["AC1", "AC2", "AC3", "AC4"])
        prd = _make_prd()
        accepted, rejected = _run_validate(prd, _make_research([story]))

        assert len(accepted) == 1
        captured = capsys.readouterr()
        # Should not warn about AC count when exactly 4
        assert "has 4 ACs" not in captured.out
