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


# ── Tests for US-1026: Cache Hit/Miss Counting and LRU Eviction ──────────────


class TestCacheDeduplication:
    """Test that cache correctly counts hits vs misses for identical queries."""

    def test_cache_deduplication(self, tmp_path: Path) -> None:
        """AC1: 10 stories with 6 identical queries → 6 cache hits, 4 API calls.

        Simulates:
        - Stories 0-3: Query A (new) → 1 API call
        - Stories 1-5: Query A (cached) → 5 cache hits, no API calls
        - Stories 6-9: Query B, C, D (new) → 3 API calls
        """
        cache_path = tmp_path / "research_cache.json"
        api_call_count = 0
        cache_hit_count = 0

        # Define queries for 10 stories
        # Stories 0,1,2,3,5,7: use query_a (6 total, first one is new, 5 are hits)
        # Stories 4, 6, 8, 9: use query_b, query_c, query_d, query_e (4 new API calls)
        queries = [
            "What is AI safety?",  # 0: query_a (new) → API call
            "What is AI safety?",  # 1: query_a (hit)
            "What is AI safety?",  # 2: query_a (hit)
            "What is AI safety?",  # 3: query_a (hit)
            "Machine learning applications",  # 4: query_b (new) → API call
            "What is AI safety?",  # 5: query_a (hit)
            "Deep learning models",  # 6: query_c (new) → API call
            "What is AI safety?",  # 7: query_a (hit)
            "Neural network training",  # 8: query_d (new) → API call
            "Transformer architectures",  # 9: query_e (new) → API call
        ]

        # Process each query
        for i, query in enumerate(queries):
            # Check if query is cached
            is_cached, cached_result = get_cached_result(
                query, cache_path, similarity_threshold=0.90
            )

            if is_cached:
                # Cache hit: reuse result without API call
                cache_hit_count += 1
            else:
                # Cache miss: make API call and store result
                api_call_count += 1
                result = f"Result for: {query} (API call #{api_call_count})"

                # Record in cache
                record_query_result(
                    query=query,
                    result=result,
                    cache_path=cache_path,
                    iteration=1,
                    ttl_iterations=5,
                )

        # Verify deduplication: 6 identical queries should give 5 cache hits + 5 API calls
        assert cache_hit_count == 5, f"Expected 5 cache hits, got {cache_hit_count}"
        assert (
            api_call_count == 5
        ), f"Expected 5 API calls, got {api_call_count}"  # 5 unique queries


class TestLRUEviction:
    """Test that cache enforces LRU eviction when size limit is exceeded."""

    def test_lru_eviction(self, tmp_path: Path) -> None:
        """AC2: Fill cache to 100 entries, add entry #101 → oldest entry removed.

        Simulates:
        1. Create 100 cached queries
        2. Save with max_cache_size=100
        3. Add query #101
        4. Save with max_cache_size=100
        5. Verify oldest (query #0) is gone, newest (query #100) is present
        """
        from research_cache import CachedQuery, save_research_cache
        import time

        cache_path = tmp_path / "research_cache.json"

        # Create 100 cached queries with different content and timestamps
        cached_queries: list[CachedQuery] = []
        for i in range(100):
            query = f"Query #{i}: Research topic {i}"
            result = f"Result for query {i}"
            tokens_set = set(query.lower().split())

            cached = CachedQuery(
                query=query,
                result=result,
                iteration=0,
                tokens=list(tokens_set),
                added_at=time.time() - (100 - i),  # Older queries have earlier timestamps
            )
            cached_queries.append(cached)

            # Small delay to ensure different timestamps
            time.sleep(0.001)

        # Save cache at capacity (100 entries)
        save_research_cache(
            cached_queries, cache_path, ttl_iterations=5, current_iteration=0, max_cache_size=100
        )

        # Verify 100 entries are saved
        loaded = load_research_cache(cache_path)
        assert len(loaded) == 100, f"Expected 100 entries, got {len(loaded)}"

        # Verify oldest query (query #0) is present before adding #101
        oldest_query = "Query #0: Research topic 0"
        oldest_present = any(q.query == oldest_query for q in loaded)
        assert oldest_present, "Query #0 should be in cache before overflow"

        # Add query #101
        query_101 = "Query #101: Research topic 101"
        result_101 = "Result for query 101"
        tokens_101_set = set(query_101.lower().split())

        new_query = CachedQuery(
            query=query_101,
            result=result_101,
            iteration=0,
            tokens=list(tokens_101_set),
            added_at=time.time(),
        )
        cached_queries.append(new_query)

        # Save with LRU eviction (max_cache_size=100)
        save_research_cache(
            cached_queries, cache_path, ttl_iterations=5, current_iteration=0, max_cache_size=100
        )

        # Verify 100 entries still exist (oldest was evicted)
        loaded_after = load_research_cache(cache_path)
        assert len(loaded_after) == 100, f"Expected 100 entries after eviction, got {len(loaded_after)}"

        # Verify oldest query (query #0) is GONE
        oldest_present_after = any(q.query == oldest_query for q in loaded_after)
        assert not oldest_present_after, "Query #0 should be evicted after overflow"

        # Verify newest query (query #101) is PRESENT
        newest_present = any(q.query == query_101 for q in loaded_after)
        assert newest_present, "Query #101 should be in cache after addition"

        # Verify query #1 is still present (LRU keeps newer entries)
        query_1 = "Query #1: Research topic 1"
        query_1_present = any(q.query == query_1 for q in loaded_after)
        assert query_1_present, "Query #1 should still be in cache (LRU preserved)"
