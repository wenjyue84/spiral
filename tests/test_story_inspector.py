"""Tests for lib.story_inspector module."""

import json
import tempfile
from pathlib import Path

import pytest

from lib.story_inspector import (
    estimate_complexity,
    find_blockers_and_dependents,
    format_inspect_output,
    load_story_by_id,
)


@pytest.fixture
def sample_prd_file() -> str:
    """Create a temporary PRD file with test stories."""
    prd_data = {
        "schemaVersion": 1,
        "productName": "Test",
        "userStories": [
            {
                "id": "US-001",
                "title": "Base feature",
                "description": "This is a base feature",
                "acceptanceCriteria": ["AC 1", "AC 2"],
                "dependencies": [],
                "passes": True,
                "_source": "seed",
            },
            {
                "id": "US-002",
                "title": "Dependent feature",
                "description": "This feature depends on US-001",
                "acceptanceCriteria": [
                    "Must work with US-001",
                    "Should integrate properly",
                ],
                "dependencies": ["US-001"],
                "passes": False,
                "_source": "ai-example",
            },
            {
                "id": "US-003",
                "title": "Large feature",
                "description": "This is a large feature with many ACs",
                "acceptanceCriteria": [
                    "AC 1 - do something",
                    "AC 2 - do another thing",
                    "AC 3 - validate the output",
                    "AC 4 - handle edge cases",
                    "AC 5 - write comprehensive tests",
                    "AC 6 - document the feature",
                ]
                * 3,
                "dependencies": ["US-001", "US-002"],
                "passes": False,
                "_source": "research",
            },
        ],
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(prd_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink()


def test_load_story_by_id(sample_prd_file: str) -> None:
    """Test loading a story by ID."""
    story = load_story_by_id(sample_prd_file, "US-001")
    assert story is not None
    assert story["id"] == "US-001"
    assert story["title"] == "Base feature"


def test_load_story_not_found(sample_prd_file: str) -> None:
    """Test loading a non-existent story."""
    story = load_story_by_id(sample_prd_file, "US-999")
    assert story is None


def test_load_story_invalid_file() -> None:
    """Test loading from non-existent file."""
    story = load_story_by_id("/nonexistent/file.json", "US-001")
    assert story is None


def test_find_blockers(sample_prd_file: str) -> None:
    """Test finding blockers for a story."""
    blockers, dependents = find_blockers_and_dependents(sample_prd_file, "US-002")
    assert blockers == ["US-001"]
    assert "US-003" in dependents  # US-003 depends on US-002


def test_find_dependents(sample_prd_file: str) -> None:
    """Test finding dependents of a story."""
    blockers, dependents = find_blockers_and_dependents(sample_prd_file, "US-001")
    assert blockers == []
    assert "US-002" in dependents
    assert "US-003" in dependents


def test_find_no_blockers(sample_prd_file: str) -> None:
    """Test finding blockers for story with no dependencies."""
    blockers, dependents = find_blockers_and_dependents(sample_prd_file, "US-001")
    assert blockers == []


def test_estimate_complexity_small() -> None:
    """Test complexity estimation for small stories."""
    story = {
        "acceptanceCriteria": ["AC 1", "AC 2"],
    }
    assert estimate_complexity(story) == "small"


def test_estimate_complexity_medium() -> None:
    """Test complexity estimation for medium stories."""
    story = {
        "acceptanceCriteria": [
            "This is a longer acceptance criterion with more details and specifications about the implementation",
            "And another one with more words in it that adds up to get over thirty words total so this is truly medium",
        ],
    }
    assert estimate_complexity(story) == "medium"


def test_estimate_complexity_large() -> None:
    """Test complexity estimation for large stories."""
    story = {
        "acceptanceCriteria": [
            " ".join(["word"] * 120),
        ],
    }
    assert estimate_complexity(story) == "large"


def test_estimate_complexity_empty() -> None:
    """Test complexity estimation for stories with no ACs."""
    story = {"acceptanceCriteria": []}
    assert estimate_complexity(story) == "small"


def test_format_inspect_output(sample_prd_file: str) -> None:
    """Test formatting inspect output."""
    story = load_story_by_id(sample_prd_file, "US-002")
    assert story is not None
    blockers, dependents = find_blockers_and_dependents(sample_prd_file, "US-002")
    complexity = estimate_complexity(story)

    output = format_inspect_output(story, blockers, dependents, complexity)

    # Check that output contains expected elements
    assert "US-002" in output
    assert "Dependent feature" in output
    assert "⏳ PENDING" in output  # Not passed
    assert "US-001" in output  # Blocker
    assert "US-003" in output  # Dependent
    assert f"Complexity: {complexity}" in output
    assert "ai-example" in output  # Source


def test_format_inspect_output_passed(sample_prd_file: str) -> None:
    """Test formatting output for a passed story."""
    story = load_story_by_id(sample_prd_file, "US-001")
    assert story is not None
    blockers, dependents = find_blockers_and_dependents(sample_prd_file, "US-001")
    complexity = estimate_complexity(story)

    output = format_inspect_output(story, blockers, dependents, complexity)

    # Check that output contains expected elements for passed story
    assert "✓ PASSED" in output


def test_format_inspect_output_no_dependencies(sample_prd_file: str) -> None:
    """Test formatting output for a story with no dependencies."""
    story = load_story_by_id(sample_prd_file, "US-001")
    assert story is not None

    output = format_inspect_output(story, [], [], "small")

    # Check that output handles empty blockers/dependents
    assert "(none)" in output
