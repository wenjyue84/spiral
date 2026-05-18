"""Integration tests for federated PRD merge with namespace isolation and collision detection.

Tests validate that:
1. Federated PRD merge correctly applies namespace prefixes to sub-project stories
2. Story ID collisions are detected and handled appropriately
3. All story fields (title, acceptanceCriteria, filesTouch, _source, _decomposed) are preserved
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

# Setup path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))

from lib.prd.merge_stories import load_with_includes


@pytest.mark.federation_integration
def test_namespace_isolation_main_and_subproject() -> None:
    """Test that same story IDs from main and sub-project are isolated by namespace.

    Acceptance Criteria:
    - Main project story US-001 exists without namespace prefix
    - Sub-project story US-001 exists with namespace prefix (sub_project:US-001)
    - Both stories coexist in merged output without collision
    """
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "main_prd.json")
    assert os.path.isfile(fixture_path), f"Fixture not found: {fixture_path}"

    # Load the main PRD which includes the sub-project
    result = load_with_includes(fixture_path)
    stories = result.get("userStories", [])

    # Should have 6 stories total: 3 from main + 3 from sub-project (with namespace prefix)
    assert len(stories) == 6, f"Expected 6 stories, got {len(stories)}"

    # Extract story IDs
    story_ids = {s["id"] for s in stories}

    # Verify main project stories (no prefix)
    assert "US-001" in story_ids, "Main project US-001 should exist without namespace"
    assert "US-002" in story_ids, "Main project US-002 should exist without namespace"
    assert "US-003" in story_ids, "Main project US-003 should exist without namespace"

    # Verify sub-project stories (with namespace prefix)
    # The fixture file is named sub_project_prd.json, so namespace should be "sub_project"
    assert "sub_project:US-001" in story_ids, "Sub-project US-001 should have sub_project: prefix"
    assert "sub_project:US-002" in story_ids, "Sub-project US-002 should have sub_project: prefix"
    assert "sub_project:US-003" in story_ids, "Sub-project US-003 should have sub_project: prefix"

    # Verify no collision: stories are distinct by ID
    assert len(story_ids) == 6, f"Story IDs should be unique (no collisions), got: {story_ids}"


@pytest.mark.federation_integration
def test_collision_detection_same_namespace() -> None:
    """Test that duplicate story IDs within the same namespace are detected.

    Creates two sub-projects with identical story IDs and verifies that
    the merge properly namespaces them to avoid collisions.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create main PRD with two includes
        main_prd_path = os.path.join(tmpdir, "main.json")
        sub1_prd_path = os.path.join(tmpdir, "sub_project_a_prd.json")
        sub2_prd_path = os.path.join(tmpdir, "sub_project_b_prd.json")

        # Sub-project A with stories
        sub_a = {
            "schemaVersion": 1,
            "productName": "SubA",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Feature A",
                    "priority": "high",
                    "acceptanceCriteria": ["A criterion"],
                    "dependencies": [],
                    "passes": False,
                }
            ],
        }

        # Sub-project B with same story ID
        sub_b = {
            "schemaVersion": 1,
            "productName": "SubB",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Feature B",
                    "priority": "high",
                    "acceptanceCriteria": ["B criterion"],
                    "dependencies": [],
                    "passes": False,
                }
            ],
        }

        # Main PRD includes both sub-projects
        main = {
            "schemaVersion": 1,
            "productName": "Main",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Main",
                    "priority": "high",
                    "acceptanceCriteria": [],
                    "dependencies": [],
                    "passes": False,
                }
            ],
            "prd": {"include": ["sub_project_a_prd.json", "sub_project_b_prd.json"]},
        }

        # Write files
        with open(sub1_prd_path, "w", encoding="utf-8") as f:
            json.dump(sub_a, f)
        with open(sub2_prd_path, "w", encoding="utf-8") as f:
            json.dump(sub_b, f)
        with open(main_prd_path, "w", encoding="utf-8") as f:
            json.dump(main, f)

        # Load merged PRD
        result = load_with_includes(main_prd_path)
        stories = result.get("userStories", [])

        # Should have 3 stories: main (US-1) + sub_project_a (sub_project_a:US-100) + sub_project_b (sub_project_b:US-100)
        assert len(stories) == 3, f"Expected 3 stories, got {len(stories)}"

        story_ids = {s["id"] for s in stories}
        assert "US-1" in story_ids, "Main story should be present"
        assert "sub_project_a:US-100" in story_ids, "Sub-project A story should have namespace"
        assert "sub_project_b:US-100" in story_ids, "Sub-project B story should have namespace"


