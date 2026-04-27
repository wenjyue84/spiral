"""Tests for US-1338: Phase S duplicate detector with embedding cache."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import pytest

from phase_s.duplicate_detector import find_duplicates
from phase_s.embedding_cache import compute_title_hash, load_cache, save_cache


@pytest.fixture
def test_stories() -> list[dict]:
    """Fixture with 5 stories including 2 near-duplicate pairs."""
    return [
        {
            "id": "US-001",
            "title": "Implement user login page with authentication",
            "description": "Create a login form with email and password fields and session management",
        },
        {
            "id": "US-002",
            "title": "Build user login page with session management",
            "description": "Implement authentication form with email password credentials and user sessions",
        },
        {
            "id": "US-003",
            "title": "Display product listing in grid format",
            "description": "Show all products in a grid layout with product name price and thumbnail image",
        },
        {
            "id": "US-004",
            "title": "Show product listing grid with items",
            "description": "Present all products in grid format with name price and image thumbnails",
        },
        {
            "id": "US-005",
            "title": "Setup database schema migrations",
            "description": "Create database schema for users products and orders with migrations",
        },
    ]


def test_find_duplicates(test_stories, tmp_path):
    """Test find_duplicates returns high-similarity pairs above 0.80 threshold.

    Expected: US-001 & US-002 should be detected as duplicates (both about login),
              US-003 & US-004 should be detected as duplicates (both about products).
    """
    cache_dir = str(tmp_path)
    duplicates = find_duplicates(test_stories, similarity_threshold=0.80, cache_dir=cache_dir)

    # Should find at least 2 duplicate pairs
    assert len(duplicates) >= 2, f"Expected at least 2 duplicate pairs, found {len(duplicates)}"

    # Extract story IDs from duplicates
    dup_pairs = {(d[0]["id"], d[1]["id"]) for d in duplicates}

    # Check that the expected near-duplicate pairs are found
    # (allowing for order variation: (A, B) or (B, A) are both acceptable)
    expected_pairs = {("US-001", "US-002"), ("US-002", "US-001"), ("US-003", "US-004"), ("US-004", "US-003")}

    found_pairs = dup_pairs & expected_pairs
    assert len(found_pairs) >= 2, f"Expected to find US-001/US-002 and US-003/US-004 pairs, found: {dup_pairs}"

    # All returned duplicates should have score > 0.80
    for story_a, story_b, score in duplicates:
        assert score > 0.80, f"Duplicate pair {story_a['id']}, {story_b['id']} has score {score}, expected > 0.80"


def test_cache_reuse(test_stories, tmp_path):
    """Test that second call reads from embedding cache without recomputing.

    Verifies that the cache file is created and that a second call with the
    same stories reads embeddings from cache (not recomputing).
    """
    cache_dir = str(tmp_path)
    cache_path = os.path.join(cache_dir, "embedding_cache.jsonl")

    # First call: compute embeddings and cache them
    duplicates_1 = find_duplicates(test_stories, cache_dir=cache_dir)
    assert os.path.isfile(cache_path), f"Cache file not created at {cache_path}"

    # Count cache entries
    with open(cache_path, "r", encoding="utf-8") as f:
        initial_cache_lines = len([line for line in f if line.strip()])

    assert initial_cache_lines == 5, f"Expected 5 cache entries, found {initial_cache_lines}"

    # Second call: should read from cache, not add new entries
    duplicates_2 = find_duplicates(test_stories, cache_dir=cache_dir)

    # Cache should not have grown (no new entries added)
    with open(cache_path, "r", encoding="utf-8") as f:
        final_cache_lines = len([line for line in f if line.strip()])

    assert final_cache_lines == initial_cache_lines, f"Cache grew on second call: {initial_cache_lines} -> {final_cache_lines}"

    # Results should be identical
    assert len(duplicates_1) == len(duplicates_2), "Duplicate count changed between calls"


def test_similarity_threshold(test_stories, tmp_path):
    """Test that only pairs above similarity threshold are returned."""
    cache_dir = str(tmp_path)

    # With a very high threshold, should get fewer or no duplicates
    high_threshold_results = find_duplicates(test_stories, similarity_threshold=0.99, cache_dir=cache_dir)

    # With a moderate threshold, should get more duplicates
    moderate_threshold_results = find_duplicates(
        test_stories, similarity_threshold=0.50, cache_dir=str(tmp_path / "cache2")
    )

    # Should find more pairs with lower threshold
    assert len(moderate_threshold_results) >= len(high_threshold_results)


def test_cache_format(test_stories, tmp_path):
    """Test that cache JSONL format is correct."""
    cache_dir = str(tmp_path)
    cache_path = os.path.join(cache_dir, "embedding_cache.jsonl")

    find_duplicates(test_stories, cache_dir=cache_dir)

    # Load and verify cache format
    cache = load_cache(cache_path)
    assert len(cache) == 5, f"Expected 5 embeddings in cache, found {len(cache)}"

    # Verify each cached embedding is a list of floats
    for title_hash, embedding in cache.items():
        assert isinstance(embedding, list), f"Embedding for {title_hash} is not a list"
        assert len(embedding) > 0, f"Embedding for {title_hash} is empty"
        assert all(isinstance(val, float) for val in embedding), f"Embedding contains non-float values"


def test_empty_stories(tmp_path):
    """Test find_duplicates with empty input."""
    cache_dir = str(tmp_path)
    duplicates = find_duplicates([], cache_dir=cache_dir)
    assert duplicates == []


def test_single_story(tmp_path):
    """Test find_duplicates with only one story."""
    cache_dir = str(tmp_path)
    stories = [
        {
            "id": "US-001",
            "title": "Single story",
            "description": "This is the only story",
        }
    ]
    duplicates = find_duplicates(stories, cache_dir=cache_dir)
    assert duplicates == []
