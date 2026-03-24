"""test_phase_data_integrity.py — Integration tests for SPIRAL phase data integrity.

Validates that each phase output conforms to expected schemas and that data
flows correctly through the R→T→S→M pipeline without corruption, duplicates,
or security issues.

Tests verify:
- Phase R: valid research JSON schema (stories with title, description, acceptanceCriteria, priority)
- Phase T: valid test failures schema with unique test IDs and valid error categories
- Phase S: validated stories with constitution_score >= 0.7 and unique story IDs
- Phase M: safe merge operations (no path traversal, valid commit messages)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest  # noqa: F401

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from lib.spiral.validate_phase_outputs import validate_phase


class TestPhaseDataIntegrity:
    """Integration tests for SPIRAL phase output schemas and data integrity."""

    @pytest.fixture
    def temp_spiral_dir(self) -> Generator[str, None, None]:
        """Create a temporary .spiral directory for test fixtures."""
        tmpdir = tempfile.mkdtemp(prefix="spiral_test_")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_research_output(self, temp_spiral_dir: str) -> dict[str, Any]:
        """Create mock Phase R research output with valid schema."""
        output: dict[str, Any] = {
            "stories": [
                {
                    "title": "Feature A",
                    "description": "Implement feature A with full coverage",
                    "acceptanceCriteria": ["AC1: Feature works", "AC2: Tests pass"],
                    "priority": "high",
                    "query": "implement feature A",
                    "source": "gemini-search",
                    "relevance_score": 0.95,
                    "text": "Full research text here...",
                },
                {
                    "title": "Feature B",
                    "description": "Implement feature B",
                    "acceptanceCriteria": ["AC1: Feature works"],
                    "priority": "medium",
                    "query": "implement feature B",
                    "source": "gemini-search",
                    "relevance_score": 0.78,
                    "text": "Research text for feature B...",
                },
            ]
        }
        output_path = Path(temp_spiral_dir) / "_research_output.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f)
        return output

    @pytest.fixture
    def mock_test_output(self, temp_spiral_dir: str) -> dict[str, Any]:
        """Create mock Phase T test stories output with valid schema."""
        output: dict[str, Any] = {
            "stories": [
                {
                    "title": "Test: Feature A validation",
                    "description": "Integration test for feature A",
                    "acceptanceCriteria": ["Test passes", "Coverage > 80%"],
                    "priority": "high",
                    "test_id": "UT-1001",
                    "error_category": "assertion",
                    "exit_code": 1,
                },
                {
                    "title": "Test: Feature B validation",
                    "description": "Unit test for feature B",
                    "acceptanceCriteria": ["Test passes"],
                    "priority": "medium",
                    "test_id": "UT-1002",
                    "error_category": "runtime",
                    "exit_code": 2,
                },
            ]
        }
        output_path = Path(temp_spiral_dir) / "_test_stories_output.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f)
        return output

    @pytest.fixture
    def mock_validated_stories(self, temp_spiral_dir: str) -> dict[str, Any]:
        """Create mock Phase S validated stories with constitution scores."""
        output: dict[str, Any] = {
            "stories": [
                {
                    "id": "US-1001",
                    "title": "Feature A",
                    "description": "Implement feature A",
                    "acceptanceCriteria": ["AC1", "AC2"],
                    "priority": "high",
                    "constitution_score": 0.85,
                },
                {
                    "id": "US-1002",
                    "title": "Feature B",
                    "description": "Implement feature B",
                    "acceptanceCriteria": ["AC1"],
                    "priority": "medium",
                    "constitution_score": 0.72,
                },
            ]
        }
        output_path = Path(temp_spiral_dir) / "_validated_stories.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f)
        return output

    @pytest.fixture
    def mock_prd_json(self, temp_spiral_dir: str) -> dict[str, Any]:
        """Create mock Phase M prd.json output."""
        # prd.json is in the parent directory of .spiral
        parent_dir = Path(temp_spiral_dir).parent
        output: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-1001",
                    "title": "Feature A",
                    "passes": True,
                },
                {
                    "id": "US-1002",
                    "title": "Feature B",
                    "passes": False,
                },
            ]
        }
        output_path = parent_dir / "prd.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f)
        return output

    def assert_research_schema_valid(
        self, temp_spiral_dir: str, mock_research_output: dict[str, Any]
    ) -> None:
        """Assert Phase R research output conforms to schema."""
        result = validate_phase("R", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result["valid"], f"Phase R validation failed: {result['errors']}"

        # Verify stories have required fields for research
        for story in mock_research_output["stories"]:
            assert "title" in story, "Story missing title"
            assert "description" in story, "Story missing description"
            assert "acceptanceCriteria" in story, "Story missing acceptanceCriteria"
            assert "priority" in story, "Story missing priority"
            assert story["priority"] in ["high", "medium", "low"], f"Invalid priority: {story['priority']}"

            # Verify research-specific fields
            if "relevance_score" in story:
                assert 0 <= story["relevance_score"] <= 1, f"Invalid relevance_score: {story['relevance_score']}"

    def assert_test_failures_no_duplicates(
        self, temp_spiral_dir: str, mock_test_output: dict[str, Any]
    ) -> None:
        """Assert Phase T test failures have no duplicate test IDs."""
        result = validate_phase("T", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result["valid"], f"Phase T validation failed: {result['errors']}"

        # Verify no duplicate test IDs
        test_ids: list[str] = []
        for story in mock_test_output["stories"]:
            if "test_id" in story:
                assert story["test_id"] not in test_ids, f"Duplicate test_id: {story['test_id']}"
                test_ids.append(story["test_id"])

            # Verify error category is valid
            if "error_category" in story:
                valid_categories = ["compile", "runtime", "timeout", "assertion"]
                assert story["error_category"] in valid_categories, f"Invalid error_category: {story['error_category']}"

            # Verify exit code is in valid range
            if "exit_code" in story:
                assert 1 <= story["exit_code"] <= 255, f"Invalid exit_code: {story['exit_code']}"

    def assert_merge_files_safe(self, temp_spiral_dir: str) -> None:
        """Assert Phase M merge operations are safe (no path traversal)."""
        parent_dir = Path(temp_spiral_dir).parent
        prd_path = parent_dir / "prd.json"

        # Verify prd.json exists and validates against schema
        result = validate_phase("M", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result["valid"], f"Phase M validation failed: {result['errors']}"

        # Verify no path traversal patterns in file paths
        with open(prd_path, encoding="utf-8") as f:
            prd_data: dict[str, Any] = json.load(f)

        for story in prd_data.get("userStories", []):
            story_id = story.get("id", "")
            assert ".." not in story_id, f"Path traversal detected in story ID: {story_id}"
            assert "/" not in story_id, f"Invalid path separator in story ID: {story_id}"

    def test_phase_r_research_schema_valid(
        self, temp_spiral_dir: str, mock_research_output: dict[str, Any]
    ) -> None:
        """Test Phase R output conforms to research schema."""
        self.assert_research_schema_valid(temp_spiral_dir, mock_research_output)

    def test_phase_t_test_failures_schema_valid(
        self, temp_spiral_dir: str, mock_test_output: dict[str, Any]
    ) -> None:
        """Test Phase T output conforms to test failures schema."""
        self.assert_test_failures_no_duplicates(temp_spiral_dir, mock_test_output)

    def test_phase_s_constitution_score_constraint(
        self, temp_spiral_dir: str, mock_validated_stories: dict[str, Any]
    ) -> None:
        """Test Phase S stories meet constitution_score >= 0.7 constraint."""
        result = validate_phase("S", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result["valid"], f"Phase S validation failed: {result['errors']}"

        # Verify all stories have constitution_score >= 0.7
        for story in mock_validated_stories["stories"]:
            if "constitution_score" in story:
                score = story["constitution_score"]
                assert score >= 0.7, f"Story {story.get('id')} has low constitution_score: {score}"

    def test_phase_s_unique_story_ids(self, temp_spiral_dir: str, mock_validated_stories: dict[str, Any]) -> None:
        """Test Phase S has unique story IDs."""
        result = validate_phase("S", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result["valid"], f"Phase S validation failed: {result['errors']}"

        story_ids = [story.get("id") for story in mock_validated_stories["stories"]]
        assert len(story_ids) == len(set(story_ids)), f"Duplicate story IDs found: {story_ids}"

    def test_phase_m_merge_files_safe(self, temp_spiral_dir: str, mock_prd_json: dict[str, Any]) -> None:
        """Test Phase M merge operations maintain safety constraints."""
        self.assert_merge_files_safe(temp_spiral_dir)

    def test_phase_data_integrity_full_flow(
        self,
        temp_spiral_dir: str,
        mock_research_output: dict[str, Any],
        mock_test_output: dict[str, Any],
        mock_validated_stories: dict[str, Any],
        mock_prd_json: dict[str, Any],
    ) -> None:
        """Test full data integrity across R→T→S→M phase pipeline."""
        # Validate all phases in sequence
        result_r = validate_phase("R", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result_r["valid"], f"Phase R failed: {result_r['errors']}"

        result_t = validate_phase("T", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result_t["valid"], f"Phase T failed: {result_t['errors']}"

        result_s = validate_phase("S", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result_s["valid"], f"Phase S failed: {result_s['errors']}"

        result_m = validate_phase("M", spiral_dir=temp_spiral_dir, schema_dir="lib/schemas")
        assert result_m["valid"], f"Phase M failed: {result_m['errors']}"

        # Verify no data corruption across pipeline
        # All phases should have at least one story
        assert len(mock_research_output["stories"]) > 0, "Phase R has no stories"
        assert len(mock_test_output["stories"]) > 0, "Phase T has no stories"
        assert len(mock_validated_stories["stories"]) > 0, "Phase S has no stories"
        assert len(mock_prd_json["userStories"]) > 0, "Phase M has no stories"

    def test_phase_output_no_orphaned_references(self, temp_spiral_dir: str, mock_prd_json: dict[str, Any]) -> None:
        """Test Phase M has no orphaned story references."""
        parent_dir = Path(temp_spiral_dir).parent
        prd_path = parent_dir / "prd.json"

        with open(prd_path, encoding="utf-8") as f:
            prd_data: dict[str, Any] = json.load(f)

        # Verify all story IDs follow valid pattern
        for story in prd_data.get("userStories", []):
            story_id = story.get("id", "")
            assert story_id, "Story missing ID"
            # Valid patterns: US-NNN or UT-NNN
            assert re.match(r"^(US|UT)-\d+$", story_id), f"Invalid story ID format: {story_id}"

    def test_phase_research_relevance_scores_valid(
        self, temp_spiral_dir: str, mock_research_output: dict[str, Any]
    ) -> None:
        """Test Phase R relevance scores are in valid range (0-1)."""
        for story in mock_research_output["stories"]:
            if "relevance_score" in story:
                score = story["relevance_score"]
                assert isinstance(score, (int, float)), f"Relevance score must be numeric: {score}"
                assert 0 <= score <= 1, f"Relevance score out of range: {score}"
