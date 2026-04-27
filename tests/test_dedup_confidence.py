#!/usr/bin/env python3
"""Tests for lib/dedup_confidence.py"""

from __future__ import annotations

from pathlib import Path

import pytest

sys_path_insert = __import__("sys").path.insert
sys_path_insert(0, str(Path(__file__).parent.parent))

from lib.dedup_confidence import find_duplicates, merge_stories


@pytest.fixture
def sample_prd() -> dict:
    """Sample prd.json with duplicate and seed stories"""
    return {
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "US-001",
                "title": "Add user authentication system",
                "description": ("Implement user login and signup with JWT tokens for secure auth"),
                "source": "ai-example",
                "acceptanceCriteria": ["Login works", "Signup works"],
                "passes": False,
            },
            {
                "id": "US-002",
                "title": "Add user authentication system",
                "description": ("Implement user login and signup with JWT tokens for secure auth"),
                "source": "research",
                "acceptanceCriteria": ["Users can log in"],
                "passes": False,
            },
            {
                "id": "US-003",
                "title": "Setup database schema",
                "description": "Create tables for users and posts",
                "source": "ai-example",
                "acceptanceCriteria": ["Tables created"],
                "passes": False,
            },
            {
                "id": "US-SEED-001",
                "title": "Seed story - should be excluded",
                "description": "This is a seed story",
                "source": "seed",
                "acceptanceCriteria": [],
                "passes": False,
            },
            {
                "id": "US-004",
                "title": "Already completed story",
                "description": "This one passed",
                "source": "ai-example",
                "acceptanceCriteria": [],
                "passes": True,
            },
        ],
    }


def test_high_confidence_detection(sample_prd: dict) -> None:
    """Verify find_duplicates detects obvious duplicates with confidence ≥0.75"""
    duplicates = find_duplicates(sample_prd, threshold=0.75)

    # US-001 and US-002 should be detected as duplicates (high similarity)
    assert len(duplicates) > 0
    assert duplicates[0][2] >= 0.75

    # Check that the pair exists
    ids_in_result = set()
    for id1, id2, _ in duplicates:
        ids_in_result.add(id1)
        ids_in_result.add(id2)

    # Both US-001 and US-002 should appear in results
    assert "US-001" in ids_in_result or "US-002" in ids_in_result


def test_seed_excluded(sample_prd: dict) -> None:
    """Verify seed stories never appear as dedup candidates"""
    duplicates = find_duplicates(sample_prd, threshold=0.0)

    # No duplicate should contain the seed story
    for id1, id2, _ in duplicates:
        assert "SEED" not in id1
        assert "SEED" not in id2


def test_passed_stories_excluded(sample_prd: dict) -> None:
    """Verify passed stories are excluded from dedup candidates"""
    duplicates = find_duplicates(sample_prd, threshold=0.0)

    for id1, id2, _ in duplicates:
        assert "US-004" not in [id1, id2]


def test_merge_sets_superseded_by(sample_prd: dict) -> None:
    """Verify merge creates new story and marks originals as superseded"""
    result = merge_stories("US-001", "US-002", sample_prd)

    assert result is not None
    stories = {s["id"]: s for s in result["userStories"]}

    # Check that originals are marked superseded
    assert "superseded_by" in stories["US-001"]
    assert "superseded_by" in stories["US-002"]

    merged_id = stories["US-001"]["superseded_by"]
    assert merged_id == stories["US-002"]["superseded_by"]

    # Check that merged story exists
    assert merged_id in stories
    merged = stories[merged_id]

    # Merged story should combine acceptance criteria
    assert len(merged["acceptanceCriteria"]) >= 2
    assert "Login works" in merged["acceptanceCriteria"]
    assert "Users can log in" in merged["acceptanceCriteria"]


def test_merge_invalid_story_id(sample_prd: dict) -> None:
    """Verify merge returns None if story ID not found"""
    result = merge_stories("US-001", "US-NOTFOUND", sample_prd)
    assert result is None


def test_merge_preserves_other_stories(sample_prd: dict) -> None:
    """Verify merge doesn't affect other stories"""
    original_count = len(sample_prd["userStories"])
    result = merge_stories("US-001", "US-002", sample_prd)

    assert result is not None
    # Should have added one new merged story
    assert len(result["userStories"]) == original_count + 1


def test_merge_with_dependencies(sample_prd: dict) -> None:
    """Verify merge combines dependencies from both stories"""
    sample_prd["userStories"][0]["dependencies"] = ["US-100"]
    sample_prd["userStories"][1]["dependencies"] = ["US-200"]

    result = merge_stories("US-001", "US-002", sample_prd)
    assert result is not None

    merged_id = result["userStories"][0]["superseded_by"]
    merged = next(s for s in result["userStories"] if s["id"] == merged_id)

    # Should have both dependencies (deduplicated)
    assert set(merged["dependencies"]) >= {"US-100", "US-200"}


def test_find_duplicates_empty_prd() -> None:
    """Verify find_duplicates handles empty PRD gracefully"""
    empty_prd = {"userStories": []}
    duplicates = find_duplicates(empty_prd)
    assert duplicates == []


def test_find_duplicates_single_story() -> None:
    """Verify find_duplicates returns empty list with <2 candidates"""
    prd = {
        "userStories": [
            {
                "id": "US-001",
                "title": "Test story",
                "description": "A test",
                "source": "ai-example",
                "acceptanceCriteria": [],
                "passes": False,
            }
        ]
    }
    duplicates = find_duplicates(prd)
    assert duplicates == []


def test_threshold_filtering(sample_prd: dict) -> None:
    """Verify threshold parameter filters results correctly"""
    # High threshold should return fewer results
    high_threshold_results = find_duplicates(sample_prd, threshold=0.95)
    low_threshold_results = find_duplicates(sample_prd, threshold=0.5)

    assert len(high_threshold_results) <= len(low_threshold_results)
