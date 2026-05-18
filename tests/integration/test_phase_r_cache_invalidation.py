"""Integration test: Phase R research cache invalidation on story title change.

Story US-1441: When a story's title changes, the Phase R research cache
key changes and the old entry is invalidated (marked with invalidated_at).

Test command:
    uv run pytest tests/integration/test_phase_r_cache_invalidation.py::test_cache_invalidated_on_title_change -v -s
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_spiral_root = str(Path(__file__).parent.parent.parent)
if _spiral_root not in sys.path:
    sys.path.insert(0, _spiral_root)

from lib.phase_r_cache import (
    cache_key_from_story,
    cache_story_research,
    check_cache_validity,
    invalidate_story_cache_if_stale,
)


def test_cache_invalidated_on_title_change(tmp_path: Path) -> None:
    """AC1+AC2: Cache invalidated when story title changes; both entries in JSON.

    Scenario:
    - Story 'Implement auth feature' → cached (title_hash = hash_A)
    - Title updated to 'Implement OAuth 2.0 flow' → (title_hash = hash_B)
    - invalidate_story_cache_if_stale() marks hash_A entry with invalidated_at
    - cache_story_research() stores fresh entry under hash_B
    - research_cache.json contains both entries with correct state
    """
    cache_file = str(tmp_path / ".spiral" / "research_cache.json")

    # --- Step 1: original story and mocked Gemini research ---
    story_original: dict[str, object] = {
        "id": "US-TEST",
        "title": "Implement auth feature",
        "priority": "medium",
    }
    mock_results_original = {
        "synthesis": "Authentication implementation guide",
        "sources": ["https://example.com/auth"],
    }

    # Cache research for original title
    original_hash = cache_story_research(story_original, mock_results_original, cache_file)

    # Verify: cache entry is valid for original story
    with open(cache_file, encoding="utf-8") as f:
        cache_data = json.load(f)
    assert original_hash in cache_data
    assert check_cache_validity(story_original, cache_data[original_hash])

    # --- Step 2: story title changes (rename) ---
    story_updated: dict[str, object] = {**story_original, "title": "Implement OAuth 2.0 flow"}
    new_hash = cache_key_from_story(story_updated)

    # Hashes must differ (different titles)
    assert original_hash != new_hash

    # Existing cache entry is now stale for the updated story
    assert not check_cache_validity(story_updated, cache_data[original_hash])

    # --- Step 3: invalidate stale entries ---
    did_invalidate = invalidate_story_cache_if_stale(story_updated, cache_file)
    assert did_invalidate, "Expected stale entry to be invalidated"

    # --- Step 4: cache fresh research under the new title ---
    mock_results_updated = {
        "synthesis": "OAuth 2.0 implementation guide with authorization flows",
        "sources": ["https://example.com/oauth2", "https://oauth.net/2/"],
    }
    returned_hash = cache_story_research(story_updated, mock_results_updated, cache_file)
    assert returned_hash == new_hash

    # --- Step 5: verify research_cache.json contains both entries ---
    with open(cache_file, encoding="utf-8") as f:
        final_cache = json.load(f)

    # Old entry: marked with invalidated_at, original title preserved
    assert original_hash in final_cache
    old_entry = final_cache[original_hash]
    assert "invalidated_at" in old_entry, "Old entry must have invalidated_at timestamp"
    assert old_entry["story_title"] == "Implement auth feature"
    assert isinstance(old_entry["invalidated_at"], str)
    assert len(old_entry["invalidated_at"]) > 0

    # New entry: fresh research, no invalidated_at
    assert new_hash in final_cache
    new_entry = final_cache[new_hash]
    assert "invalidated_at" not in new_entry, "New entry must not be invalidated"
    assert new_entry["story_title"] == "Implement OAuth 2.0 flow"
    assert "timestamp_created" in new_entry
    assert new_entry["results"]["synthesis"] == ("OAuth 2.0 implementation guide with authorization flows")
    assert "https://oauth.net/2/" in new_entry["results"]["sources"]


def test_cache_key_changes_on_title_rename() -> None:
    """AC1 (unit): cache_key_from_story produces different keys for different titles."""
    story_a = {"id": "US-1", "title": "Implement auth feature"}
    story_b = {"id": "US-1", "title": "Implement OAuth 2.0 flow"}

    key_a = cache_key_from_story(story_a)
    key_b = cache_key_from_story(story_b)

    assert key_a != key_b
    assert len(key_a) == 64  # sha256 hex length
    assert len(key_b) == 64


def test_check_cache_validity_detects_stale_title(tmp_path: Path) -> None:
    """AC3 (unit): check_cache_validity returns False for changed title; True for same."""
    cache_file = str(tmp_path / ".spiral" / "research_cache.json")

    story = {"id": "US-2", "title": "Implement auth feature"}
    cache_story_research(story, {"result": "cached"}, cache_file)

    with open(cache_file, encoding="utf-8") as f:
        cache_data = json.load(f)
    entry = cache_data[cache_key_from_story(story)]

    # Same title → valid
    assert check_cache_validity(story, entry)

    # Changed title → stale
    renamed_story = {**story, "title": "Implement OAuth 2.0 flow"}
    assert not check_cache_validity(renamed_story, entry)


def test_no_invalidation_when_title_unchanged(tmp_path: Path) -> None:
    """invalidate_story_cache_if_stale returns False when title has not changed."""
    cache_file = str(tmp_path / ".spiral" / "research_cache.json")

    story: dict[str, object] = {"id": "US-3", "title": "Stable title"}
    cache_story_research(story, {"result": "ok"}, cache_file)

    # Same story → nothing to invalidate
    did_invalidate = invalidate_story_cache_if_stale(story, cache_file)
    assert not did_invalidate

    with open(cache_file, encoding="utf-8") as f:
        cache_data = json.load(f)
    entry = cache_data[cache_key_from_story(story)]
    assert "invalidated_at" not in entry
