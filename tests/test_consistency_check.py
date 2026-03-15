#!/usr/bin/env python3
"""Tests for lib/consistency_check.py (US-228)"""

import json
import tempfile
from pathlib import Path

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from consistency_check import ConsistencyChecker, flag_stories_in_prd


class TestConsistencyChecker:
    """Test the ConsistencyChecker class."""

    @pytest.fixture
    def checker(self):
        return ConsistencyChecker(threshold=0.8)

    def test_identical_stories(self, checker):
        """Identical stories should have 100% similarity."""
        story = {
            "id": "US-001",
            "title": "Test story",
            "description": "A test",
            "acceptanceCriteria": ["criterion 1", "criterion 2"],
        }

        result = checker.compare_stories(story, story)
        assert result["story_id"] == "US-001"
        assert result["low_confidence_fields"] == []
        assert result["requires_human_review"] is False
        assert result["low_confidence_percentage"] == 0.0

    def test_different_acceptance_criteria(self, checker):
        """Different acceptance criteria should be flagged."""
        v1 = {
            "id": "US-002",
            "acceptanceCriteria": ["criterion 1", "criterion 2"],
        }
        v2 = {
            "id": "US-002",
            "acceptanceCriteria": ["criterion 1", "criterion 3"],
        }

        result = checker.compare_stories(v1, v2)
        assert "acceptanceCriteria" in result["low_confidence_fields"]
        assert result["low_confidence_percentage"] > 0

    def test_partial_overlap_criteria(self, checker):
        """Criteria with partial overlap should have similarity > 0.5."""
        v1 = {
            "id": "US-003",
            "acceptanceCriteria": ["add login", "add signup", "add password reset"],
        }
        v2 = {
            "id": "US-003",
            "acceptanceCriteria": ["add login", "add signup", "add MFA"],
        }

        result = checker.compare_stories(v1, v2)
        # 2 of 3 elements match → Jaccard: 2/(3+3-2) = 2/4 = 0.5
        # Should be flagged as low_confidence (0.5 < 0.8)
        assert "acceptanceCriteria" in result["low_confidence_fields"]

    def test_threshold_configuration(self):
        """Lower threshold should accept more similarity."""
        checker = ConsistencyChecker(threshold=0.5)
        v1 = {
            "id": "US-004",
            "acceptanceCriteria": ["a", "b", "c"],
        }
        v2 = {
            "id": "US-004",
            "acceptanceCriteria": ["a", "b", "d"],
        }

        result = checker.compare_stories(v1, v2)
        # Jaccard: 2/4 = 0.5, which should NOT be flagged (>= threshold)
        assert "acceptanceCriteria" not in result["low_confidence_fields"]

    def test_multiple_divergent_fields_triggers_review(self, checker):
        """If >20% of fields diverge, requires_human_review should be True."""
        v1 = {
            "id": "US-005",
            "acceptanceCriteria": ["a"],
            "description": "desc1",
            "technicalNotes": ["note1"],
            "priority": "high",
            "estimatedComplexity": "small",
        }
        v2 = {
            "id": "US-005",
            "acceptanceCriteria": ["b"],
            "description": "desc2",
            "technicalNotes": ["note2"],
            "priority": "low",
            "estimatedComplexity": "large",
        }

        result = checker.compare_stories(v1, v2)
        # 5 fields compared, all diverged → 100% low_confidence
        assert result["requires_human_review"] is True
        assert result["low_confidence_percentage"] == 100.0

    def test_skip_missing_fields(self, checker):
        """Fields that are missing in both versions should not be counted."""
        v1 = {
            "id": "US-006",
            "description": "same",
        }
        v2 = {
            "id": "US-006",
            "description": "same",
        }

        result = checker.compare_stories(v1, v2)
        assert result["total_compared_fields"] == 1  # only description
        assert result["low_confidence_percentage"] == 0.0

    def test_field_similarity_strings(self, checker):
        """String fields should use exact equality."""
        assert checker._field_similarity("same", "same", "test") == 1.0
        assert checker._field_similarity("diff1", "diff2", "test") == 0.0
        assert checker._field_similarity("text", None, "test") == 0.0

    def test_field_similarity_lists(self, checker):
        """List fields should use Jaccard similarity."""
        # Identical lists
        assert checker._field_similarity(["a", "b"], ["a", "b"], "test") == 1.0

        # No overlap
        assert checker._field_similarity(["a"], ["b"], "test") == 0.0

        # Partial overlap: Jaccard = 1/2 = 0.5
        sim = checker._field_similarity(["a", "b"], ["a", "c"], "test")
        assert sim == pytest.approx(0.5, rel=0.01)

    def test_field_similarity_dicts(self, checker):
        """Dict fields should recurse and average component similarities."""
        # Identical dicts
        dict1 = {"name": "test", "count": 5}
        dict2 = {"name": "test", "count": 5}
        assert checker._field_similarity(dict1, dict2, "test") == 1.0

        # Different dict structures
        dict1 = {"name": "test"}
        dict2 = {"value": "test"}
        assert checker._field_similarity(dict1, dict2, "test") == 0.5


class TestFlagStoriesInPrd:
    """Test the flag_stories_in_prd integration function."""

    def test_flag_stories_with_human_review(self):
        """Stories flagged for human review should be marked in prd.json."""
        prd = {
            "userStories": [
                {"id": "US-001", "title": "Story 1", "passes": False},
                {"id": "US-002", "title": "Story 2", "passes": False},
            ]
        }
        reports = [
            {
                "story_id": "US-001",
                "low_confidence_fields": [],
                "divergence_report": {},
                "requires_human_review": False,
                "low_confidence_percentage": 0.0,
                "total_compared_fields": 5,
            },
            {
                "story_id": "US-002",
                "low_confidence_fields": ["acceptanceCriteria", "description"],
                "divergence_report": {},
                "requires_human_review": True,
                "low_confidence_percentage": 40.0,
                "total_compared_fields": 5,
            },
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(prd, f)
            prd_file = f.name

        try:
            result = flag_stories_in_prd(prd_file, reports)
            assert result["updated_stories"] == 2
            assert result["human_review_count"] == 1
            assert "US-002" in result["paused_stories"]

            # Verify PRD was updated
            with open(prd_file) as f:
                updated_prd = json.load(f)

            story1 = next(s for s in updated_prd["userStories"] if s["id"] == "US-001")
            story2 = next(s for s in updated_prd["userStories"] if s["id"] == "US-002")

            assert story1["_requires_human_review"] is False
            assert story2["_requires_human_review"] is True
            assert "_human_review_reason" in story2

        finally:
            Path(prd_file).unlink()

    def test_skip_consistency_check_flag(self):
        """--skip-consistency-check should prevent PRD modifications."""
        prd = {
            "userStories": [{"id": "US-001", "title": "Story 1", "passes": False}]
        }
        reports = [
            {
                "story_id": "US-001",
                "low_confidence_fields": ["acceptanceCriteria"],
                "divergence_report": {},
                "requires_human_review": True,
                "low_confidence_percentage": 50.0,
                "total_compared_fields": 2,
            }
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(prd, f)
            prd_file = f.name

        try:
            result = flag_stories_in_prd(prd_file, reports, skip_consistency_check=True)
            assert result["updated_stories"] == 0
            assert result["human_review_count"] == 0

            # Verify PRD was NOT modified
            with open(prd_file) as f:
                unchanged_prd = json.load(f)

            story = unchanged_prd["userStories"][0]
            assert "_requires_human_review" not in story

        finally:
            Path(prd_file).unlink()
