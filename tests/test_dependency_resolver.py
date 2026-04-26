#!/usr/bin/env python3
"""Tests for lib/dependency_resolver.py — NLP-based dependency inference."""

import sys
from pathlib import Path

# Ensure we can import from lib/
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from dependency_resolver import (
    compute_dag_metrics,
    extract_story_ids,
    infer_dependencies,
)


class TestExtractStoryIds:
    """Test story ID extraction from text."""

    def test_extract_us_format(self) -> None:
        """Extract US-NNN format IDs."""
        text = "This depends on US-1234 and requires US-5678"
        ids = extract_story_ids(text)
        assert "US-1234" in ids
        assert "US-5678" in ids

    def test_extract_mixed_formats(self) -> None:
        """Extract mixed ID formats."""
        text = "After US-100 and UT-200 complete"
        ids = extract_story_ids(text)
        assert "US-100" in ids
        assert "UT-200" in ids

    def test_no_duplicate_ids(self) -> None:
        """De-duplicate extracted IDs."""
        text = "US-1234 requires US-1234"
        ids = extract_story_ids(text)
        assert ids.count("US-1234") == 1


class TestInferDependencies:
    """Test NLP-based dependency inference."""

    def test_requires_keyword(self) -> None:
        """Detect 'requires' keyword."""
        stories = [
            {"id": "US-1", "title": "Feature A", "description": ""},
            {"id": "US-2", "title": "Feature B", "description": "Requires US-1"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_depends_on_keyword(self) -> None:
        """Detect 'depends on' keyword."""
        stories = [
            {"id": "US-1", "title": "Setup", "description": ""},
            {"id": "US-2", "title": "Feature", "description": "Depends on US-1 to work"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_blocked_by_keyword(self) -> None:
        """Detect 'blocked by' keyword."""
        stories = [
            {"id": "US-1", "title": "Auth", "description": ""},
            {"id": "US-2", "title": "Dashboard", "description": "Blocked by US-1"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_after_keyword(self) -> None:
        """Detect 'after' keyword."""
        stories = [
            {"id": "US-1", "title": "Phase 1", "description": ""},
            {"id": "US-2", "title": "Phase 2", "description": "After US-1 is done"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_must_complete_keyword(self) -> None:
        """Detect 'must complete' keyword."""
        stories = [
            {"id": "US-1", "title": "Migration", "description": ""},
            {"id": "US-2", "title": "Validation", "description": "US-1 must complete first"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_no_self_reference(self) -> None:
        """Prevent self-referencing dependencies."""
        stories = [
            {"id": "US-1", "title": "Feature", "description": "Requires US-1"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" not in inferred["US-1"]

    def test_nonexistent_story_ignored(self) -> None:
        """Ignore references to non-existent stories."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": "Requires US-999"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-999" not in inferred["US-2"]

    def test_multiple_dependencies(self) -> None:
        """Infer multiple dependencies for one story."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": ""},
            {
                "id": "US-3",
                "title": "C",
                "description": "Requires US-1 and US-2",
            },
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-3"]
        assert "US-2" in inferred["US-3"]


class TestComputeDagMetrics:
    """Test DAG metric computation."""

    def test_depth_in_dag_simple_chain(self) -> None:
        """Compute depth for linear dependency chain."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": ""},
            {"id": "US-3", "title": "C", "description": ""},
        ]
        inferred = {"US-1": [], "US-2": ["US-1"], "US-3": ["US-2"]}
        metrics = compute_dag_metrics(stories, inferred)

        assert metrics["US-1"]["depth_in_dag"] == 0
        assert metrics["US-2"]["depth_in_dag"] == 1
        assert metrics["US-3"]["depth_in_dag"] == 2

    def test_blocked_by_field(self) -> None:
        """Verify blocked_by field is reverse of depends_on."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": ""},
        ]
        inferred = {"US-1": ["US-2"], "US-2": []}
        metrics = compute_dag_metrics(stories, inferred)

        assert "US-1" in metrics["US-2"]["blocked_by"]
        assert len(metrics["US-1"]["blocked_by"]) == 0

    def test_blocker_count(self) -> None:
        """Compute blocker_count: how many stories depend on me."""
        stories = [
            {"id": "US-1", "title": "Core", "description": ""},
            {"id": "US-2", "title": "A", "description": ""},
            {"id": "US-3", "title": "B", "description": ""},
        ]
        inferred = {"US-1": [], "US-2": ["US-1"], "US-3": ["US-1"]}
        metrics = compute_dag_metrics(stories, inferred)

        assert metrics["US-1"]["blocker_count"] == 2
        assert metrics["US-2"]["blocker_count"] == 0

    def test_critical_flag(self) -> None:
        """Mark high-impact stories as critical."""
        stories = [
            {"id": "US-1", "title": "Core", "description": ""},
            {"id": "US-2", "title": "A", "description": ""},
            {"id": "US-3", "title": "B", "description": ""},
            {"id": "US-4", "title": "C", "description": ""},
        ]
        # US-1 blocks US-2, US-3, US-4 (3 blockers)
        inferred = {
            "US-1": [],
            "US-2": ["US-1"],
            "US-3": ["US-1"],
            "US-4": ["US-1"],
        }
        metrics = compute_dag_metrics(stories, inferred)

        # US-1 should be marked critical (highest blocker count)
        assert metrics["US-1"]["critical"] is True
        assert metrics["US-2"]["critical"] is False

    def test_complex_dag_metrics(self) -> None:
        """Verify all metrics in a realistic DAG."""
        stories = [
            {"id": "US-1", "title": "Setup", "description": ""},
            {"id": "US-2", "title": "Auth", "description": ""},
            {"id": "US-3", "title": "Dashboard", "description": ""},
            {"id": "US-4", "title": "Monitoring", "description": ""},
        ]
        # US-3 depends on US-1 and US-2; US-4 depends on US-3
        inferred = {
            "US-1": [],
            "US-2": [],
            "US-3": ["US-1", "US-2"],
            "US-4": ["US-3"],
        }
        metrics = compute_dag_metrics(stories, inferred)

        # Verify structure
        assert metrics["US-1"]["depth_in_dag"] == 0
        assert metrics["US-3"]["depth_in_dag"] == 1
        assert metrics["US-4"]["depth_in_dag"] == 2

        # Verify blocked_by relationships
        assert "US-3" in metrics["US-1"]["blocked_by"]
        assert "US-3" in metrics["US-2"]["blocked_by"]
        assert "US-4" in metrics["US-3"]["blocked_by"]


class TestCyclicDependencies:
    """Test cycle detection in DAGs."""

    def test_cycle_detection_simple(self) -> None:
        """Test that simple cycles are detected."""
        stories = [
            {"id": "US-1", "title": "A", "description": "Requires US-2"},
            {"id": "US-2", "title": "B", "description": "Requires US-1"},
        ]
        inferred = {"US-1": ["US-2"], "US-2": ["US-1"]}
        metrics = compute_dag_metrics(stories, inferred)

        # Cycle should result in undefined depth (topological sort fails)
        # Both stories should have same depth (no progress in sorting)
        assert metrics["US-1"]["depth_in_dag"] == metrics["US-2"]["depth_in_dag"]

    def test_cycle_detection_three_way(self) -> None:
        """Test cycle involving three stories."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": ""},
            {"id": "US-3", "title": "C", "description": ""},
        ]
        inferred = {"US-1": ["US-2"], "US-2": ["US-3"], "US-3": ["US-1"]}
        metrics = compute_dag_metrics(stories, inferred)

        # All three in cycle should end up at same depth
        depths = [
            metrics["US-1"]["depth_in_dag"],
            metrics["US-2"]["depth_in_dag"],
            metrics["US-3"]["depth_in_dag"],
        ]
        assert len(set(depths)) == 1  # All same


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_stories_list(self) -> None:
        """Handle empty stories list gracefully."""
        stories: list[dict] = []
        inferred = infer_dependencies(stories)
        assert inferred == {}

    def test_stories_without_description(self) -> None:
        """Handle stories missing description field."""
        stories = [
            {"id": "US-1", "title": "Feature A"},
            {"id": "US-2", "title": "Feature B requires US-1"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_case_insensitive_keywords(self) -> None:
        """Detect keywords regardless of case."""
        stories = [
            {"id": "US-1", "title": "A", "description": ""},
            {"id": "US-2", "title": "B", "description": "REQUIRES US-1"},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred["US-2"]

    def test_story_without_id_skipped(self) -> None:
        """Skip stories without ID field."""
        stories = [
            {"title": "No ID", "description": ""},
            {"id": "US-1", "title": "With ID", "description": ""},
        ]
        inferred = infer_dependencies(stories)
        assert "US-1" in inferred
        assert len(inferred) == 1
