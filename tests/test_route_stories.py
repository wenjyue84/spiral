"""Unit tests for lib/route_stories.py - story model annotation and routing."""
import json
import os
import sys
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from route_stories import route_stories


# ── Helpers ────────────────────────────────────────────────────────────────

def make_prd(stories):
    return {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }


def make_story(sid, passes=False, model=None):
    s = {
        "id": sid,
        "title": f"Story {sid}",
        "passes": passes,
        "priority": "medium",
        "description": "A test story.",
        "acceptanceCriteria": ["It works"],
        "dependencies": [],
    }
    if model is not None:
        s["model"] = model
    return s


def write_prd(tmp_path, prd):
    path = tmp_path / "prd.json"
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


def read_prd(tmp_path):
    return json.loads((tmp_path / "prd.json").read_text(encoding="utf-8"))


# ── Profile assignment tests ────────────────────────────────────────────────

class TestHaikuProfile:
    def test_haiku_assigns_haiku_to_all_pending(self, tmp_path):
        prd = make_prd([make_story("US-001"), make_story("US-002")])
        prd_path = write_prd(tmp_path, prd)

        route_stories(prd_path, "haiku")

        result = read_prd(tmp_path)
        for story in result["userStories"]:
            assert story["model"] == "haiku"


class TestOpusProfile:
    def test_opus_assigns_opus_to_all_pending(self, tmp_path):
        prd = make_prd([make_story("US-001"), make_story("US-002")])
        prd_path = write_prd(tmp_path, prd)

        route_stories(prd_path, "opus")

        result = read_prd(tmp_path)
        for story in result["userStories"]:
            assert story["model"] == "opus"


# ── Passed-story filtering ──────────────────────────────────────────────────

class TestPassedStoriesFiltered:
    def test_passed_stories_not_reannotated(self, tmp_path):
        stories = [
            make_story("US-001", passes=True),   # already done — must not be touched
            make_story("US-002", passes=False),  # pending — must be annotated
        ]
        prd_path = write_prd(tmp_path, make_prd(stories))

        route_stories(prd_path, "sonnet")

        result = read_prd(tmp_path)
        passed = next(s for s in result["userStories"] if s["id"] == "US-001")
        pending = next(s for s in result["userStories"] if s["id"] == "US-002")

        assert "model" not in passed, "Passed story must not receive a model annotation"
        assert pending["model"] == "sonnet"


# ── Model overwrite ─────────────────────────────────────────────────────────

class TestModelOverwrite:
    def test_existing_model_overwritten_on_reroute(self, tmp_path):
        """A story already annotated with 'haiku' is overwritten when re-routed with 'opus'."""
        prd_path = write_prd(tmp_path, make_prd([make_story("US-001", model="haiku")]))

        route_stories(prd_path, "opus")

        result = read_prd(tmp_path)
        assert result["userStories"][0]["model"] == "opus"


# ── Atomic write ────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_atomic_write_produces_valid_json(self, tmp_path):
        prd_path = write_prd(tmp_path, make_prd([make_story("US-001")]))

        route_stories(prd_path, "sonnet")

        # If the file is not valid JSON this line raises — that is the assertion
        result = read_prd(tmp_path)
        assert result["userStories"][0]["model"] == "sonnet"

    def test_no_temp_file_left_after_successful_write(self, tmp_path):
        prd_path = write_prd(tmp_path, make_prd([make_story("US-001")]))

        route_stories(prd_path, "haiku")

        # Only prd.json should remain; no stray temp files
        files = set(f.name for f in tmp_path.iterdir())
        assert files == {"prd.json"}


# ── Missing PRD ─────────────────────────────────────────────────────────────

class TestMissingPrd:
    def test_missing_prd_raises_file_not_found(self, tmp_path):
        prd_path = str(tmp_path / "nonexistent.json")

        with pytest.raises((FileNotFoundError, SystemExit)):
            route_stories(prd_path, "haiku")


# ── Auto profile ────────────────────────────────────────────────────────────

class TestAutoProfile:
    def test_auto_complex_story_gets_sonnet(self, tmp_path):
        prd_path = write_prd(tmp_path, make_prd([make_story("US-001")]))

        with patch("route_stories.call_claude", return_value="complex"):
            route_stories(prd_path, "auto")

        result = read_prd(tmp_path)
        assert result["userStories"][0]["model"] == "sonnet"

    def test_auto_simple_story_gets_haiku(self, tmp_path):
        prd_path = write_prd(tmp_path, make_prd([make_story("US-001")]))

        with patch("route_stories.call_claude", return_value="simple"):
            route_stories(prd_path, "auto")

        result = read_prd(tmp_path)
        assert result["userStories"][0]["model"] == "haiku"
