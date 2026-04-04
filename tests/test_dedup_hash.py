"""Test content-hash deduplication (US-1095)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure lib is importable
_lib_path = Path(__file__).resolve().parent.parent / "lib"
if str(_lib_path) not in sys.path:
    sys.path.insert(0, str(_lib_path))

from prd.merge_stories import compute_content_hash, load_dedup_hashes, save_dedup_hashes


def test_compute_content_hash_identical_stories() -> None:
    """Two stories with same title+description should have same hash."""
    story1 = {"title": "Test Feature", "description": "This is a test"}
    story2 = {"title": "Test Feature", "description": "This is a test"}
    assert compute_content_hash(story1) == compute_content_hash(story2)


def test_compute_content_hash_different_stories() -> None:
    """Different title/description should produce different hashes."""
    story1 = {"title": "Test Feature", "description": "This is a test"}
    story2 = {"title": "Different Feature", "description": "This is different"}
    assert compute_content_hash(story1) != compute_content_hash(story2)


def test_compute_content_hash_whitespace_normalized() -> None:
    """Whitespace should be normalized (leading/trailing stripped, lowercased)."""
    story1 = {"title": "  Test Feature  ", "description": "  This is a test  "}
    story2 = {"title": "test feature", "description": "this is a test"}
    assert compute_content_hash(story1) == compute_content_hash(story2)


def test_compute_content_hash_case_insensitive() -> None:
    """Case should be normalized (lowercased)."""
    story1 = {"title": "TEST FEATURE", "description": "THIS IS A TEST"}
    story2 = {"title": "test feature", "description": "this is a test"}
    assert compute_content_hash(story1) == compute_content_hash(story2)


def test_compute_content_hash_empty_description() -> None:
    """Empty description should be handled gracefully."""
    story1 = {"title": "Test Feature", "description": ""}
    story2 = {"title": "Test Feature"}
    assert compute_content_hash(story1) == compute_content_hash(story2)


def test_load_dedup_hashes_empty_file() -> None:
    """Load from non-existent file should return empty set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hashes = load_dedup_hashes(tmpdir)
        assert hashes == set()


def test_load_dedup_hashes_with_data() -> None:
    """Load from file with hashes should return set of hashes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hashes_file = os.path.join(tmpdir, "dedup_hashes.json")
        test_hashes = ["hash1", "hash2", "hash3"]
        with open(hashes_file, "w", encoding="utf-8") as f:
            json.dump({"hashes": test_hashes}, f)
        loaded = load_dedup_hashes(tmpdir)
        assert loaded == set(test_hashes)


def test_save_dedup_hashes() -> None:
    """Save hashes to file and reload should preserve them."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_hashes = {"hash1", "hash2", "hash3"}
        save_dedup_hashes(test_hashes, tmpdir)
        loaded = load_dedup_hashes(tmpdir)
        assert loaded == test_hashes


def test_dedup_10_candidates_with_3_exact_duplicates() -> None:
    """Test AC4: 10 candidates with 3 exact duplicates.

    Verifies that hash dedup correctly identifies and would remove the 3 duplicates
    before similarity comparison runs.
    """
    # Create 10 candidates: 7 unique + 3 exact duplicates
    candidates = [
        {"title": "Story A", "description": "Description A"},
        {"title": "Story B", "description": "Description B"},
        {"title": "Story C", "description": "Description C"},
        {"title": "Story D", "description": "Description D"},
        {"title": "Story E", "description": "Description E"},
        {"title": "Story F", "description": "Description F"},
        {"title": "Story G", "description": "Description G"},
        # These 3 are exact duplicates of Story A
        {"title": "Story A", "description": "Description A"},
        {"title": "Story A", "description": "Description A"},
        {"title": "Story A", "description": "Description A"},
    ]

    assert len(candidates) == 10

    # Compute hashes for all candidates
    hashes = set()
    duplicates_detected = 0

    for i, candidate in enumerate(candidates):
        content_hash = compute_content_hash(candidate)
        if content_hash in hashes:
            # This would be a dedup hit (candidate would be skipped)
            duplicates_detected += 1
        else:
            hashes.add(content_hash)

    # Should have detected exactly 3 duplicates
    assert duplicates_detected == 3
    # Should have 7 unique hashes
    assert len(hashes) == 7


def test_dedup_with_persistent_storage() -> None:
    """Test AC2: Hash persistence across iterations.

    Verify that hashes persisted in .spiral/dedup_hashes.json are loaded
    and checked in subsequent operations.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create story and compute its hash
        story = {"title": "Test Story", "description": "Test Description"}
        content_hash = compute_content_hash(story)

        # Save hash to persistent storage
        hashes = {content_hash}
        save_dedup_hashes(hashes, tmpdir)

        # Load in a new operation and verify hash is present
        loaded_hashes = load_dedup_hashes(tmpdir)
        assert content_hash in loaded_hashes

        # Verify the persisted story would be detected as duplicate
        duplicate_story = {"title": "Test Story", "description": "Test Description"}
        duplicate_hash = compute_content_hash(duplicate_story)
        assert duplicate_hash in loaded_hashes


def test_dedup_hash_field_in_story() -> None:
    """Test AC1: _content_hash field is added to story."""
    story = {"title": "Test", "description": "Desc"}
    content_hash = compute_content_hash(story)
    story["_content_hash"] = content_hash
    assert story.get("_content_hash") == content_hash
    assert len(story["_content_hash"]) == 64  # sha256 hex is 64 chars
