#!/usr/bin/env python3
"""Tests for Phase S constitution integration — goal alignment and antiPatterns validation."""

import json
import os
import sys
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "spiral"))

from constitution_parser import (
    parse_constitution_rules,
    validate_antipatterns,
    validate_story_against_constitution,
)


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_story(fixtures_dir: Path) -> dict:
    """Load valid constitution story fixture."""
    fixture_path = fixtures_dir / "valid_constitution_story.json"
    with open(fixture_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def invalid_story(fixtures_dir: Path) -> dict:
    """Load invalid constitution story fixture."""
    fixture_path = fixtures_dir / "invalid_goal_story.json"
    with open(fixture_path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def constitution_path() -> str:
    """Return path to constitution.md for testing."""
    # Use the constitution from .specify/memory/
    return os.path.join(os.path.dirname(__file__), "..", ".specify", "memory", "constitution.md")


class TestValidStoryPasses:
    """Test that stories matching constitution goals are accepted."""

    def test_valid_story_passes(self, valid_story: dict, constitution_path: str) -> None:
        """Verify a valid story passes Phase S validation."""
        # Parse constitution rules
        rules = parse_constitution_rules(constitution_path)
        assert rules["parsed"], "Constitution should be parsed successfully"

        # Validate the story against constitution
        is_valid, error_msg = validate_story_against_constitution(valid_story, rules["forbidden_phrases"])

        # Valid story should pass
        assert is_valid, f"Valid story should pass validation: {error_msg}"
        assert error_msg == "", "No error message for valid story"


class TestGoalMismatchFails:
    """Test that stories with goal mismatches are rejected."""

    def test_goal_mismatch_fails(self, invalid_story: dict) -> None:
        """Verify a story with forbidden content fails with constitution violation message."""
        # Use explicit forbidden phrases that match the invalid story
        forbidden_phrases = ["skip testing", "bypass", "quality gates"]

        # Validate the invalid story against these forbidden phrases
        is_valid, error_msg = validate_story_against_constitution(invalid_story, forbidden_phrases)

        # Invalid story should fail validation
        assert not is_valid, "Invalid story should fail validation"
        assert "constitution violation" in error_msg.lower(), (
            f"Error message should contain 'constitution violation', got: {error_msg}"
        )


class TestAntipatternValidation:
    """Test that malformed antiPatterns fields are caught."""

    def test_antipattern_validation_valid(self) -> None:
        """Verify that stories with valid antiPatterns pass."""
        story = {
            "id": "US-100",
            "title": "Test Story",
            "description": "A test story",
            "_decomposed": {"antiPatterns": ["pattern1", "pattern2"]},
        }

        is_valid, error_msg = validate_antipatterns(story)
        assert is_valid, f"Valid antiPatterns should pass: {error_msg}"

    def test_antipattern_validation_no_field(self) -> None:
        """Verify that stories without antiPatterns pass."""
        story = {"id": "US-101", "title": "Test Story", "description": "A test story"}

        is_valid, error_msg = validate_antipatterns(story)
        assert is_valid, f"Story without antiPatterns should pass: {error_msg}"

    def test_antipattern_validation_duplicate_raises(self) -> None:
        """Verify that duplicate antiPatterns raises ValueError."""
        story = {
            "id": "US-102",
            "title": "Test Story",
            "description": "A test story",
            "_decomposed": {"antiPatterns": ["pattern1", "pattern2", "pattern1"]},
        }

        with pytest.raises(ValueError, match="duplicate antiPattern"):
            validate_antipatterns(story)

    def test_antipattern_validation_wrong_type(self) -> None:
        """Verify that non-list antiPatterns fails gracefully."""
        story = {
            "id": "US-103",
            "title": "Test Story",
            "description": "A test story",
            "_decomposed": {"antiPatterns": "not a list"},
        }

        is_valid, error_msg = validate_antipatterns(story)
        assert not is_valid, "Non-list antiPatterns should fail validation"
        assert "must be a list" in error_msg
