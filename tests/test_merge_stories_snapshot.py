"""Snapshot tests for merge_stories.py JSON outputs using syrupy."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from merge_stories import full_sort_key, story_to_prd_entry


class TestMergeStoriesSnapshot:
    """Snapshot tests for stable JSON and dict outputs from merge_stories functions."""

    def test_story_to_prd_entry_snapshot(self, snapshot):
        """Snapshot test for story_to_prd_entry() output format."""
        candidate = {
            "title": "Add feature X to dashboard",
            "priority": "high",
            "description": "Implement feature X for improved UX",
            "acceptanceCriteria": [
                "Feature X is implemented",
                "Tests pass",
            ],
            "dependencies": ["US-99"],
            "estimatedComplexity": "medium",
        }
        result = story_to_prd_entry(candidate, "US-100")
        # Snapshot should capture the exact output structure
        assert result == snapshot

    def test_story_to_prd_entry_minimal_snapshot(self, snapshot):
        """Snapshot test for story_to_prd_entry() with minimal fields."""
        candidate = {
            "title": "Fix bug in parser",
            "priority": "critical",
        }
        result = story_to_prd_entry(candidate, "US-101")
        assert result == snapshot

    def test_full_sort_key_deterministic_snapshot(self, snapshot):
        """Snapshot test for full_sort_key() output to ensure sorting is deterministic."""
        story = {
            "id": "US-50",
            "title": "Refactor logging",
            "priority": "low",
            "complexity": "small",
            "passes": False,
            "dependencies": ["US-40", "US-45"],
        }
        # full_sort_key returns a tuple; snapshot will capture the exact tuple structure
        sort_key = full_sort_key(story)
        assert sort_key == snapshot

    def test_full_sort_key_multiple_stories_snapshot(self, snapshot):
        """Snapshot test comparing sort keys for multiple stories to verify ranking."""
        stories = [
            {
                "id": "US-200",
                "title": "Critical bug fix",
                "priority": "critical",
                "complexity": "small",
                "passes": False,
            },
            {
                "id": "US-201",
                "title": "Nice to have feature",
                "priority": "low",
                "complexity": "large",
                "passes": False,
            },
            {
                "id": "US-202",
                "title": "Medium priority task",
                "priority": "medium",
                "complexity": "medium",
                "passes": False,
            },
        ]
        sort_keys = [full_sort_key(s) for s in stories]
        # Snapshot captures the list of sort keys to verify consistency
        assert sort_keys == snapshot

    def test_story_to_prd_entry_with_all_fields_snapshot(self, snapshot):
        """Snapshot test for story_to_prd_entry() with all optional fields populated."""
        candidate = {
            "title": "Comprehensive feature implementation with all fields",
            "priority": "high",
            "description": "A detailed description of what needs to be implemented",
            "acceptanceCriteria": [
                "User can perform action A",
                "System logs all events",
                "Performance < 100ms",
            ],
            "technicalNotes": ["Use the new API", "Deploy to staging first"],
            "dependencies": ["US-998", "US-997"],
            "estimatedComplexity": "large",
            "_source": "seed",
        }
        result = story_to_prd_entry(candidate, "US-999")
        # Snapshot captures all fields in consistent order
        assert result == snapshot
