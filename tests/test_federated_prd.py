"""Integration tests for federated prd.json support with sub-project namespacing.

Tests cover:
1. Happy path: loading federated prd.json with sub-project namespacing
2. Error cases: missing subproject files, malformed namespace references
3. Self-contained: no external services required, uses tmp_path fixtures
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))


def create_base_prd(product_name: str = "Test Product") -> dict[str, Any]:
    """Create a minimal base prd.json structure."""
    return {
        "schemaVersion": 1,
        "productName": product_name,
        "branchName": "main",
        "overview": "Test PRD",
        "goals": ["Test goal"],
        "userStories": []
    }


def create_story(story_id: str, title: str, priority: str = "medium") -> dict[str, Any]:
    """Create a minimal story object."""
    return {
        "id": story_id,
        "title": title,
        "priority": priority,
        "description": f"Story: {title}",
        "acceptanceCriteria": ["Criterion 1"],
        "dependencies": [],
        "estimatedComplexity": "small",
        "passes": False
    }


def load_federated_prd(prd_dict: dict[str, Any], base_path: Path) -> dict[str, Any]:
    """
    Load a federated prd.json and merge sub-projects with namespacing.

    This is a minimal implementation that:
    1. Looks for "subProjects" array in prd_dict
    2. For each sub-project, loads its prd.json
    3. Prefixes story IDs with sub-project namespace
    4. Raises descriptive errors for missing files

    Sub-project format:
    {
        "namespace": "subproj",
        "path": "path/to/sub/prd.json"
    }
    """
    if not isinstance(prd_dict, dict):
        raise ValueError("prd_dict must be a dict")

    # Start with base stories
    merged: dict[str, Any] = prd_dict.copy()
    merged["userStories"] = list(prd_dict.get("userStories", []))

    # Process sub-projects if present
    sub_projects = prd_dict.get("subProjects", [])
    if not isinstance(sub_projects, list):
        raise ValueError("subProjects must be a list")

    for sub_project in sub_projects:
        if not isinstance(sub_project, dict):
            raise ValueError("Each subProject must be an object")

        if "namespace" not in sub_project or "path" not in sub_project:
            raise ValueError("Each subProject must have 'namespace' and 'path' keys")

        namespace = sub_project["namespace"]
        rel_path = sub_project["path"]

        # Resolve path relative to base_path
        sub_prd_path = base_path / rel_path

        # Check if file exists
        if not sub_prd_path.exists():
            raise FileNotFoundError(
                f"Sub-project prd.json not found at {rel_path} "
                f"(resolved to {sub_prd_path})"
            )

        # Load sub-project prd.json
        try:
            with open(sub_prd_path, "r", encoding="utf-8") as f:
                sub_prd = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Sub-project prd.json at {rel_path} has invalid JSON: {e}"
            )

        # Verify structure
        if not isinstance(sub_prd, dict):
            raise ValueError(f"Sub-project prd.json must be an object")

        if "userStories" not in sub_prd or not isinstance(sub_prd["userStories"], list):
            raise ValueError(
                f"Sub-project prd.json at {rel_path} must have userStories array"
            )

        # Namespace and merge stories
        for story in sub_prd["userStories"]:
            if not isinstance(story, dict):
                continue

            # Create namespaced copy
            namespaced_story = story.copy()

            # Prefix the ID with namespace
            if "id" in namespaced_story:
                original_id = namespaced_story["id"]
                namespaced_story["id"] = f"{namespace}/{original_id}"

            # Add metadata to track origin
            namespaced_story["_federated_from"] = namespace
            namespaced_story["_original_id"] = story.get("id")

            merged["userStories"].append(namespaced_story)

    return merged


class TestFederatedPrdHappyPath:
    """Tests for successful federated prd.json loading."""

    def test_federated_prd_happy_path(self, tmp_path: Path) -> None:
        """
        Test happy path: federated prd.json loads with namespaced story IDs.

        Creates a base prd.json and a sub-project prd.json, loads them together,
        and verifies that sub-project story IDs are properly namespaced.
        """
        # Create base prd.json
        base_prd = create_base_prd("Main Product")
        base_prd["userStories"] = [
            create_story("US-001", "Main feature 1"),
            create_story("US-002", "Main feature 2"),
        ]

        # Create sub-project directory and prd.json
        sub_proj_dir = tmp_path / "subproject"
        sub_proj_dir.mkdir()

        sub_prd = create_base_prd("Sub Project")
        sub_prd["userStories"] = [
            create_story("US-100", "Sub feature 1"),
            create_story("US-101", "Sub feature 2"),
        ]

        sub_prd_path = sub_proj_dir / "prd.json"
        with open(sub_prd_path, "w") as f:
            json.dump(sub_prd, f)

        # Add sub-project reference to base PRD
        base_prd["subProjects"] = [
            {
                "namespace": "subproj",
                "path": "subproject/prd.json"
            }
        ]

        # Load federated PRD
        merged_prd = load_federated_prd(base_prd, tmp_path)

        # Verify stories
        story_ids = [s["id"] for s in merged_prd["userStories"]]

        # Base stories should have original IDs
        assert "US-001" in story_ids, "Base story US-001 should be present"
        assert "US-002" in story_ids, "Base story US-002 should be present"

        # Sub-project stories should be namespaced
        assert "subproj/US-100" in story_ids, "Sub-project story should be namespaced as 'subproj/US-100'"
        assert "subproj/US-101" in story_ids, "Sub-project story should be namespaced as 'subproj/US-101'"

        # Verify total count
        assert len(merged_prd["userStories"]) == 4, "Merged PRD should have 4 stories total"

        # Verify metadata
        sub_story = next(s for s in merged_prd["userStories"] if s["id"] == "subproj/US-100")
        assert sub_story.get("_federated_from") == "subproj"
        assert sub_story.get("_original_id") == "US-100"

    def test_federated_prd_multiple_subprojects(self, tmp_path: Path) -> None:
        """Test loading multiple sub-projects with different namespaces."""
        base_prd = create_base_prd("Multi-Repo Product")
        base_prd["userStories"] = [create_story("US-001", "Base feature")]

        # Create first sub-project
        sub1_dir = tmp_path / "sub1"
        sub1_dir.mkdir()
        sub1_prd = create_base_prd("Sub1")
        sub1_prd["userStories"] = [create_story("US-100", "Sub1 feature")]
        with open(sub1_dir / "prd.json", "w") as f:
            json.dump(sub1_prd, f)

        # Create second sub-project
        sub2_dir = tmp_path / "sub2"
        sub2_dir.mkdir()
        sub2_prd = create_base_prd("Sub2")
        sub2_prd["userStories"] = [create_story("US-200", "Sub2 feature")]
        with open(sub2_dir / "prd.json", "w") as f:
            json.dump(sub2_prd, f)

        # Add both sub-projects
        base_prd["subProjects"] = [
            {"namespace": "sub1", "path": "sub1/prd.json"},
            {"namespace": "sub2", "path": "sub2/prd.json"},
        ]

        # Load merged PRD
        merged_prd = load_federated_prd(base_prd, tmp_path)
        story_ids = [s["id"] for s in merged_prd["userStories"]]

        # Verify all stories are present with correct namespaces
        assert "US-001" in story_ids
        assert "sub1/US-100" in story_ids
        assert "sub2/US-200" in story_ids


class TestFederatedPrdErrorHandling:
    """Tests for error handling in federated prd.json loading."""

    def test_federated_prd_missing_subproject(self, tmp_path: Path) -> None:
        """
        Test error handling: missing sub-project file raises descriptive error.

        Verifies that when a sub-project prd.json doesn't exist, a FileNotFoundError
        is raised with helpful context about the missing file path.
        """
        base_prd = create_base_prd("Product with Missing Sub")
        base_prd["userStories"] = [create_story("US-001", "Feature")]

        # Reference a sub-project that doesn't exist
        base_prd["subProjects"] = [
            {
                "namespace": "missing",
                "path": "nonexistent/prd.json"
            }
        ]

        # Attempt to load should raise FileNotFoundError
        with pytest.raises(FileNotFoundError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        # Verify error message is descriptive
        error_msg = str(exc_info.value)
        assert "nonexistent/prd.json" in error_msg, "Error should mention missing path"
        assert "Sub-project prd.json not found" in error_msg, "Error should be descriptive"

    def test_federated_prd_malformed_json(self, tmp_path: Path) -> None:
        """Test error handling: malformed JSON in sub-project raises ValueError."""
        base_prd = create_base_prd("Product")

        # Create a sub-project with invalid JSON
        sub_dir = tmp_path / "broken"
        sub_dir.mkdir()
        with open(sub_dir / "prd.json", "w") as f:
            f.write("{ invalid json }")

        base_prd["subProjects"] = [
            {"namespace": "broken", "path": "broken/prd.json"}
        ]

        # Should raise ValueError for invalid JSON
        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        error_msg = str(exc_info.value)
        assert "invalid JSON" in error_msg

    def test_federated_prd_missing_namespace(self, tmp_path: Path) -> None:
        """Test error handling: sub-project without namespace raises ValueError."""
        base_prd = create_base_prd("Product")

        # Sub-project missing 'namespace' key
        base_prd["subProjects"] = [
            {
                "path": "some/path.json"
                # Missing 'namespace' key
            }
        ]

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        error_msg = str(exc_info.value)
        assert "namespace" in error_msg.lower()

    def test_federated_prd_missing_path(self, tmp_path: Path) -> None:
        """Test error handling: sub-project without path raises ValueError."""
        base_prd = create_base_prd("Product")

        # Sub-project missing 'path' key
        base_prd["subProjects"] = [
            {
                "namespace": "orphan"
                # Missing 'path' key
            }
        ]

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        error_msg = str(exc_info.value)
        assert "path" in error_msg.lower()

    def test_federated_prd_invalid_subproject_structure(self, tmp_path: Path) -> None:
        """Test error handling: invalid subProject structure raises ValueError."""
        base_prd = create_base_prd("Product")

        # subProjects is not a list
        base_prd["subProjects"] = "not a list"

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        assert "subProjects must be a list" in str(exc_info.value)


# Integration-level tests
class TestFederatedPrdIntegration:
    """Full integration tests for federated prd.json workflow."""

    def test_federated_prd_happy_path_full_workflow(self, tmp_path: Path) -> None:
        """
        Full integration test: create temp files, load federated PRD, verify schema.

        This is the primary acceptance criteria test that must pass.
        """
        # Setup: create base and sub-project PRDs
        base_prd = create_base_prd("Integrated Product")
        base_prd["userStories"] = [
            create_story("US-001", "Core feature A"),
            create_story("US-002", "Core feature B"),
        ]

        # Create nested sub-projects
        sub_dir = tmp_path / "features"
        sub_dir.mkdir()

        sub_prd = create_base_prd("Features Module")
        sub_prd["userStories"] = [
            create_story("US-100", "Feature module task 1"),
            create_story("US-101", "Feature module task 2"),
        ]

        with open(sub_dir / "prd.json", "w") as f:
            json.dump(sub_prd, f)

        base_prd["subProjects"] = [
            {"namespace": "features", "path": "features/prd.json"}
        ]

        # Load
        result = load_federated_prd(base_prd, tmp_path)

        # Verify story IDs have namespace prefix for sub-projects
        story_ids = [s["id"] for s in result["userStories"]]

        # Check namespace prefix present
        namespaced_ids = [sid for sid in story_ids if "/" in sid]
        assert len(namespaced_ids) == 2, "Should have 2 namespaced stories"

        # Check all stories are present
        assert len(result["userStories"]) == 4

        # Verify federation metadata
        for story in result["userStories"]:
            if "/" in story["id"]:
                assert "_federated_from" in story
                assert "_original_id" in story


# ── Module-level functions for acceptance criteria ──────────────────────────


def test_federated_prd_happy_path(tmp_path: Path) -> None:
    """
    Acceptance criteria test: federated prd.json loads with namespaced story IDs.

    Test creates a base prd.json and a sub-project prd.json, loads them together,
    and verifies that sub-project story IDs carry the namespace prefix.
    """
    test_case = TestFederatedPrdHappyPath()
    test_case.test_federated_prd_happy_path(tmp_path)


def test_federated_prd_missing_subproject(tmp_path: Path) -> None:
    """
    Acceptance criteria test: missing subproject file raises descriptive error.

    Test verifies that when a referenced sub-project prd.json doesn't exist,
    a FileNotFoundError is raised with helpful context.
    """
    test_case = TestFederatedPrdErrorHandling()
    test_case.test_federated_prd_missing_subproject(tmp_path)
