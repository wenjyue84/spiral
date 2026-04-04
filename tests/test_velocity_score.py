"""Unit tests for lib/routing/velocity_score.py"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import pytest
from routing.velocity_score import compute_velocity_score, sort_candidates_by_velocity


class TestVelocityScoring:
    """Test velocity score computation."""

    def test_simple_story_high_score(self) -> None:
        """Simple story with few files scores >70."""
        story = {
            "title": "Add new button",
            "description": "Add submit button",
            "filesTouch": ["src/button.tsx"],
        }
        score = compute_velocity_score(story)
        assert score > 70, f"Simple story should score >70, got {score}"

    def test_minimal_files_no_keywords(self) -> None:
        """Story with ≤3 files and no keywords scores >70."""
        story = {
            "title": "Update CSS",
            "filesTouch": ["styles/a.css", "styles/b.css"],
        }
        score = compute_velocity_score(story)
        assert score > 70

    def test_complex_story_low_score(self) -> None:
        """Complex story with many files and keywords scores <40."""
        story = {
            "title": "Refactor authentication architecture",
            "description": "Complete redesign of infrastructure",
            "filesTouch": ["a.ts", "b.ts", "c.ts", "d.ts", "e.ts", "f.ts"],
        }
        score = compute_velocity_score(story)
        assert score < 40, f"Complex story should score <40, got {score}"

    def test_file_penalty(self) -> None:
        """More files reduce score."""
        story_few = {"title": "Task", "filesTouch": ["a.ts", "b.ts", "c.ts"]}
        story_many = {"title": "Task", "filesTouch": ["a.ts", "b.ts", "c.ts", "d.ts", "e.ts"]}
        score_few = compute_velocity_score(story_few)
        score_many = compute_velocity_score(story_many)
        assert score_few > score_many

    def test_keyword_penalty(self) -> None:
        """Architecture keywords reduce score."""
        story_simple = {"title": "Add button", "filesTouch": ["a.ts"]}
        story_refactor = {"title": "Refactor handler", "filesTouch": ["a.ts"]}
        score_simple = compute_velocity_score(story_simple)
        score_refactor = compute_velocity_score(story_refactor)
        assert score_simple > score_refactor

    def test_no_files_no_keywords_perfect_score(self) -> None:
        """Story with no files/keywords gets perfect score."""
        story = {"title": "Simple task"}
        score = compute_velocity_score(story)
        assert score == 100.0

    def test_multiple_keywords_stacked_penalty(self) -> None:
        """Multiple keywords compound the penalty."""
        story = {
            "title": "Refactor and migrate database",
            "description": "Complete redesign and overhaul",
            "filesTouch": ["db.ts"],
        }
        score = compute_velocity_score(story)
        # 4 keywords × 15 = -60 penalty (capped at -50) → 50
        assert score <= 50


class TestSortingByVelocity:
    """Test sorting candidates by velocity."""

    def test_sort_puts_simple_first(self) -> None:
        """Sort puts quick-win stories first."""
        candidates = [
            {
                "id": "complex",
                "title": "Refactor database",
                "filesTouch": ["d1.ts", "d2.ts", "d3.ts", "d4.ts", "d5.ts"],
            },
            {
                "id": "simple",
                "title": "Add label",
                "filesTouch": ["label.ts"],
            },
        ]

        sorted_list = sort_candidates_by_velocity(candidates)
        assert sorted_list[0]["id"] == "simple"
        assert sorted_list[1]["id"] == "complex"

    def test_sort_descending_by_default(self) -> None:
        """Default sort is descending (high scores first)."""
        candidates = [
            {"title": "Complex overhaul", "filesTouch": ["a", "b", "c", "d", "e"]},
            {"title": "Simple fix", "filesTouch": ["x"]},
        ]

        sorted_list = sort_candidates_by_velocity(candidates)
        assert sorted_list[0]["title"] == "Simple fix"


class TestAcceptanceCriteria:
    """Test acceptance criteria."""

    def test_ac1_computes_from_files_and_keywords(self) -> None:
        """AC1: Score computed from filesToTouch and complexity keywords."""
        story = {
            "title": "Refactor API handler",
            "filesTouch": ["api/handler.ts"],
        }
        score = compute_velocity_score(story)
        assert 0 <= score <= 100

    def test_ac2_simple_stories_above_70(self) -> None:
        """AC2: ≤3 files + no keywords → score >70."""
        story = {
            "title": "Update text",
            "filesTouch": ["text.ts", "label.ts"],
        }
        score = compute_velocity_score(story)
        assert score > 70

    def test_ac3_complex_stories_below_40(self) -> None:
        """AC3: Complex stories → score <40."""
        story = {
            "title": "Architecture refactor migration overhaul",
            "description": "Complete infrastructure redesign with legacy restructure",
            "filesTouch": ["a.ts", "b.ts", "c.ts", "d.ts", "e.ts", "f.ts"],
        }
        score = compute_velocity_score(story)
        assert score < 40, f"Complex story should score <40, got {score}"

    def test_ac4_ordering_5_stories(self) -> None:
        """AC4: Score & order 5 stories (2 simple, 3 complex)."""
        stories = [
            {"id": "simple-1", "title": "Add button", "filesTouch": ["btn.ts"]},
            {
                "id": "complex-1",
                "title": "Refactor API",
                "filesTouch": ["a.ts", "b.ts", "c.ts", "d.ts"],
            },
            {"id": "simple-2", "title": "Update label", "filesTouch": ["lbl.ts"]},
            {
                "id": "complex-2",
                "title": "Database migration",
                "filesTouch": ["d1.ts", "d2.ts", "d3.ts"],
            },
            {
                "id": "complex-3",
                "title": "Infrastructure overhaul",
                "filesTouch": ["i1.ts", "i2.ts", "i3.ts", "i4.ts", "i5.ts"],
            },
        ]

        sorted_stories = sort_candidates_by_velocity(stories)
        ordered_ids = [s["id"] for s in sorted_stories]

        # Simple stories should come before complex
        simple_indices = [i for i, sid in enumerate(ordered_ids) if sid.startswith("simple")]
        complex_indices = [
            i for i, sid in enumerate(ordered_ids) if sid.startswith("complex")
        ]

        if simple_indices and complex_indices:
            assert max(simple_indices) < min(complex_indices)
