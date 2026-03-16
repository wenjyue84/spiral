"""Tests for lib/story_helpers.py — get_files_to_touch, priority_key."""

import os
import sys

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
    # critical=80 → key=20, high=60 → key=40, medium=40 → key=60, low=20 → key=80
    assert priority_key({"priority": "critical"}) == 20
    assert priority_key({"priority": "high"}) == 40
    assert priority_key({"priority": "medium"}) == 60
    assert priority_key({"priority": "low"}) == 80


def test_priority_key_default():
    assert priority_key({}) == 60  # defaults to medium score (40) → key=60
    assert priority_key({"priority": "unknown"}) == 60


def test_priority_key_sorting():
    stories = [
        {"id": "a", "priority": "low"},
        {"id": "b", "priority": "critical"},
        {"id": "c", "priority": "high"},
        {"id": "d", "priority": "medium"},
    ]
    sorted_stories = sorted(stories, key=priority_key)
    assert [s["id"] for s in sorted_stories] == ["b", "c", "d", "a"]


def test_priority_key_priority_score_overrides_text():
    # priorityScore=90 → key=10, beats critical text (key=20)
    assert priority_key({"priority": "low", "priorityScore": 90}) < priority_key({"priority": "critical"})
    # priorityScore=5 → key=95, lower than low text (key=80)
    assert priority_key({"priority": "critical", "priorityScore": 5}) > priority_key({"priority": "low"})


def test_priority_key_priority_score_range():
    assert priority_key({"priorityScore": 100}) == 0  # highest possible
    assert priority_key({"priorityScore": 0}) == 100  # lowest possible
    assert priority_key({"priorityScore": 60}) == 40  # same sort key as "high" default


def test_priority_key_priority_score_fine_grained():
    # Two "high" stories can now be ordered within the bucket
    a = {"priority": "high", "priorityScore": 65}
    b = {"priority": "high", "priorityScore": 55}
    assert priority_key(a) < priority_key(b)  # a ranks higher
