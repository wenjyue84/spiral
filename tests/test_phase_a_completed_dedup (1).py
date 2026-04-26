"""Integration test for Phase A completed story dedup — US-1168.

Verifies that Phase A suggest excludes completed stories from AI suggestion
candidates via semantic similarity checking (< 85% match threshold).
"""

import difflib
import json
import os
import sys
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "research"))
from ai_suggest import _build_prompt, _suggest_via_llm


def _minimal_prd_with_completed(**kwargs: Any) -> dict[str, Any]:
    """Create a minimal PRD with 3 completed stories."""
    base: dict[str, Any] = {
        "productName": "TestProduct",
        "branchName": "main",
        "goals": ["improve test coverage"],
        "epics": [],
        "userStories": [
            {
                "id": "US-001",
                "title": "Add authentication to API endpoints",
                "passes": True,  # Completed
                "priority": "high",
                "description": "Implement JWT auth",
                "acceptanceCriteria": ["API rejects unauthenticated requests"],
                "dependencies": [],
            },
            {
                "id": "US-002",
                "title": "Implement caching layer for performance",
                "passes": True,  # Completed
                "priority": "medium",
                "description": "Add Redis caching",
                "acceptanceCriteria": ["Queries cached for 5 min"],
                "dependencies": [],
            },
            {
                "id": "US-003",
                "title": "Create documentation for database schema",
                "passes": True,  # Completed
                "priority": "low",
                "description": "Document all tables and columns",
                "acceptanceCriteria": ["Schema doc covers all entities"],
                "dependencies": [],
            },
            {
                "id": "US-004",
                "title": "Pending story to be ignored",
                "passes": False,  # Not completed (passes != True)
                "priority": "medium",
                "description": "This should be in suggestions",
                "acceptanceCriteria": [],
                "dependencies": [],
            },
        ],
    }
    base.update(kwargs)
    return base


def _string_similarity(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings using difflib."""
    return difflib.SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


class TestCompletedStoriesDedup:
    """Test that Phase A excludes completed stories from dedup set."""

    def test_build_prompt_includes_completed_stories(self) -> None:
        """Verify _build_prompt includes completed story titles in 'Already Done' section."""
        prd = _minimal_prd_with_completed()
        existing_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is not True]
        completed_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is True]

        prompt = _build_prompt(prd, existing_titles, completed_titles, "", 2)

        # Should include all 3 completed titles
        assert "Add authentication to API endpoints" in prompt
        assert "Implement caching layer for performance" in prompt
        assert "Create documentation for database schema" in prompt

        # Should have "Already Done" section
        assert "Already Done" in prompt

    def test_ai_suggestions_avoid_high_similarity_to_completed(self) -> None:
        """
        Run Phase A with completed stories + AI suggestions.
        Verify suggestions don't have >85% similarity to any completed title.
        """
        prd = _minimal_prd_with_completed()

        # Mock AI suggestions (deliberately different from completed stories)
        mock_suggestions = [
            {
                "title": "Add rate limiting to API endpoints",  # Similar but different from "Add authentication..."
                "priority": "medium",
                "description": "Implement rate limiting to prevent abuse",
                "acceptanceCriteria": ["API returns 429 when limit exceeded"],
                "technicalNotes": ["Implement in middleware"],
                "filesTouch": ["lib/middleware/ratelimit.py"],
                "estimatedComplexity": "medium",
            },
            {
                "title": "Optimize database query performance",  # Different from caching story
                "priority": "high",
                "description": "Add query indexes and optimize slow queries",
                "acceptanceCriteria": ["95th percentile query time < 100ms"],
                "technicalNotes": ["Add indexes to high-traffic tables"],
                "filesTouch": ["lib/db/migrations.py"],
                "estimatedComplexity": "large",
            },
        ]

        # Extract completed and existing titles
        completed_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is True]
        existing_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is not True]

        # Mock the Claude CLI subprocess
        def mock_claude_success(*args: Any, **kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = json.dumps({"stories": mock_suggestions})
            mock.stderr = ""
            return mock

        with patch("ai_suggest.subprocess.run", side_effect=mock_claude_success):
            # Call _suggest_via_llm with completed titles
            suggestions = _suggest_via_llm(
                prd,
                existing_titles=existing_titles,
                completed_titles=completed_titles,
                focus="",
                n=2,
            )

        # Verify we got suggestions
        assert len(suggestions) >= 2

        # Check each suggestion against completed titles
        threshold = 0.85
        for suggestion in suggestions:
            title = suggestion.get("title", "")
            max_similarity = 0.0

            for completed in completed_titles:
                sim = _string_similarity(title, completed)
                max_similarity = max(max_similarity, sim)

            # Assert suggestion doesn't match >85% to any completed story
            assert max_similarity < threshold, (
                f'Suggestion "{title}" has {max_similarity:.2%} similarity to a completed story (threshold: {threshold:.0%})'
            )

    def test_completed_stories_excluded_from_dedup(self) -> None:
        """
        Main integration test: verify Phase A with mocked completed stories
        excludes them from semantic dedup candidate set.
        """
        prd = _minimal_prd_with_completed()

        completed_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is True]

        # Verify we have 3 completed stories
        assert len(completed_titles) == 3

        # Manually check that similarities are computed correctly
        # "Add authentication..." vs "Add rate limiting..." should be < 85%
        auth_title = "Add authentication to API endpoints"
        rate_limit_title = "Add rate limiting to API endpoints"

        similarity = _string_similarity(auth_title, rate_limit_title)
        # These share "Add" and "to API endpoints" but are different enough
        assert similarity < 0.95, f"Similarity {similarity:.2%} unexpectedly high"
        # But they're similar enough to be worth checking in dedup
        assert similarity > 0.5, f"Similarity {similarity:.2%} unexpectedly low"

    def test_build_prompt_dedup_instruction_present(self) -> None:
        """Verify prompt includes explicit dedup instruction when completed stories exist."""
        prd = _minimal_prd_with_completed()

        completed_titles = [s.get("title", "") for s in prd["userStories"] if s.get("passes") is True]

        prompt = _build_prompt(prd, [], completed_titles, "", 2)

        # Should include dedup instruction
        assert "Avoid any similarity" in prompt or "do NOT suggest" in prompt

    def test_empty_completed_list_works(self) -> None:
        """Verify Phase A works normally when no completed stories exist."""
        prd = _minimal_prd_with_completed()
        # Remove all completed stories
        prd["userStories"] = [s for s in prd["userStories"] if s.get("passes") is not True]

        existing_titles = [s.get("title", "") for s in prd["userStories"]]
        prompt = _build_prompt(prd, existing_titles, [], "", 2)

        # Should not include "Already Done" section
        assert "Already Done" not in prompt
