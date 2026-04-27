"""Tests for prd.include schema field and load_with_includes() function."""

import json
import os
import sys
import tempfile

import pytest

# Setup path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))

from lib.prd.merge_stories import MergeError, load_with_includes
from lib.prd_schema import validate_prd

pytestmark = pytest.mark.include_schema


@pytest.mark.include_schema
def test_schema_accepts_prd_include_field():
    """Test that prd.schema.json accepts the prd.include field."""
    prd = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [],
        "prd": {"include": ["subproject_a.json", "subproject_b.json"]},
    }
    errors = validate_prd(prd)
    assert len(errors) == 0, f"Schema validation failed: {errors}"


@pytest.mark.include_schema
def test_schema_validates_prd_object():
    """Test that prd object is optional and doesn't break validation."""
    prd_no_prd = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [],
    }
    errors = validate_prd(prd_no_prd)
    assert len(errors) == 0, f"Schema validation failed for PRD without prd object: {errors}"


def test_load_with_includes_simple_subproject():
    """Test loading a simple PRD with included subproject."""
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "subproject_web_prd.json")

    # Load the fixture PRD without includes
    result = load_with_includes(fixture_path)

    # Should have the 2 stories from the fixture
    stories = result.get("userStories", [])
    assert len(stories) == 2

    # Check story IDs are prefixed with namespace
    story_ids = {s["id"] for s in stories}
    assert "web:US-100" in story_ids
    assert "web:US-101" in story_ids


@pytest.mark.include_schema
def test_load_with_includes_circular_detection():
    """Test that circular includes raise MergeError with 'circular' in message."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create PRD A that includes B
        prd_a_path = os.path.join(tmpdir, "prd_a.json")
        prd_b_path = os.path.join(tmpdir, "prd_b.json")

        prd_a = {
            "productName": "ProjectA",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Feature A",
                    "priority": "high",
                    "acceptanceCriteria": [],
                    "passes": False,
                    "dependencies": [],
                }
            ],
            "prd": {"include": ["prd_b.json"]},
        }

        prd_b = {
            "productName": "ProjectB",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Feature B",
                    "priority": "high",
                    "acceptanceCriteria": [],
                    "passes": False,
                    "dependencies": [],
                }
            ],
            "prd": {"include": ["prd_a.json"]},  # Circular: includes A
        }

        with open(prd_a_path, "w", encoding="utf-8") as f:
            json.dump(prd_a, f)
        with open(prd_b_path, "w", encoding="utf-8") as f:
            json.dump(prd_b, f)

        # Should raise MergeError with 'circular' in message
        with pytest.raises(MergeError) as exc_info:
            load_with_includes(prd_a_path)

        assert "circular" in str(exc_info.value).lower()


@pytest.mark.include_schema
def test_load_with_includes_missing_file():
    """Test that missing include file raises MergeError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = os.path.join(tmpdir, "prd.json")

        prd = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [],
            "prd": {"include": ["nonexistent_subproject.json"]},
        }

        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        # Should raise MergeError for missing file
        with pytest.raises(MergeError) as exc_info:
            load_with_includes(prd_path)

        assert "not found" in str(exc_info.value).lower()


@pytest.mark.include_schema
def test_load_with_includes_namespacing():
    """Test that story IDs are correctly prefixed with namespace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create main PRD with a subproject include
        main_prd_path = os.path.join(tmpdir, "prd.json")
        sub_prd_path = os.path.join(tmpdir, "api_prd.json")

        sub_prd = {
            "productName": "API",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-50",
                    "title": "API Auth",
                    "priority": "high",
                    "acceptanceCriteria": [],
                    "passes": False,
                    "dependencies": [],
                }
            ],
        }

        main_prd = {
            "productName": "Main",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Main Feature",
                    "priority": "high",
                    "acceptanceCriteria": [],
                    "passes": False,
                    "dependencies": [],
                }
            ],
            "prd": {"include": ["api_prd.json"]},
        }

        with open(sub_prd_path, "w", encoding="utf-8") as f:
            json.dump(sub_prd, f)
        with open(main_prd_path, "w", encoding="utf-8") as f:
            json.dump(main_prd, f)

        # Load with includes
        result = load_with_includes(main_prd_path)
        stories = result.get("userStories", [])

        # Should have 2 stories: main story + prefixed subproject story
        assert len(stories) == 2

        story_ids = {s["id"] for s in stories}
        assert "US-1" in story_ids  # Main story without prefix
        assert "api:US-50" in story_ids  # Subproject story with api: prefix


def test_load_with_includes_empty_include_array():
    """Test PRD with empty include array (should pass schema and load normally)."""
    prd_data = {
        "productName": "Test",
        "branchName": "main",
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "US-001",
                "title": "Test",
                "priority": "high",
                "acceptanceCriteria": ["Test criterion"],
                "passes": False,
                "dependencies": [],
            }
        ],
        "prd": {"include": []},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = os.path.join(tmpdir, "prd.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd_data, f)

        # Should validate
        errors = validate_prd(prd_data)
        assert len(errors) == 0, f"Validation failed: {errors}"

        # Should load without error
        result = load_with_includes(prd_path)
        stories = result.get("userStories", [])
        assert len(stories) == 1
        assert stories[0]["id"] == "US-001"


@pytest.mark.include_schema
def test_load_with_includes_no_prd_object():
    """Test PRD without prd object (backward compatibility)."""
    prd_data = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-1",
                "title": "Test",
                "priority": "high",
                "acceptanceCriteria": [],
                "passes": False,
                "dependencies": [],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = os.path.join(tmpdir, "prd.json")
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd_data, f)

        # Should load without error (backward compatible)
        result = load_with_includes(prd_path)
        stories = result.get("userStories", [])
        assert len(stories) == 1
        assert stories[0]["id"] == "US-1"
