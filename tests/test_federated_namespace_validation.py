"""Tests for federated namespace prefix validation (US-1255).

Tests validate that story IDs in repos/PROJECT-X/ folders match
the expected prefix (e.g., repos/makan/ → MAKAN-*).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lib.federated.namespace_validator import (
    get_story_line_number,
    infer_prefix_from_folder,
    validate_namespace_prefix,
    validate_story_id_prefix,
)


class TestValidateStoryIdPrefix:
    """Test individual story ID prefix validation."""

    def test_valid_prefix_match(self) -> None:
        """Test that matching prefix is accepted."""
        assert validate_story_id_prefix("MAKAN-100", "MAKAN") is True

    def test_invalid_prefix_mismatch(self) -> None:
        """Test that mismatched prefix is rejected."""
        assert validate_story_id_prefix("US-100", "MAKAN") is False

    def test_case_sensitive_prefix(self) -> None:
        """Test that prefix matching is case-sensitive."""
        assert validate_story_id_prefix("makan-100", "MAKAN") is False
        assert validate_story_id_prefix("MAKAN-100", "makan") is False

    def test_prefix_with_dash(self) -> None:
        """Test prefix matching with required dash separator."""
        assert validate_story_id_prefix("MAKAN-001", "MAKAN") is True
        assert validate_story_id_prefix("MAKANOS", "MAKAN") is False


class TestInferPrefixFromFolder:
    """Test folder name to prefix conversion."""

    def test_simple_folder_name(self) -> None:
        """Test simple folder name conversion to uppercase."""
        result = infer_prefix_from_folder(Path("repos/makan"))
        assert result == "MAKAN"

    def test_uppercase_folder_name(self) -> None:
        """Test that uppercase folder names are preserved."""
        result = infer_prefix_from_folder(Path("repos/BACKEND"))
        assert result == "BACKEND"

    def test_hyphenated_folder_name(self) -> None:
        """Test folder names with hyphens."""
        result = infer_prefix_from_folder(Path("repos/my-service"))
        assert result == "MY-SERVICE"


class TestGetStoryLineNumber:
    """Test finding story ID line numbers in prd.json."""

    def test_find_story_line_number(self) -> None:
        """Test that story line number is correctly detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_content = {
                "userStories": [
                    {"id": "MAKAN-100", "title": "Story 1"},
                    {"id": "MAKAN-101", "title": "Story 2"},
                ]
            }
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(prd_content, f)

            line_num = get_story_line_number(prd_path, "MAKAN-100")
            assert line_num > 0, "Should find story line number"

    def test_story_not_found_returns_negative_one(self) -> None:
        """Test that missing story returns -1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_path = Path(tmpdir) / "prd.json"
            prd_content = {"userStories": [{"id": "MAKAN-100", "title": "Story 1"}]}
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(prd_content, f)

            line_num = get_story_line_number(prd_path, "NONEXISTENT-999")
            assert line_num == -1


class TestValidateNamespacePrefix:
    """Integration tests for namespace prefix validation."""

    def test_valid_namespace_single_repo(self) -> None:
        """Test validation passes when story IDs match folder prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repos_path = Path(tmpdir) / "repos"
            repos_path.mkdir()

            makan_dir = repos_path / "makan"
            makan_dir.mkdir()
            prd_path = makan_dir / "prd.json"
            prd_content = {
                "userStories": [
                    {"id": "MAKAN-100", "title": "Story 1"},
                    {"id": "MAKAN-101", "title": "Story 2"},
                ]
            }
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(prd_content, f)

            result = validate_namespace_prefix(repos_path)
            assert result["valid"] is True
            assert result["failed_count"] == 0
            assert result["passed_count"] == 2

    def test_invalid_namespace_mismatch(self) -> None:
        """Test validation fails when story IDs don't match folder prefix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repos_path = Path(tmpdir) / "repos"
            repos_path.mkdir()

            makan_dir = repos_path / "makan"
            makan_dir.mkdir()
            prd_path = makan_dir / "prd.json"
            prd_content = {
                "userStories": [
                    {"id": "US-100", "title": "Story 1"},
                    {"id": "MAKAN-101", "title": "Story 2"},
                ]
            }
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(prd_content, f)

            result = validate_namespace_prefix(repos_path)
            assert result["valid"] is False
            assert result["failed_count"] == 1
            assert result["passed_count"] == 1
            assert len(result["errors"]) == 1
            assert result["errors"][0]["story_id"] == "US-100"
            assert result["errors"][0]["expected"] == "MAKAN-*"

    def test_multiple_subprojects(self) -> None:
        """Test validation across multiple sub-projects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repos_path = Path(tmpdir) / "repos"
            repos_path.mkdir()

            makan_dir = repos_path / "makan"
            makan_dir.mkdir()
            with open(makan_dir / "prd.json", "w", encoding="utf-8") as f:
                json.dump(
                    {"userStories": [{"id": "MAKAN-100", "title": "Story 1"}]},
                    f,
                )

            backend_dir = repos_path / "backend"
            backend_dir.mkdir()
            with open(backend_dir / "prd.json", "w", encoding="utf-8") as f:
                json.dump(
                    {"userStories": [{"id": "BACKEND-200", "title": "Story 2"}]},
                    f,
                )

            result = validate_namespace_prefix(repos_path)
            assert result["valid"] is True
            assert result["total_stories"] == 2
            assert result["passed_count"] == 2

    def test_story_id_mismatch_detection(self) -> None:
        """Test the specific mismatch detection referenced in acceptance criteria."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repos_path = Path(tmpdir) / "repos"
            repos_path.mkdir()

            makan_dir = repos_path / "makan"
            makan_dir.mkdir()
            prd_path = makan_dir / "prd.json"
            prd_content = {"userStories": [{"id": "US-100", "title": "Cafe feature"}]}
            with open(prd_path, "w", encoding="utf-8") as f:
                json.dump(prd_content, f)

            result = validate_namespace_prefix(repos_path)

            assert result["valid"] is False
            error = result["errors"][0]
            assert str(prd_path) in error["file"]
            assert error["story_id"] == "US-100"
            assert error["expected"] == "MAKAN-*"
            assert error["got"] == "US-100"
