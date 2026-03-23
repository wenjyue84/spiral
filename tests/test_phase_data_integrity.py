#!/usr/bin/env python3
"""
Phase Data Integrity Validator Tests — US-1070

Validates that each SPIRAL phase (R, T, S, M) outputs conform to expected schemas
and that no data corruption occurs during state transitions.

Tests:
  - assert_research_schema_valid: Phase R research_results.json structure
  - assert_test_failures_no_duplicates: Phase T test_failures.json structure
  - assert_merge_files_safe: Phase M git safety checks
"""

from __future__ import annotations

import json
import re
from typing import Any


def assert_research_schema_valid(research_results: list[dict[str, Any]]) -> None:
    """
    Validate Phase R research_results.json output schema.

    AC1: Phase R output is valid JSON array with {query, source, relevance_score (0-1), text}
    """
    assert isinstance(research_results, list), "research_results must be a list"
    assert len(research_results) > 0, "research_results must not be empty"

    for i, item in enumerate(research_results):
        assert isinstance(item, dict), f"Item {i} must be a dict"

        # Required fields
        assert "query" in item, f"Item {i} missing 'query'"
        assert isinstance(item["query"], str), f"Item {i} query must be string"

        assert "source" in item, f"Item {i} missing 'source'"
        assert isinstance(item["source"], str), f"Item {i} source must be string"

        assert "relevance_score" in item, f"Item {i} missing 'relevance_score'"
        relevance = item["relevance_score"]
        assert isinstance(relevance, (int, float)), f"Item {i} relevance_score must be numeric"
        assert 0 <= relevance <= 1, f"Item {i} relevance_score must be in [0, 1], got {relevance}"

        assert "text" in item, f"Item {i} missing 'text'"
        assert isinstance(item["text"], str), f"Item {i} text must be string"


def assert_test_failures_no_duplicates(test_failures: list[dict[str, Any]]) -> None:
    r"""
    Validate Phase T test_failures.json output schema.

    AC1: Phase T has valid exit_code (1-255), error_category in allowed set,
         test_id matches UT-\d+
    """
    assert isinstance(test_failures, list), "test_failures must be a list"

    seen_ids = set()
    valid_categories = {"compile", "runtime", "timeout", "assertion"}

    for i, item in enumerate(test_failures):
        assert isinstance(item, dict), f"Item {i} must be a dict"

        # Validate exit_code (1-255)
        assert "exit_code" in item, f"Item {i} missing 'exit_code'"
        exit_code = item["exit_code"]
        assert isinstance(exit_code, int), f"Item {i} exit_code must be int"
        assert 1 <= exit_code <= 255, f"Item {i} exit_code {exit_code} not in [1, 255]"

        # Validate error_category
        assert "error_category" in item, f"Item {i} missing 'error_category'"
        category = item["error_category"]
        assert category in valid_categories, (
            f"Item {i} error_category '{category}' not in {valid_categories}"
        )

        # Validate test_id matches UT-NNN pattern
        assert "test_id" in item, f"Item {i} missing 'test_id'"
        test_id = item["test_id"]
        assert isinstance(test_id, str), f"Item {i} test_id must be string"
        assert re.match(r"^UT-\d+$", test_id), f"Item {i} test_id '{test_id}' doesn't match UT-\\d+"

        # Check for duplicates
        assert test_id not in seen_ids, f"Duplicate test_id '{test_id}' at index {i}"
        seen_ids.add(test_id)


def assert_merge_files_safe(modified_files: list[str], commit_message: str) -> None:
    """
    Validate Phase M merge safety checks.

    AC2: git diff --name-only shows only modified files (no path traversal),
         commit message contains US-NNN or UT-NNN story ID
    """
    assert isinstance(modified_files, list), "modified_files must be a list"
    assert isinstance(commit_message, str), "commit_message must be string"

    # Check no path traversal (../ not allowed)
    for filepath in modified_files:
        assert isinstance(filepath, str), f"File path must be string, got {type(filepath).__name__}"
        assert "../" not in filepath, f"Path traversal detected in '{filepath}'"
        assert "\\" in filepath or "/" in filepath or len(filepath) > 0, (
            f"Invalid file path '{filepath}'"
        )

    # Check commit message contains story ID
    pattern = r"(US|UT)-\d+"
    assert re.search(pattern, commit_message), (
        f"Commit message missing story ID (US-NNN or UT-NNN): {commit_message}"
    )


