"""Tests for lib/story_helpers.py — get_files_to_touch, priority_key."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from story_helpers import get_files_to_touch, priority_key


# ── get_files_to_touch ────────────────────────────────────────────────────────


def test_get_files_to_touch_top_level():
    story = {"filesTouch": ["src/a.py", "src/b.py"]}
    assert get_files_to_touch(story) == {"src/a.py", "src/b.py"}


def test_get_files_to_touch_technical_hints_fallback():
    story = {"technicalHints": {"filesTouch": ["lib/foo.py"]}}
    assert get_files_to_touch(story) == {"lib/foo.py"}


def test_get_files_to_touch_top_level_takes_precedence():
    story = {
        "filesTouch": ["src/a.py"],
        "technicalHints": {"filesTouch": ["lib/b.py"]},
    }
    # Top-level is non-empty, so it wins
    assert get_files_to_touch(story) == {"src/a.py"}


def test_get_files_to_touch_empty():
    assert get_files_to_touch({}) == set()
    assert get_files_to_touch({"filesTouch": []}) == set()


def test_get_files_to_touch_hints_not_dict():
    story = {"technicalHints": "just a string"}
    assert get_files_to_touch(story) == set()


# ── priority_key ──────────────────────────────────────────────────────────────


def test_priority_key_all_levels():
    assert priority_key({"priority": "critical"}) == 0
    assert priority_key({"priority": "high"}) == 1
    assert priority_key({"priority": "medium"}) == 2
    assert priority_key({"priority": "low"}) == 3


def test_priority_key_default():
    assert priority_key({}) == 2  # defaults to medium
    assert priority_key({"priority": "unknown"}) == 2


def test_priority_key_sorting():
    stories = [
        {"id": "a", "priority": "low"},
        {"id": "b", "priority": "critical"},
        {"id": "c", "priority": "high"},
        {"id": "d", "priority": "medium"},
    ]
    sorted_stories = sorted(stories, key=priority_key)
    assert [s["id"] for s in sorted_stories] == ["b", "c", "d", "a"]
