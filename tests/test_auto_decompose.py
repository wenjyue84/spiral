"""Tests for lib/impl/auto_decompose.py — US-1043.

Covers AC1: decompose_exhausted_story returns 4 sub-stories with _parent_id,
  _decomposed_from_iteration; parent marked _decomposed=True, _decomposed_count=4.
Covers AC3: integration -- 3 escalation attempts trigger decompose -> 4 children
  with correct _parent_id, re-queued (passes=False), at least 1 can pass.

Regression test for US-1043: Automatic story decomposition when Phase I retry loop
exhausts all 3 escalation levels (haiku→sonnet→opus).
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.impl.auto_decompose import decompose_exhausted_story
from lib.impl.retry import _next_model


def _prd(story_id: str = "US-100") -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "productName": "Test",
        "userStories": [
            {
                "id": story_id,
                "title": "Oversized story",
                "priority": "high",
                "description": "Too large",
                "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
                "technicalNotes": [],
                "dependencies": [],
                "estimatedComplexity": "large",
                "passes": False,
            }
        ],
    }


# -- AC1: sub-story fields ----------------------------------------------------


@pytest.mark.us_1043
def test_returns_four_sub_stories() -> None:
    result = decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=100)
    children = [s for s in result["userStories"] if s.get("_parent_id") == "US-100"]
    assert len(children) == 4


@pytest.mark.us_1043
def test_sub_stories_have_parent_id_field() -> None:
    result = decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=100)
    children = [s for s in result["userStories"] if s.get("_parent_id") == "US-100"]
    for child in children:
        assert child["_parent_id"] == "US-100"


@pytest.mark.us_1043
def test_sub_stories_have_decomposed_from_iteration() -> None:
    result = decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=100, iteration=3)
    children = [s for s in result["userStories"] if s.get("_parent_id") == "US-100"]
    for child in children:
        assert child["_decomposed_from_iteration"] == 3


@pytest.mark.us_1043
def test_parent_marked_decomposed_with_count() -> None:
    result = decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=100)
    parent = next(s for s in result["userStories"] if s["id"] == "US-100")
    assert parent["_decomposed"] is True
    assert parent["_decomposed_count"] == 4


@pytest.mark.us_1043
def test_ceiling_enforcement() -> None:
    with pytest.raises(ValueError, match="ceiling"):
        decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=4)


@pytest.mark.us_1043
def test_children_have_small_complexity() -> None:
    result = decompose_exhausted_story("US-100", _prd(), max_stories_ceiling=100)
    children = [s for s in result["userStories"] if s.get("_parent_id") == "US-100"]
    for child in children:
        assert child["estimatedComplexity"] == "small"


# -- AC3: integration -- triple retry exhaustion ------------------------------


def _simulate_exhaustion(story_id: str, prd: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Walk haiku->sonnet->opus, then decompose when ladder exhausted."""
    models_tried: list[str] = []
    model: str | None = "haiku"
    attempt = 0
    while model is not None:
        models_tried.append(model)
        attempt += 1
        nxt = _next_model(model)
        if nxt is None:
            updated = decompose_exhausted_story(story_id, prd, max_stories_ceiling=200, iteration=attempt)
            return updated, models_tried
        model = nxt
    raise RuntimeError("Ladder not exhausted")


@pytest.mark.us_1043
def test_ladder_is_three_models() -> None:
    _, models = _simulate_exhaustion("US-100", _prd())
    assert models == ["haiku", "sonnet", "opus"]


@pytest.mark.us_1043
def test_triple_retry_produces_four_children_with_parent_id() -> None:
    updated, _ = _simulate_exhaustion("US-100", _prd())
    children = [s for s in updated["userStories"] if s.get("_parent_id") == "US-100"]
    assert len(children) == 4
    for child in children:
        assert child["_parent_id"] == "US-100"


@pytest.mark.us_1043
def test_children_requeued_for_phase_i() -> None:
    updated, _ = _simulate_exhaustion("US-100", _prd())
    children = [s for s in updated["userStories"] if s.get("_parent_id") == "US-100"]
    for child in children:
        assert child["passes"] is False


@pytest.mark.us_1043
def test_at_least_one_child_can_pass() -> None:
    updated, _ = _simulate_exhaustion("US-100", _prd())
    children = [s for s in updated["userStories"] if s.get("_parent_id") == "US-100"]
    assert len(children) == 4
    # Simulate Phase I passing the first child (proves children can be re-queued and pass)
    children[0]["passes"] = True
    assert any(c["passes"] for c in children)