@pytest.mark.federation_integration
def test_story_field_preservation_on_merge() -> None:
    """Test that all story fields are preserved during federated merge.

    Acceptance Criteria:
    - Title preserved
    - acceptanceCriteria array preserved
    - filesTouch array preserved
    - _source field preserved
    - _decomposed field preserved (if present)
    - dependencies preserved
    - priority preserved
    - estimatedComplexity preserved
    """
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "main_prd.json")

    result = load_with_includes(fixture_path)
    stories = result.get("userStories", [])

    # Find the sub-project US-001 story
    sub_story = next((s for s in stories if s["id"] == "sub_project:US-001"), None)
    assert sub_story is not None, "Sub-project story US-001 not found"

    # Verify all key fields are preserved
    assert sub_story["title"] == "Sub-project feature (same ID as main)", "Title not preserved"
    assert isinstance(sub_story["acceptanceCriteria"], list), "acceptanceCriteria not preserved as list"
    assert len(sub_story["acceptanceCriteria"]) == 2, "acceptanceCriteria count mismatch"
    assert "Sub story criterion 1" in sub_story["acceptanceCriteria"], "acceptanceCriteria content not preserved"

    assert isinstance(sub_story["filesTouch"], list), "filesTouch not preserved as list"
    assert len(sub_story["filesTouch"]) == 2, "filesTouch count mismatch"
    assert "sub/module1.py" in sub_story["filesTouch"], "filesTouch content not preserved"

    assert sub_story["_source"] == "ai-example", "_source field not preserved"
    assert sub_story["priority"] == "high", "priority not preserved"
    assert sub_story["estimatedComplexity"] == "medium", "estimatedComplexity not preserved"

    # Verify _decomposed field is preserved (if present)
    sub_story_002 = next((s for s in stories if s["id"] == "sub_project:US-002"), None)
    assert sub_story_002 is not None, "Sub-project story US-002 not found"
    assert sub_story_002.get("_decomposed") is False, "_decomposed field not preserved"

    # Verify dependencies are preserved
    assert isinstance(sub_story_002.get("dependencies", []), list), "dependencies not preserved as list"


@pytest.mark.federation_integration
def test_federation_merge_with_complex_includes() -> None:
    """Test federated PRD merge with multiple levels of includes and field preservation.

    Creates a more complex scenario with multiple sub-projects and verifies
    all stories are correctly namespaced and their fields preserved.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a three-level hierarchy: main -> sub_a -> sub_b
        main_path = os.path.join(tmpdir, "main.json")
        sub_a_path = os.path.join(tmpdir, "sub_project_a_prd.json")
        sub_b_path = os.path.join(tmpdir, "sub_project_b_prd.json")

        sub_b = {
            "schemaVersion": 1,
            "productName": "SubB",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-200",
                    "title": "Deep nested story",
                    "priority": "high",
                    "description": "Story from deepest level",
                    "acceptanceCriteria": ["Criterion A", "Criterion B"],
                    "technicalNotes": ["Note 1", "Note 2"],
                    "filesTouch": ["deep/file.py"],
                    "dependencies": [],
                    "estimatedComplexity": "small",
                    "passes": False,
                    "_source": "research",
                }
            ],
        }

        sub_a = {
            "schemaVersion": 1,
            "productName": "SubA",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Mid-level story",
                    "priority": "medium",
                    "description": "Story from middle level",
                    "acceptanceCriteria": ["Mid criterion"],
                    "technicalNotes": [],
                    "filesTouch": ["mid/file.py", "mid/file2.py"],
                    "dependencies": [],
                    "estimatedComplexity": "medium",
                    "passes": False,
                    "_source": "test-fix",
                }
            ],
            "prd": {"include": ["sub_project_b_prd.json"]},
        }

        main = {
            "schemaVersion": 1,
            "productName": "Main",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Top-level story",
                    "priority": "high",
                    "description": "Main project story",
                    "acceptanceCriteria": ["Main criterion"],
                    "technicalNotes": ["Implementation"],
                    "filesTouch": ["main/core.py"],
                    "dependencies": [],
                    "estimatedComplexity": "large",
                    "passes": False,
                    "_source": "seed",
                }
            ],
            "prd": {"include": ["sub_project_a_prd.json"]},
        }

        # Write files
        with open(sub_b_path, "w", encoding="utf-8") as f:
            json.dump(sub_b, f)
        with open(sub_a_path, "w", encoding="utf-8") as f:
            json.dump(sub_a, f)
        with open(main_path, "w", encoding="utf-8") as f:
            json.dump(main, f)

        # Load the main PRD
        result = load_with_includes(main_path)
        stories = result.get("userStories", [])

        # Should have all stories with proper namespacing
        assert len(stories) == 3, f"Expected 3 stories, got {len(stories)}"

        story_ids = {s["id"] for s in stories}
        assert "US-1" in story_ids, "Main story missing"
        assert "sub_project_a:US-100" in story_ids, "Sub-A story missing or not namespaced"
        assert "sub_project_b:US-200" in story_ids, "Sub-B story missing or not namespaced (should have both prefixes)"

        # Verify deep story has proper namespacing
        deep_story = next((s for s in stories if s["id"] == "sub_project_b:US-200"), None)
        assert deep_story is not None, "Deep nested story not found with correct namespace"
        assert deep_story["title"] == "Deep nested story", "Deep story title not preserved"
        assert len(deep_story["acceptanceCriteria"]) == 2, "Deep story acceptanceCriteria not preserved"
        assert deep_story["_source"] == "research", "Deep story _source not preserved"
