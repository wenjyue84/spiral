"""Tests for lib/research_cache.py — semantic query caching with TF-IDF."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "research"))

from research_cache import (
    get_cached_result,
    jaccard_similarity,
    load_research_cache,
    record_query_result,
    tokenize,
)


class TestTokenize:
    """Test tokenization of queries."""

    def test_basic_tokenization(self) -> None:
        tokens = tokenize("find Python tutorial")
        assert "find" in tokens
        assert "python" in tokens
        assert "tutorial" in tokens

    def test_lowercase_conversion(self) -> None:
        tokens = tokenize("UPPERCASE Text")
        assert "uppercase" in tokens
        assert "text" in tokens

    def test_empty_query(self) -> None:
        tokens = tokenize("")
        assert tokens == []


class TestJaccardSimilarity:
    """Test Jaccard similarity computation."""

    def test_identical_sets(self) -> None:
        tokens = {"hello", "world"}
        assert jaccard_similarity(tokens, tokens) == pytest.approx(1.0)

    def test_disjoint_sets(self) -> None:
        set1 = {"hello"}
        set2 = {"world"}
        assert jaccard_similarity(set1, set2) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        set1 = {"python", "tutorial", "learn"}
        set2 = {"python", "programming", "tutorial"}
        # intersection = 2, union = 4, jaccard = 2/4 = 0.5
        assert jaccard_similarity(set1, set2) == pytest.approx(0.5)

    def test_empty_sets(self) -> None:
        assert jaccard_similarity(set(), set()) == 1.0
        assert jaccard_similarity({"a"}, set()) == 0.0


class TestCacheHitParaphrased:
    """Test cache hit for paraphrased queries (main acceptance criterion)."""

    def test_paraphrased_query_returns_cached_result(self, tmp_path: Path) -> None:
        """Cache hit: paraphrased query >0.90 similar returns cached result."""
        cache_path = tmp_path / "research_cache.json"

        # Record original query
        original = "how to learn Python programming"
        original_result = "Python is a great language for beginners"
        record_query_result(original, original_result, cache_path, iteration=0, ttl_iterations=5)

        # Query with paraphrase
        paraphrased = "Python programming tutorial for beginners"
        is_hit, result = get_cached_result(paraphrased, cache_path, similarity_threshold=0.90)

        assert is_hit is True
        assert result == original_result


class TestCacheMissNovelQuery:
    """Test cache miss for novel queries."""

    def test_novel_query_cache_miss(self, tmp_path: Path) -> None:
        """Cache miss: novel query not cached returns False."""
        cache_path = tmp_path / "research_cache.json"

        # Record a query
        record_query_result("Python tutorial", "Content", cache_path, iteration=0, ttl_iterations=5)

        # Query completely different topic
        is_hit, result = get_cached_result("how to cook pasta", cache_path, similarity_threshold=0.90)

        assert is_hit is False
        assert result == ""


class TestTTLPruning:
    """Test TTL-based pruning of old cache entries."""

    def test_old_entries_pruned_beyond_ttl(self, tmp_path: Path) -> None:
        """Cache entries older than TTL are pruned on save."""
        cache_path = tmp_path / "research_cache.json"
        ttl = 5

        # Record queries from iterations 0-7
        for i in range(8):
            record_query_result(
                f"query {i}",
                f"result {i}",
                cache_path,
                iteration=i,
                ttl_iterations=ttl,
            )

        # Load at iteration 7: should keep only iterations 2-7 (within TTL of 5)
        cached = load_research_cache(cache_path)

        # Should have pruned iteration 0 and 1
        assert len(cached) <= 6
        assert all(q.iteration >= 2 for q in cached)


class TestCacheRoundTrip:
    """Test save and load cycle."""

    def test_save_and_load_preserves_tokens(self, tmp_path: Path) -> None:
        """Saved tokens are correctly loaded."""
        cache_path = tmp_path / "research_cache.json"

        query = "machine learning basics"
        result = "ML is a subset of AI"
        record_query_result(query, result, cache_path, iteration=0, ttl_iterations=5)

        # Load and check
        cached = load_research_cache(cache_path)
        assert len(cached) == 1
        assert cached[0].query == query
        assert cached[0].result == result
        assert len(cached[0].tokens) > 0
        assert "machine" in cached[0].tokens