def assert_validated_stories_schema(validated_stories: list[dict[str, Any]]) -> None:
    """
    Validate Phase S validated_stories.json output schema.

    AC2: validated_stories contains only stories with constitution_score >= 0.7
         and unique story_ids
    """
    assert isinstance(validated_stories, list), "validated_stories must be a list"

    seen_ids = set()

    for i, story in enumerate(validated_stories):
        assert isinstance(story, dict), f"Story {i} must be a dict"

        # Validate constitution_score
        assert "constitution_score" in story, f"Story {i} missing 'constitution_score'"
        score = story["constitution_score"]
        assert isinstance(score, (int, float)), f"Story {i} constitution_score must be numeric"
        assert 0.7 <= score <= 1.0, (
            f"Story {i} constitution_score {score} must be >= 0.7 and <= 1.0"
        )

        # Validate story_id exists and is unique
        assert "id" in story, f"Story {i} missing 'id'"
        story_id = story["id"]
        assert isinstance(story_id, str), f"Story {i} id must be string"
        assert story_id not in seen_ids, f"Duplicate story_id '{story_id}' at index {i}"
        seen_ids.add(story_id)


# ────────────────────────────────────────────────────────────────────────────
# Integration tests with fixtures
# ────────────────────────────────────────────────────────────────────────────


def test_research_schema_valid() -> None:
    """AC1: Research results conform to schema."""
    research_results = [
        {
            "query": "How to optimize SPIRAL loop?",
            "source": "docs.spiral.ai",
            "relevance_score": 0.95,
            "text": "Use Phase M to merge stories efficiently...",
        },
        {
            "query": "Federation patterns",
            "source": "github.com/spiral",
            "relevance_score": 0.87,
            "text": "Multi-repo setups follow the sub-project pattern...",
        },
    ]
    assert_research_schema_valid(research_results)


def test_test_failures_no_duplicates() -> None:
    """AC1: Test failures have valid schema and no duplicates."""
    test_failures = [
        {
            "exit_code": 1,
            "error_category": "assertion",
            "test_id": "UT-001",
        },
        {
            "exit_code": 139,
            "error_category": "runtime",
            "test_id": "UT-002",
        },
    ]
    assert_test_failures_no_duplicates(test_failures)


def test_merge_files_safe() -> None:
    """AC2: Merge files are safe and commit message has story ID."""
    modified_files = ["lib/spiral/phase_m.py", "tests/test_phase_m.py"]
    commit_message = "feat: US-1070 Phase data integrity validation\n\nAdded schema checks."
    assert_merge_files_safe(modified_files, commit_message)


def test_validated_stories_schema() -> None:
    """AC2: Validated stories have minimum constitution_score and unique IDs."""
    validated_stories = [
        {"id": "US-001", "constitution_score": 0.85, "title": "Feature A"},
        {"id": "US-002", "constitution_score": 0.71, "title": "Feature B"},
    ]
    assert_validated_stories_schema(validated_stories)


def test_invalid_research_schema_rejects_bad_relevance() -> None:
    """Verify schema validation catches out-of-range relevance_score."""
    research_results = [
        {
            "query": "test",
            "source": "test.com",
            "relevance_score": 1.5,  # Invalid: > 1.0
            "text": "test",
        }
    ]
    try:
        assert_research_schema_valid(research_results)
        assert False, "Should have raised assertion for relevance_score > 1.0"
    except AssertionError as e:
        assert "relevance_score must be in [0, 1]" in str(e)


def test_invalid_test_failures_rejects_bad_exit_code() -> None:
    """Verify schema validation catches invalid exit codes."""
    test_failures = [
        {
            "exit_code": 0,  # Invalid: must be 1-255
            "error_category": "runtime",
            "test_id": "UT-001",
        }
    ]
    try:
        assert_test_failures_no_duplicates(test_failures)
        assert False, "Should have raised assertion for exit_code 0"
    except AssertionError as e:
        assert "exit_code" in str(e) and "not in [1, 255]" in str(e)


def test_invalid_merge_rejects_path_traversal() -> None:
    """Verify merge safety catches path traversal attempts."""
    modified_files = ["../../../etc/passwd"]  # Path traversal
    commit_message = "fix: US-001"
    try:
        assert_merge_files_safe(modified_files, commit_message)
        assert False, "Should have raised assertion for path traversal"
    except AssertionError as e:
        assert "Path traversal" in str(e)


def test_invalid_merge_rejects_missing_story_id() -> None:
    """Verify merge safety catches missing story ID in commit message."""
    modified_files = ["lib/test.py"]
    commit_message = "Update some code"  # No US-NNN or UT-NNN
    try:
        assert_merge_files_safe(modified_files, commit_message)
        assert False, "Should have raised assertion for missing story ID"
    except AssertionError as e:
        assert "story ID" in str(e)


def test_invalid_validated_stories_rejects_low_score() -> None:
    """Verify validation catches constitution_score < 0.7."""
    validated_stories = [
        {"id": "US-001", "constitution_score": 0.65, "title": "Feature A"}  # Invalid
    ]
    try:
        assert_validated_stories_schema(validated_stories)
        assert False, "Should have raised assertion for score < 0.7"
    except AssertionError as e:
        assert "constitution_score" in str(e) and ">= 0.7" in str(e)
