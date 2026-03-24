"""Integration tests for US-1060: Episodic Memory Relevance Scorer."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from episodic_memory import EpisodicMemory, get_similar_patterns


def _seed_patterns(mem: EpisodicMemory) -> None:
    """Store 5 diverse episodic patterns with distinct vocabularies."""
    mem.write(
        "US-200",
        {
            "approach": "authentication token refresh authentication retry authentication backoff",
            "outcome": "pass",
            "files_touched": "lib/auth.py",
            "description": "authentication token expired authentication 401 authentication refresh",
        },
    )
    mem.write(
        "US-201",
        {
            "approach": "database migration alembic index table schema",
            "outcome": "pass",
            "files_touched": "migrations/002.sql",
            "description": "database migration index performance schema upgrade",
        },
    )
    mem.write(
        "US-202",
        {
            "approach": "sidebar layout overflow css navigation component",
            "outcome": "pass",
            "files_touched": "src/Sidebar.tsx",
            "description": "sidebar layout overflow small screens css flex",
        },
    )
    mem.write(
        "US-203",
        {
            "approach": "redis caching layer config values cache eviction",
            "outcome": "pass",
            "files_touched": "lib/cache.py",
            "description": "redis caching configuration lookups cache performance",
        },
    )
    mem.write(
        "US-204",
        {
            "approach": "webhook signature verification hmac sha256 endpoint",
            "outcome": "pass",
            "files_touched": "lib/webhooks.py",
            "description": "webhook signature hmac endpoint verification security",
        },
    )


def test_auth_pattern_ranks_first() -> None:
    """AC3: Auth-related query returns auth pattern as top result with >80% similarity."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        _seed_patterns(mem)

        results = get_similar_patterns(
            "authentication token expired authentication retry refresh",
            top_k=3,
            memory_path=path,
        )

        assert len(results) >= 1, "Should return at least 1 pattern"
        top = results[0]
        assert top["story_id"] == "US-200", f"Auth pattern should rank first, got {top['story_id']}"
        assert top["similarity_score"] > 0.80, f"Auth similarity should be >80%, got {top['similarity_score']:.2%}"


def test_results_include_similarity_score() -> None:
    """Every returned pattern has a similarity_score field."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        _seed_patterns(mem)

        results = get_similar_patterns("database migration", top_k=3, memory_path=path)
        for r in results:
            assert "similarity_score" in r, "Each result must have similarity_score"
            assert 0.0 <= r["similarity_score"] <= 1.0


def test_top_k_limits_results() -> None:
    """get_similar_patterns respects top_k parameter."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        mem = EpisodicMemory(path)
        _seed_patterns(mem)

        results = get_similar_patterns("any query text here", top_k=2, memory_path=path)
        assert len(results) <= 2


def test_empty_store_returns_empty() -> None:
    """Empty memory store returns empty list without error."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "mem.jsonl")
        results = get_similar_patterns("auth token fix", top_k=3, memory_path=path)
        assert results == []
