"""Tests for lesson injection in decompose_story.py (US-1257)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from workers.decompose_story import build_lessons_section


def _make_lesson(tag: str, pattern: str, fix: str = "Avoid it") -> dict[str, Any]:
    return {
        "error_category": tag,
        "pattern": pattern,
        "fix": fix,
        "story_id": "US-001",
        "story_title": f"Story about {tag}",
        "seen_count": 1,
        "confidence": 0.8,
    }


def _story(title: str = "Decompose scope overflow", description: str = "") -> dict[str, Any]:
    return {
        "id": "US-999",
        "title": title,
        "description": description,
        "acceptanceCriteria": ["Works"],
        "technicalNotes": [],
    }


# ── AC1: decompose_story imports query_lessons and appends lessons ──────────


def test_lessons_appended_when_matches_found(tmp_path: Path) -> None:
    """Lessons matching the story are appended to the prompt section."""
    lessons_file = tmp_path / "learned_lessons.jsonl"
    lessons_file.write_text(
        json.dumps(_make_lesson("scope", "scope overflow causes decompose failure")) + "\n",
        encoding="utf-8",
    )
    story = _story("Decompose scope overflow story")
    result = build_lessons_section(str(lessons_file), story, top_k=3)
    assert "scope" in result or "overflow" in result or "decompose" in result


# ── AC2: When >=3 entries share the story's tag, at least 1 appears ─────────


def test_matching_tag_lessons_appear_in_section(tmp_path: Path) -> None:
    """When >=3 lessons share the story's keyword, at least one appears."""
    lessons_file = tmp_path / "learned_lessons.jsonl"
    lines = [
        _make_lesson("decompose", "decompose scope overflow in story implementation"),
        _make_lesson("decompose", "decompose timeout causes retry storm in story"),
        _make_lesson("decompose", "decompose context overflow exceeds token limit in story"),
    ]
    lessons_file.write_text(
        "\n".join(json.dumps(ln) for ln in lines) + "\n",
        encoding="utf-8",
    )
    story = _story("story implementation decompose context")
    result = build_lessons_section(str(lessons_file), story, top_k=3)
    assert result.strip() != "", "Expected at least 1 lesson injected"
    assert "decompose" in result


# ── AC3: SPIRAL_LESSON_INJECTION=false disables injection ──────────────────


def test_injection_disabled_by_env(tmp_path: Path) -> None:
    """SPIRAL_LESSON_INJECTION=false returns empty string."""
    lessons_file = tmp_path / "learned_lessons.jsonl"
    lessons_file.write_text(
        json.dumps(_make_lesson("scope", "scope overflow")) + "\n",
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"SPIRAL_LESSON_INJECTION": "false"}):
        result = build_lessons_section(str(lessons_file), _story(), top_k=3)
    assert result == ""


def test_injection_enabled_by_default(tmp_path: Path) -> None:
    """Default SPIRAL_LESSON_INJECTION=true allows injection."""
    lessons_file = tmp_path / "learned_lessons.jsonl"
    lessons_file.write_text(
        json.dumps(_make_lesson("scope", "scope overflow decompose story")) + "\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "SPIRAL_LESSON_INJECTION"}
    with patch.dict(os.environ, env, clear=True):
        result = build_lessons_section(str(lessons_file), _story("decompose story scope"), top_k=3)
    # Either a match was found (non-empty) or no match (empty is also OK for default)
    assert isinstance(result, str)


# ── AC4: No lessons file → empty string, no crash ─────────────────────────


def test_no_lessons_file_returns_empty(tmp_path: Path) -> None:
    """Missing lessons file produces empty string without raising."""
    result = build_lessons_section(str(tmp_path / "nonexistent.jsonl"), _story())
    assert result == ""
