"""Tests for federated namespace validation."""

import sys
from pathlib import Path
from typing import Any

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from spiral.federated_namespace_validator import validate_federated_namespaces


class TestNamespaceValidation:
    """Test federated namespace validation."""

    def test_correct_namespaces_pass(self) -> None:
        """Test that correct namespace patterns pass validation."""
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "backend_US-001", "title": "Test 1", "dependencies": []},
                {"id": "frontend_US-002", "title": "Test 2", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is True
        assert result["passed_count"] == 2
        assert result["failed_count"] == 0
        assert len(result["errors"]) == 0

    def test_missing_repo_prefix_fails(self) -> None:
        """Test that stories without repo prefix fail validation."""
        prd = {
            "userStories": [
                {"id": "US-001", "title": "Test 1", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert result["failed_count"] == 1
        assert len(result["errors"]) == 1
        assert "Invalid namespace" in result["errors"][0]

    def test_unknown_repo_prefix_fails(self) -> None:
        """Test that stories with unknown repo prefix fail validation."""
        prd = {
            "userStories": [
                {"id": "unknown_US-001", "title": "Test 1", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert result["failed_count"] == 1
        assert len(result["errors"]) == 1

    def test_invalid_story_type_fails(self) -> None:
        """Test that invalid story types (not US or UT) fail validation."""
        prd = {
            "userStories": [
                {"id": "backend_XX-001", "title": "Test 1", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert result["failed_count"] == 1

    def test_cross_repo_dependency_fails(self) -> None:
        """Test that cross-repo dependencies are rejected."""
        prd = {
            "userStories": [
                {
                    "id": "backend_US-001",
                    "title": "Test 1",
                    "dependencies": ["frontend_US-002"],
                },
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert "Cross-repo dependency" in result["errors"][0]

    def test_three_repo_validation_multi_repo(self) -> None:
        """Test validation with 3 repos and multiple stories."""
        prd = {
            "userStories": [
                {"id": "backend_US-001", "title": "Backend story", "dependencies": []},
                {"id": "frontend_US-001", "title": "Frontend story", "dependencies": []},
                {
                    "id": "services_UT-001",
                    "title": "Service test",
                    "dependencies": [],
                },
            ]
        }
        repos = ["backend", "frontend", "services"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is True
        assert result["passed_count"] == 3
        assert result["failed_count"] == 0

    def test_three_repo_with_one_incorrect_namespace_fails(self) -> None:
        """Test 3-repo validation where one repo has incorrect namespace."""
        prd = {
            "userStories": [
                {"id": "backend_US-001", "title": "Backend story", "dependencies": []},
                {"id": "frontend_US-001", "title": "Frontend story", "dependencies": []},
                {"id": "invalid_UT-001", "title": "Invalid story", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend", "services"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert result["passed_count"] == 2
        assert result["failed_count"] == 1
        assert len(result["errors"]) == 1

    def test_empty_stories_list(self) -> None:
        """Test validation with empty stories list."""
        prd: dict[str, Any] = {"userStories": []}
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is True
        assert result["passed_count"] == 0
        assert result["failed_count"] == 0
        assert len(result["warnings"]) == 1

    def test_missing_id_field(self) -> None:
        """Test validation with missing id field."""
        prd: dict[str, Any] = {
            "userStories": [
                {"title": "No ID story", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        assert result["failed_count"] == 1
        assert "missing 'id' field" in result["errors"][0]

    def test_error_message_clarity(self) -> None:
        """Test that error messages are clear and actionable."""
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "backend_US-999", "title": "Test", "dependencies": []},
                {"id": "invalid", "title": "Test", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is False
        error_msgs = result["errors"]
        assert any("Expected format" in msg for msg in error_msgs)
        assert any("frontend" in msg for msg in error_msgs)

    def test_same_repo_dependency_allowed(self) -> None:
        """Test that same-repo dependencies are allowed."""
        prd: dict[str, Any] = {
            "userStories": [
                {
                    "id": "backend_US-001",
                    "title": "Test 1",
                    "dependencies": ["backend_US-002"],
                },
                {"id": "backend_US-002", "title": "Test 2", "dependencies": []},
            ]
        }
        repos = ["backend", "frontend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is True
        assert result["passed_count"] == 2
        assert result["failed_count"] == 0

    def test_ut_story_type_validation(self) -> None:
        """Test that UT (test) story type is accepted."""
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "backend_UT-001", "title": "Test", "dependencies": []},
            ]
        }
        repos = ["backend"]
        result = validate_federated_namespaces(prd, repos)

        assert result["valid"] is True
        assert result["passed_count"] == 1
        assert result["failed_count"] == 0
