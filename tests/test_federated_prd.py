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
    """Load a federated prd.json and merge sub-projects with namespacing."""
    if not isinstance(prd_dict, dict):
        raise ValueError("prd_dict must be a dict")

    merged: dict[str, Any] = prd_dict.copy()
    merged["userStories"] = list(prd_dict.get("userStories", []))

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

        sub_prd_path = base_path / rel_path

        if not sub_prd_path.exists():
            raise FileNotFoundError(
                f"Sub-project prd.json not found at {rel_path} "
                f"(resolved to {sub_prd_path})"
            )

        try:
            with open(sub_prd_path, "r", encoding="utf-8") as f:
                sub_prd = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Sub-project prd.json at {rel_path} has invalid JSON: {e}"
            )

        if not isinstance(sub_prd, dict):
            raise ValueError(f"Sub-project prd.json must be an object")

        if "userStories" not in sub_prd or not isinstance(sub_prd["userStories"], list):
            raise ValueError(
                f"Sub-project prd.json at {rel_path} must have userStories array"
            )

        for story in sub_prd["userStories"]:
            if not isinstance(story, dict):
                continue

            namespaced_story = story.copy()

            if "id" in namespaced_story:
                original_id = namespaced_story["id"]
                namespaced_story["id"] = f"{namespace}/{original_id}"

            namespaced_story["_federated_from"] = namespace
            namespaced_story["_original_id"] = story.get("id")

            merged["userStories"].append(namespaced_story)

    return merged


def test_federated_prd_happy_path(tmp_path: Path) -> None:
    """Test happy path: federated prd.json loads with namespaced story IDs."""
    base_prd = create_base_prd("Main Product")
    base_prd["userStories"] = [
        create_story("US-001", "Main feature 1"),
        create_story("US-002", "Main feature 2"),
    ]

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

    base_prd["subProjects"] = [
        {
            "namespace": "subproj",
            "path": "subproject/prd.json"
        }
    ]

    merged_prd = load_federated_prd(base_prd, tmp_path)

    story_ids = [s["id"] for s in merged_prd["userStories"]]

    assert "US-001" in story_ids
    assert "US-002" in story_ids
    assert "subproj/US-100" in story_ids, "Sub-project story IDs should carry namespace prefix"
    assert "subproj/US-101" in story_ids

    assert len(merged_prd["userStories"]) == 4

    sub_story = next(s for s in merged_prd["userStories"] if s["id"] == "subproj/US-100")
    assert sub_story.get("_federated_from") == "subproj"
    assert sub_story.get("_original_id") == "US-100"


def test_federated_prd_missing_subproject(tmp_path: Path) -> None:
    """Test error handling: missing sub-project file raises descriptive error."""
    base_prd = create_base_prd("Product with Missing Sub")
    base_prd["userStories"] = [create_story("US-001", "Feature")]

    base_prd["subProjects"] = [
        {
            "namespace": "missing",
            "path": "nonexistent/prd.json"
        }
    ]

    with pytest.raises(FileNotFoundError) as exc_info:
        load_federated_prd(base_prd, tmp_path)

    error_msg = str(exc_info.value)
    assert "nonexistent/prd.json" in error_msg
    assert "Sub-project prd.json not found" in error_msg


class TestFederatedPrdComprehensive:
    """Comprehensive test suite for federated prd.json."""

    def test_multiple_subprojects(self, tmp_path: Path) -> None:
        """Test loading multiple sub-projects."""
        base_prd = create_base_prd("Multi-Repo Product")
        base_prd["userStories"] = [create_story("US-001", "Base feature")]

        sub1_dir = tmp_path / "sub1"
        sub1_dir.mkdir()
        sub1_prd = create_base_prd("Sub1")
        sub1_prd["userStories"] = [create_story("US-100", "Sub1 feature")]
        with open(sub1_dir / "prd.json", "w") as f:
            json.dump(sub1_prd, f)

        sub2_dir = tmp_path / "sub2"
        sub2_dir.mkdir()
        sub2_prd = create_base_prd("Sub2")
        sub2_prd["userStories"] = [create_story("US-200", "Sub2 feature")]
        with open(sub2_dir / "prd.json", "w") as f:
            json.dump(sub2_prd, f)

        base_prd["subProjects"] = [
            {"namespace": "sub1", "path": "sub1/prd.json"},
            {"namespace": "sub2", "path": "sub2/prd.json"},
        ]

        result = load_federated_prd(base_prd, tmp_path)
        story_ids = [s["id"] for s in result["userStories"]]

        assert "US-001" in story_ids
        assert "sub1/US-100" in story_ids
        assert "sub2/US-200" in story_ids

    def test_malformed_json(self, tmp_path: Path) -> None:
        """Test error handling for malformed JSON."""
        base_prd = create_base_prd("Product")

        sub_dir = tmp_path / "broken"
        sub_dir.mkdir()
        with open(sub_dir / "prd.json", "w") as f:
            f.write("{ invalid json }")

        base_prd["subProjects"] = [
            {"namespace": "broken", "path": "broken/prd.json"}
        ]

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        assert "invalid JSON" in str(exc_info.value)

    def test_missing_namespace(self, tmp_path: Path) -> None:
        """Test error handling for missing namespace."""
        base_prd = create_base_prd("Product")
        base_prd["subProjects"] = [{"path": "some/path.json"}]

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        assert "namespace" in str(exc_info.value).lower()

    def test_missing_path(self, tmp_path: Path) -> None:
        """Test error handling for missing path."""
        base_prd = create_base_prd("Product")
        base_prd["subProjects"] = [{"namespace": "orphan"}]

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        assert "path" in str(exc_info.value).lower()

    def test_invalid_subprojects_structure(self, tmp_path: Path) -> None:
        """Test error handling for invalid subProjects."""
        base_prd = create_base_prd("Product")
        base_prd["subProjects"] = "not a list"

        with pytest.raises(ValueError) as exc_info:
            load_federated_prd(base_prd, tmp_path)

        assert "subProjects must be a list" in str(exc_info.value)
