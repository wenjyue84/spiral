"""Unit tests for story_compatibility.py — CompatibilityMatrix class."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from story_compatibility import CompatibilityMatrix


class TestCompatibilityScoreOverlap:
    """Tests for compute_score() — Jaccard similarity of filesTouch."""

    def test_no_shared_files_returns_zero(self) -> None:
        """Stories with no shared filesTouch return 0.0."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py", "file_b.py"]},
            {"id": "US-002", "filesTouch": ["file_c.py", "file_d.py"]},
        ]
        matrix = CompatibilityMatrix(stories)
        score = matrix.compute_score("US-001", "US-002")
        assert score == 0.0

    def test_full_overlap_returns_one(self) -> None:
        """Stories with identical filesTouch return 1.0."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py", "file_b.py"]},
            {"id": "US-002", "filesTouch": ["file_a.py", "file_b.py"]},
        ]
        matrix = CompatibilityMatrix(stories)
        score = matrix.compute_score("US-001", "US-002")
        assert score == 1.0

    def test_partial_overlap(self) -> None:
        """Stories with partial filesTouch overlap return correct Jaccard score."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py", "file_b.py", "file_c.py"]},
            {"id": "US-002", "filesTouch": ["file_a.py", "file_d.py"]},
        ]
        matrix = CompatibilityMatrix(stories)
        # intersection = {file_a.py} = 1
        # union = {file_a.py, file_b.py, file_c.py, file_d.py} = 4
        # score = 1/4 = 0.25
        score = matrix.compute_score("US-001", "US-002")
        assert abs(score - 0.25) < 0.001

    def test_missing_story_returns_zero(self) -> None:
        """Requesting score for nonexistent story ID returns 0.0."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"]},
        ]
        matrix = CompatibilityMatrix(stories)
        score = matrix.compute_score("US-001", "NONEXISTENT")
        assert score == 0.0

    def test_empty_filesTouch_returns_zero(self) -> None:
        """Stories with empty filesTouch lists return 0.0."""
        stories = [
            {"id": "US-001", "filesTouch": []},
            {"id": "US-002", "filesTouch": []},
        ]
        matrix = CompatibilityMatrix(stories)
        score = matrix.compute_score("US-001", "US-002")
        assert score == 0.0

    def test_symmetric_score(self) -> None:
        """compute_score is symmetric: score(a,b) == score(b,a)."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py", "file_b.py"]},
            {"id": "US-002", "filesTouch": ["file_a.py", "file_c.py"]},
        ]
        matrix = CompatibilityMatrix(stories)
        score_ab = matrix.compute_score("US-001", "US-002")
        score_ba = matrix.compute_score("US-002", "US-001")
        assert abs(score_ab - score_ba) < 0.001


class TestCircularDependencyDetection:
    """Tests for validate_dag() — cycle detection in dependency graph."""

    def test_no_cycle_passes(self) -> None:
        """DAG with no cycles passes validation."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        # Should not raise
        matrix.validate_dag()

    def test_self_cycle_raises(self) -> None:
        """Story with self-dependency raises ValueError."""
        stories = [
            {"id": "US-001", "dependencies": ["US-001"]},
        ]
        matrix = CompatibilityMatrix(stories)
        with pytest.raises(ValueError, match="Circular dependency detected"):
            matrix.validate_dag()

    def test_two_node_cycle_raises(self) -> None:
        """A → B → A cycle raises ValueError."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        matrix = CompatibilityMatrix(stories)
        with pytest.raises(ValueError, match="Circular dependency detected"):
            matrix.validate_dag()

    def test_three_node_cycle_raises(self) -> None:
        """A → B → C → A cycle raises ValueError."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": ["US-001"]},
        ]
        matrix = CompatibilityMatrix(stories)
        with pytest.raises(ValueError, match="Circular dependency detected"):
            matrix.validate_dag()

    def test_missing_dependency_handled(self) -> None:
        """Dependency on nonexistent story ID is handled gracefully."""
        stories = [
            {"id": "US-001", "dependencies": ["NONEXISTENT"]},
        ]
        matrix = CompatibilityMatrix(stories)
        # Should not raise (missing dependencies are ignored)
        matrix.validate_dag()

    def test_empty_dependencies(self) -> None:
        """Stories with no dependencies pass validation."""
        stories = [
            {"id": "US-001", "dependencies": []},
            {"id": "US-002", "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        matrix.validate_dag()


class TestBatchSuggestion:
    """Tests for suggest_batches() — grouping independent stories."""

    def test_all_independent_one_batch(self) -> None:
        """Stories with no overlaps and no dependencies are grouped in one batch."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"], "dependencies": []},
            {"id": "US-002", "filesTouch": ["file_b.py"], "dependencies": []},
            {"id": "US-003", "filesTouch": ["file_c.py"], "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        # All independent → one batch with all 3
        assert len(batches) == 1
        assert set(batches[0]) == {"US-001", "US-002", "US-003"}

    def test_file_overlap_separate_batches(self) -> None:
        """Stories with file overlap are placed in separate batches."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"], "dependencies": []},
            {"id": "US-002", "filesTouch": ["file_a.py"], "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        # File overlap → separate batches
        assert len(batches) == 2

    def test_dependency_separate_batches(self) -> None:
        """Stories with dependencies are placed in separate batches."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"], "dependencies": []},
            {"id": "US-002", "filesTouch": ["file_b.py"], "dependencies": ["US-001"]},
        ]
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        # Dependency → separate batches
        assert len(batches) == 2

    def test_mixed_independent_and_dependent(self) -> None:
        """Mix of independent and dependent stories creates appropriate batches."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"], "dependencies": []},
            {"id": "US-002", "filesTouch": ["file_b.py"], "dependencies": ["US-001"]},
            {"id": "US-003", "filesTouch": ["file_c.py"], "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        # US-001 and US-003 can be independent (different files, no deps)
        # US-002 depends on US-001
        assert len(batches) >= 2

    def test_batch_contains_all_stories(self) -> None:
        """All stories appear in exactly one batch."""
        stories = [
            {"id": "US-001", "filesTouch": ["file_a.py"], "dependencies": []},
            {"id": "US-002", "filesTouch": ["file_b.py"], "dependencies": []},
            {"id": "US-003", "filesTouch": ["file_c.py"], "dependencies": []},
        ]
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        all_stories = set()
        for batch in batches:
            all_stories.update(batch)
        assert all_stories == {"US-001", "US-002", "US-003"}

    def test_empty_stories_list(self) -> None:
        """Empty stories list returns empty batches."""
        stories: list[dict[str, object]] = []
        matrix = CompatibilityMatrix(stories)
        batches = matrix.suggest_batches()
        assert batches == []
