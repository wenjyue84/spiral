"""Tests for lib/validate_stories.py — semantic similarity deduplication (US-371)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from validate_stories import _semantic_dedup_pass, _story_text


def _make_story(
    title: str,
    description: str,
    acs: list[str],
    source: str = "research",
    story_id: str = "US-TST",
) -> dict:
    return {
        "id": story_id,
        "title": title,
        "description": description,
        "acceptanceCriteria": acs,
        "_source": source,
    }


# ── _story_text ───────────────────────────────────────────────────────────────


def test_story_text_combines_title_description_acs():
    story = {
        "title": "Add LRU cache",
        "description": "Implement least-recently-used caching layer",
        "acceptanceCriteria": ["Cache hit returns stored result", "Cache miss triggers fetch"],
    }
    text = _story_text(story)
    assert "Add LRU cache" in text
    assert "Implement least-recently-used caching layer" in text
    assert "Cache hit returns stored result" in text
    assert "Cache miss triggers fetch" in text


def test_story_text_only_uses_first_two_acs():
    story = {
        "title": "T",
        "description": "D",
        "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
    }
    text = _story_text(story)
    assert "AC1" in text
    assert "AC2" in text
    assert "AC3" not in text
    assert "AC4" not in text


def test_story_text_handles_missing_fields():
    assert _story_text({}) == ""
    assert _story_text({"title": "Only title"}) == "Only title"


# ── _semantic_dedup_pass ──────────────────────────────────────────────────────


def test_semantic_dedup_exact_duplicate_rejected():
    """Exact same story text → cosine sim ~1.0 → rejected at threshold 0.5."""
    existing = [
        _make_story(
            "Add LRU cache to research phase for duplicate query avoidance",
            "Implement least-recently-used cache to avoid repeated research API calls",
            ["Cache hit returns stored result", "Cache miss triggers new research"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add LRU cache to research phase for duplicate query avoidance",
        "Implement least-recently-used cache to avoid repeated research API calls",
        ["Cache hit returns stored result", "Cache miss triggers new research"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 0
    assert len(rejected) == 1
    assert rejected[0]["_rejected"] is True
    assert "semantic_duplicate_of: US-100" in rejected[0]["_rejection_reason"]


def test_semantic_dedup_near_duplicate_rejected_at_lower_threshold():
    """Near-identical wording (minor rephrasing) → rejected at threshold 0.5."""
    existing = [
        _make_story(
            "Add LRU caching layer to Phase R to skip repeated research queries",
            "Implement LRU cache for Phase R research results to avoid duplicate API calls",
            ["Cache stores results keyed by query hash", "LRU evicts oldest entry on capacity"],
            story_id="US-200",
        )
    ]
    candidate = _make_story(
        "Add LRU caching to Phase R to avoid repeated research API queries",
        "Implement LRU cache for Phase R to store results and skip duplicate research calls",
        ["Results stored keyed by query hash", "LRU eviction removes oldest entry when capacity reached"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    # High word overlap → should be caught as duplicate
    assert len(kept) + len(rejected) == 1


def test_semantic_dedup_distinct_stories_pass():
    """Stories on completely different topics should not be rejected at threshold 0.85."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add parallel worker timeout monitoring with heartbeat",
        "Implement heartbeat-based worker timeout detection in run_parallel_ralph.sh",
        ["Worker emits heartbeat every 30 seconds", "Timeout triggers worker kill and retry"],
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.85)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_skips_test_fix_source():
    """test-fix stories bypass semantic dedup entirely."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    # Exact same text but source=test-fix
    candidate = _make_story(
        "Add LRU cache to research phase",
        "Implement least-recently-used cache for Phase R research results",
        ["Cache hit returns stored result"],
        source="test-fix",
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_skips_seed_source():
    """seed stories bypass semantic dedup entirely."""
    existing = [
        _make_story(
            "Add LRU cache to research phase",
            "Implement least-recently-used cache for Phase R research results",
            ["Cache hit returns stored result"],
            story_id="US-100",
        )
    ]
    candidate = _make_story(
        "Add LRU cache to research phase",
        "Implement least-recently-used cache for Phase R research results",
        ["Cache hit returns stored result"],
        source="seed",
    )
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.5)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_empty_existing_returns_all_kept():
    """No existing stories → nothing to compare against → all candidates kept."""
    candidate = _make_story("Add cache", "Add LRU cache", ["Cache hit"])
    kept, rejected = _semantic_dedup_pass([candidate], [], threshold=0.85)
    assert len(kept) == 1
    assert len(rejected) == 0


def test_semantic_dedup_threshold_zero_disables():
    """threshold=0.0 disables semantic dedup regardless of similarity."""
    existing = [_make_story("Add cache", "Add LRU cache", ["Cache hit"], story_id="US-X")]
    candidate = _make_story("Add cache", "Add LRU cache", ["Cache hit"])
    kept, rejected = _semantic_dedup_pass([candidate], existing, threshold=0.0)
    assert len(kept) == 1
    assert len(rejected) == 0
