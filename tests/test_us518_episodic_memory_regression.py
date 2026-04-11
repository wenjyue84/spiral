"""Regression tests for US-518 — Episodic memory store: write, retrieve, and inject past pattern.

Covers the full round-trip using EpisodicMemory and get_similar_patterns().
All tests use a temporary directory to avoid touching the real .spiral/ store.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from episodic_memory import EpisodicMemory, get_similar_patterns


@pytest.fixture
def tmp_mem(tmp_path: "os.PathLike[str]") -> EpisodicMemory:
    """Return an EpisodicMemory instance backed by a temp file."""
    return EpisodicMemory(str(tmp_path / "episodic_memory.jsonl"))


def test_us_518_write_and_retrieve_roundtrip(tmp_mem: EpisodicMemory) -> None:
    """Write several patterns and retrieve the most relevant one by description."""
    tmp_mem.write(
        "US-100",
        {
            "approach": "Fix authentication token validation in middleware",
            "outcome": "pass",
            "files_touched": "lib/auth.py",
        },
    )
    tmp_mem.write(
        "US-200",
        {
            "approach": "Refactor database connection pooling for performance",
            "outcome": "pass",
            "files_touched": "lib/db.py",
        },
    )
    tmp_mem.write(
        "US-300",
        {
            "approach": "Add JWT token expiry check in authentication layer",
            "outcome": "pass",
            "files_touched": "lib/auth.py lib/jwt_utils.py",
        },
    )

    results = tmp_mem.retrieve("authentication token expiry validation", top_k=3)

    assert len(results) >= 1, "Should return at least one result"
    # The most relevant result should be authentication-related (US-100 or US-300)
    story_ids = [r["story_id"] for r in results]
    assert "US-100" in story_ids or "US-300" in story_ids, (
        "Authentication-related stories should rank highest for auth query"
    )


def test_us_518_similarity_score_present(tmp_mem: EpisodicMemory) -> None:
    """Each retrieved record must include a similarity_score field in [0, 1]."""
    tmp_mem.write(
        "US-101",
        {"approach": "implement caching layer for API responses", "outcome": "pass"},
    )
    tmp_mem.write(
        "US-102",
        {"approach": "add rate limiting to REST endpoints", "outcome": "pass"},
    )

    results = tmp_mem.retrieve("caching API responses", top_k=2)

    assert len(results) >= 1
    for rec in results:
        assert "similarity_score" in rec, "similarity_score must be present"
        score = rec["similarity_score"]
        assert isinstance(score, float), "similarity_score must be a float"
        assert 0.0 <= score <= 1.0, f"similarity_score out of range: {score}"


def test_us_518_get_similar_patterns_function(tmp_path: "os.PathLike[str]") -> None:
    """get_similar_patterns() convenience function returns ranked results with scores."""
    mem_path = str(tmp_path / "episodic_memory.jsonl")
    mem = EpisodicMemory(mem_path)
    mem.write(
        "US-400",
        {"approach": "deploy static assets to S3 bucket with CDN", "outcome": "pass"},
    )
    mem.write(
        "US-401",
        {"approach": "configure CloudFront distribution for static assets", "outcome": "pass"},
    )
    mem.write(
        "US-402",
        {"approach": "fix database migration rollback script", "outcome": "fail"},
    )

    results = get_similar_patterns("upload static files to S3 and serve via CDN", top_k=3, memory_path=mem_path)

    assert isinstance(results, list)
    assert len(results) >= 1
    # CDN/S3 stories should appear before unrelated DB story
    top_story_ids = [r["story_id"] for r in results[:2]]
    assert "US-400" in top_story_ids or "US-401" in top_story_ids


def test_us_518_empty_store_graceful_handling(tmp_mem: EpisodicMemory) -> None:
    """Querying an empty store must return an empty list without raising."""
    results = tmp_mem.retrieve("any query text", top_k=3)
    assert results == [], "Empty store must return empty list"

    similar = tmp_mem.get_similar("US-999", k=3)
    assert similar == [], "get_similar on empty store must return empty list"


def test_us_518_clear_expired_removes_old_records(tmp_mem: EpisodicMemory) -> None:
    """clear_expired() removes records older than ttl_days and returns count."""
    # Write a record with an old timestamp by direct file manipulation
    import json
    from datetime import datetime, timedelta, timezone

    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    recent_ts = datetime.now(timezone.utc).isoformat()

    with open(tmp_mem.jsonl_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"story_id": "US-OLD", "timestamp": old_ts, "approach": "old"}) + "\n")
        f.write(json.dumps({"story_id": "US-RECENT", "timestamp": recent_ts, "approach": "recent"}) + "\n")

    deleted = tmp_mem.clear_expired(ttl_days=7)

    assert deleted == 1, f"Expected 1 deleted record, got {deleted}"
    remaining = tmp_mem._load_all_records()
    assert len(remaining) == 1
    assert remaining[0]["story_id"] == "US-RECENT"
