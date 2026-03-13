"""Unit tests for slice_prd.py (PRD batch slicing and merge-back)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from slice_prd import slice_prd, merge_batch_results


def _story(sid, passes=False, priority="medium", decomposed=False, extra=None):
    """Create a minimal valid story dict."""
    s = {
        "id": sid,
        "title": f"Story {sid}",
        "passes": passes,
        "priority": priority,
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    if decomposed:
        s["_decomposed"] = True
    if extra:
        s.update(extra)
    return s


def _prd(stories):
    return {"productName": "Test", "branchName": "main", "userStories": stories}


# ── slice_prd tests ──────────────────────────────────────────────────────────


class TestSlicePrd:
    def test_batch_size_zero_returns_all(self):
        """batch_size=0 disables slicing — all stories returned."""
        prd = _prd([_story("US-001"), _story("US-002"), _story("US-003")])
        result = slice_prd(prd, 0)
        assert len(result["userStories"]) == 3

    def test_batch_size_negative_returns_all(self):
        """Negative batch size treated same as 0 (disabled)."""
        prd = _prd([_story("US-001"), _story("US-002")])
        result = slice_prd(prd, -1)
        assert len(result["userStories"]) == 2

    def test_batch_limits_pending_stories(self):
        """Only N pending stories kept; passed stories always included."""
        stories = [
            _story("US-001", passes=True),
            _story("US-002", priority="high"),
            _story("US-003", priority="medium"),
            _story("US-004", priority="low"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 2)
        ids = [s["id"] for s in result["userStories"]]
        assert "US-001" in ids  # passed — always kept
        assert "US-002" in ids  # high priority — in batch
        assert "US-003" in ids  # medium — in batch (2nd slot)
        assert "US-004" not in ids  # low — outside batch

    def test_priority_ordering(self):
        """Higher priority stories selected first."""
        stories = [
            _story("US-001", priority="low"),
            _story("US-002", priority="critical"),
            _story("US-003", priority="high"),
            _story("US-004", priority="medium"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 2)
        ids = [s["id"] for s in result["userStories"]]
        assert "US-002" in ids  # critical
        assert "US-003" in ids  # high
        assert "US-001" not in ids  # low — cut
        assert "US-004" not in ids  # medium — cut

    def test_original_order_preserved(self):
        """Stories in the output maintain their original order from the input."""
        stories = [
            _story("US-003", priority="low"),
            _story("US-001", priority="critical"),
            _story("US-002", priority="high"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 2)
        ids = [s["id"] for s in result["userStories"]]
        # US-001 (critical) and US-002 (high) kept; order should be US-001, US-002
        # (matching their original positions in the list)
        assert ids == ["US-001", "US-002"]

    def test_decomposed_parents_always_kept(self):
        """Decomposed parent stories are always included."""
        stories = [
            _story("US-001", decomposed=True),  # decomposed parent
            _story("US-002", priority="low"),
            _story("US-003", priority="low"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 1)
        ids = [s["id"] for s in result["userStories"]]
        assert "US-001" in ids  # decomposed — always kept

    def test_batch_larger_than_pending(self):
        """When batch_size > pending count, all stories kept."""
        stories = [
            _story("US-001", passes=True),
            _story("US-002", priority="high"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 100)
        assert len(result["userStories"]) == 2

    def test_all_passed_no_pending(self):
        """When all stories are passed, empty batch is fine."""
        stories = [
            _story("US-001", passes=True),
            _story("US-002", passes=True),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 5)
        assert len(result["userStories"]) == 2

    def test_top_level_fields_preserved(self):
        """Non-userStories fields are preserved."""
        prd = _prd([_story("US-001")])
        prd["overview"] = "Test overview"
        prd["goals"] = ["goal1"]
        result = slice_prd(prd, 1)
        assert result["productName"] == "Test"
        assert result["overview"] == "Test overview"
        assert result["goals"] == ["goal1"]

    def test_same_priority_stable_order(self):
        """Stories with the same priority maintain original order."""
        stories = [
            _story("US-005", priority="medium"),
            _story("US-003", priority="medium"),
            _story("US-001", priority="medium"),
            _story("US-004", priority="medium"),
            _story("US-002", priority="medium"),
        ]
        prd = _prd(stories)
        result = slice_prd(prd, 3)
        ids = [s["id"] for s in result["userStories"]]
        # First 3 in original order
        assert ids == ["US-005", "US-003", "US-001"]


# ── merge_batch_results tests ───────────────────────────────────────────────


class TestMergeBatchResults:
    def test_pass_status_merged(self):
        """A story marked passes=True in batch is updated in full PRD."""
        full = _prd([_story("US-001"), _story("US-002")])
        batched = _prd([_story("US-001", passes=True)])
        result = merge_batch_results(full, batched)
        by_id = {s["id"]: s for s in result["userStories"]}
        assert by_id["US-001"]["passes"] is True
        assert by_id["US-002"]["passes"] is False

    def test_new_sub_stories_appended(self):
        """Decomposed sub-stories created during batch are added to full PRD."""
        full = _prd([_story("US-001")])
        batched = _prd([
            _story("US-001", decomposed=True, extra={"_decomposedInto": ["US-010", "US-011"]}),
            _story("US-010", extra={"_decomposedFrom": "US-001"}),
            _story("US-011", extra={"_decomposedFrom": "US-001"}),
        ])
        result = merge_batch_results(full, batched)
        ids = [s["id"] for s in result["userStories"]]
        assert "US-010" in ids
        assert "US-011" in ids
        # Parent should be marked decomposed
        parent = next(s for s in result["userStories"] if s["id"] == "US-001")
        assert parent["_decomposed"] is True

    def test_does_not_mutate_inputs(self):
        """merge_batch_results returns a new dict, inputs unchanged."""
        full = _prd([_story("US-001")])
        batched = _prd([_story("US-001", passes=True)])
        original_passes = full["userStories"][0]["passes"]
        merge_batch_results(full, batched)
        assert full["userStories"][0]["passes"] == original_passes

    def test_stories_not_in_batch_unchanged(self):
        """Stories absent from batch remain exactly as in full PRD."""
        full = _prd([_story("US-001"), _story("US-002", priority="low")])
        batched = _prd([_story("US-001", passes=True)])
        result = merge_batch_results(full, batched)
        us002 = next(s for s in result["userStories"] if s["id"] == "US-002")
        assert us002["passes"] is False
        assert us002["priority"] == "low"

    def test_skipped_flag_merged(self):
        """_skipped flag from batch is propagated."""
        full = _prd([_story("US-001")])
        batched = _prd([_story("US-001", extra={"_skipped": True})])
        result = merge_batch_results(full, batched)
        assert result["userStories"][0].get("_skipped") is True

    def test_no_duplicate_sub_stories_on_remerge(self):
        """If sub-stories already exist in full PRD, don't duplicate them."""
        full = _prd([
            _story("US-001"),
            _story("US-010", extra={"_decomposedFrom": "US-001"}),
        ])
        batched = _prd([
            _story("US-001", passes=True),
            _story("US-010", passes=True, extra={"_decomposedFrom": "US-001"}),
        ])
        result = merge_batch_results(full, batched)
        ids = [s["id"] for s in result["userStories"]]
        assert ids.count("US-010") == 1
