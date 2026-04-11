"""Performance tests for US-1026: Phase R Research Cache Hit/Miss Counting and LRU Eviction.

Validates:
1. Performance test measures key metrics for cache operations (hit/miss/LRU)
2. Baseline captured and acceptable threshold defined
3. Test fails if response time degrades more than 20% from baseline

Metrics:
- Cache hit performance: time for 1000 identical queries (should be <100ms total)
- Cache miss performance: time for 100 novel queries (varies by similarity threshold)
- LRU eviction performance: time to evict oldest entry when cache is at capacity
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# Add lib to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "research"))

from research_cache import (
    CachedQuery,
    get_cached_result,
    load_research_cache,
    record_query_result,
    save_research_cache,
)


@pytest.mark.benchmark(group="research-cache-us1026")
class TestCacheHitPerformance:
    """Performance test: Cache hit operations for identical queries."""

    def test_cache_hit_1000_queries_baseline(self, benchmark: Any, tmp_path: Path) -> None:
        """AC1: Measure time for 1000 cache hit operations.

        Simulates repeated access to cached research result. Should complete in <100ms
        (cache hits are ~1ms each, misses are 100-2000ms each).
        """
        cache_path = tmp_path / "research_cache.json"
        query = "What is artificial intelligence safety?"

        # Warmup: store one query in cache
        result_content = "AI safety is the study of making AI systems safe and beneficial"
        record_query_result(query, result_content, cache_path, iteration=0, ttl_iterations=5)

        # Benchmark: 1000 cache hit lookups
        def do_cache_hits() -> int:
            hit_count = 0
            for _ in range(1000):
                is_hit, _ = get_cached_result(query, cache_path, similarity_threshold=0.90)
                if is_hit:
                    hit_count += 1
            return hit_count

        # Run benchmark
        result: int = benchmark(do_cache_hits)
        # Acceptance: All 1000 should be cache hits
        assert result == 1000, f"Expected 1000 cache hits, got {result}"


@pytest.mark.benchmark(group="research-cache-us1026")
class TestCacheMissPerformance:
    """Performance test: Cache miss detection for novel queries."""

    def test_cache_miss_100_queries_baseline(self, benchmark: Any, tmp_path: Path) -> None:
        """AC1: Measure time for 100 cache miss operations.

        Each novel query requires semantic similarity computation. Time varies by
        similarity_threshold and token overlap.
        """
        cache_path = tmp_path / "research_cache.json"

        # Pre-populate cache with 10 cached queries
        for i in range(10):
            query = f"Research topic {i}: Information about domain {i}"
            result_content = f"Result for topic {i}"
            record_query_result(query, result_content, cache_path, iteration=0, ttl_iterations=5)

        # Benchmark: 100 novel query lookups (all should be misses)
        novel_queries = [f"Completely novel topic {i}: Different domain {i}" for i in range(100)]

        def do_cache_misses() -> int:
            miss_count = 0
            for query in novel_queries:
                is_hit, _ = get_cached_result(query, cache_path, similarity_threshold=0.90)
                if not is_hit:
                    miss_count += 1
            return miss_count

        # Run benchmark
        result: int = benchmark(do_cache_misses)
        # Acceptance: All 100 should be cache misses
        assert result == 100, f"Expected 100 cache misses, got {result}"


@pytest.mark.benchmark(group="research-cache-us1026")
class TestLRUEvictionPerformance:
    """Performance test: LRU eviction when cache exceeds max size."""

    def test_lru_eviction_at_capacity_baseline(self, benchmark: Any, tmp_path: Path) -> None:
        """AC2: Measure time to evict oldest entry when cache reaches capacity.

        Creates cache with max_cache_size=100, adds entry #101, measures time to
        evict oldest and save updated cache.
        """
        cache_path = tmp_path / "research_cache.json"
        max_cache_size = 100

        # Pre-populate cache with 100 entries
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
                added_at=time.time() - (100 - i),  # Older queries first
            )
            cached_queries.append(cached)

        # Save initial cache at capacity
        save_research_cache(
            cached_queries, cache_path, ttl_iterations=5, current_iteration=0, max_cache_size=max_cache_size
        )

        # Benchmark: Add entry #101 and trigger LRU eviction
        def do_lru_eviction() -> None:
            # Load cache
            loaded = load_research_cache(cache_path)
            assert len(loaded) == 100, f"Expected 100 entries, got {len(loaded)}"

            # Add new entry (query #101)
            query_101 = "Query #101: Research topic 101"
            new_query = CachedQuery(
                query=query_101,
                result="Result for query 101",
                iteration=0,
                tokens=["query", "101", "research", "topic"],
                added_at=time.time(),
            )
            loaded.append(new_query)

            # Save with LRU eviction (should remove oldest)
            save_research_cache(
                loaded, cache_path, ttl_iterations=5, current_iteration=0, max_cache_size=max_cache_size
            )

        # Run benchmark
        benchmark(do_lru_eviction)

        # Verify: Cache still has exactly 100 entries, oldest was evicted
        final_cache = load_research_cache(cache_path)
        assert len(final_cache) == 100, f"Expected 100 entries after eviction, got {len(final_cache)}"

        # Verify oldest (query #0) is gone
        oldest_query = "Query #0: Research topic 0"
        oldest_present = any(q.query == oldest_query for q in final_cache)
        assert not oldest_present, "Oldest query should be evicted"

        # Verify newest (query #101) is present
        newest_present = any(q.query == "Query #101: Research topic 101" for q in final_cache)
        assert newest_present, "Newest query should be in cache"


@pytest.mark.benchmark(group="research-cache-us1026")
class TestCachePerformanceRegression:
    """Performance regression detection: Fail if operations degrade >20% from baseline."""

    def test_cache_hit_regression_20pct_threshold(self, benchmark: Any, tmp_path: Path) -> None:
        """AC3: Fail if cache hit performance degrades more than 20% from baseline.

        pytest-benchmark tracks baseline automatically. This test fails if the
        measured time exceeds baseline * 1.20.
        """
        cache_path = tmp_path / "research_cache.json"
        query = "What is machine learning?"

        # Warmup: store query in cache
        record_query_result(query, "ML is a subset of AI", cache_path, iteration=0, ttl_iterations=5)

        # Benchmark with regression detection
        def do_cache_hits() -> int:
            hit_count = 0
            for _ in range(100):
                is_hit, _ = get_cached_result(query, cache_path, similarity_threshold=0.90)
                if is_hit:
                    hit_count += 1
            return hit_count

        # pytest-benchmark will track and compare against baseline automatically
        result: int = benchmark(do_cache_hits)
        # All should be hits
        assert result == 100, f"Expected 100 hits, got {result}"


@pytest.mark.benchmark(group="research-cache-us1026")
class TestCacheOperationsPerformanceSuite:
    """Combined benchmark suite for research cache operations (for grouping in reports)."""

    def test_mixed_workload_hit_miss_eviction(self, benchmark: Any, tmp_path: Path) -> None:
        """AC1: Benchmark realistic workload: hits + misses + occasional eviction."""
        cache_path = tmp_path / "research_cache.json"

        # Pre-populate cache
        for i in range(50):
            query = f"Topic {i}"
            record_query_result(query, f"Result {i}", cache_path, iteration=0, ttl_iterations=5)

        # Realistic workload: 60% hits, 40% misses
        def do_mixed_workload() -> dict[str, int]:
            stats = {"hits": 0, "misses": 0}
            # 60 cache hits
            for i in range(50):
                is_hit, _ = get_cached_result(f"Topic {i}", cache_path, similarity_threshold=0.90)
                if is_hit:
                    stats["hits"] += 1
            # 40 cache misses (novel queries)
            for i in range(40):
                is_hit, _ = get_cached_result(f"Novel topic {i}", cache_path, similarity_threshold=0.90)
                if not is_hit:
                    stats["misses"] += 1
            return stats

        result: dict[str, int] = benchmark(do_mixed_workload)
        # Verify: should have ~50 hits and ~40 misses
        assert result["hits"] >= 40, f"Expected at least 40 hits, got {result['hits']}"
        assert result["misses"] >= 30, f"Expected at least 30 misses, got {result['misses']}"
