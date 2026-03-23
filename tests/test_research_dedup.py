"""Integration tests for lib/research_dedup.py — query similarity deduplication.

Tests verify:
- query_similarity() returns 1.0 for identical strings, ~0.0 for orthogonal
- find_cached_response() reuses cached entry when similarity >= threshold
- find_cached_response() returns None on cache miss / below threshold
- Cost savings tracking: dedup hit skips redundant Gemini call
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from research_dedup import find_cached_response, query_similarity

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_cache(tmp_path: Any, entries: list[dict[str, Any]]) -> str:
    """Write a research_cache.json with given entries and return its path."""
    cache: dict[str, Any] = {}
    for i, entry in enumerate(entries):
        key = f"key{i:04d}"
        cache[key] = {
            "topic": entry["topic"],
            "result": entry.get("result", {"gemini_research": entry.get("content", "")}),
            "fetched_ts": entry.get("fetched_ts", time.time()),
            "expires_at": entry.get("expires_at", time.time() + 86400),
        }
    cache_file = str(tmp_path / "research_cache.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    return cache_file


# ── TestQuerySimilarity ───────────────────────────────────────────────────────


class TestQuerySimilarity:
    def test_identical_strings_return_one(self) -> None:
        sim = query_similarity("AI safety research 2025", "AI safety research 2025")
        assert sim == 1.0

    def test_empty_strings_return_zero(self) -> None:
        assert query_similarity("", "some query") == 0.0
        assert query_similarity("some query", "") == 0.0
        assert query_similarity("", "") == 0.0

    def test_similar_queries_return_high_score(self) -> None:
        q1 = "best practices for Python testing with pytest"
        q2 = "Python testing best practices pytest guide"
        sim = query_similarity(q1, q2)
        assert sim >= 0.5, f"Expected high similarity, got {sim}"

    def test_dissimilar_queries_return_low_score(self) -> None:
        q1 = "machine learning neural networks deep learning"
        q2 = "French cuisine recipe ingredients cooking"
        sim = query_similarity(q1, q2)
        assert sim <= 0.3, f"Expected low similarity, got {sim}"

    def test_symmetric(self) -> None:
        q1 = "spiral autonomous development tool"
        q2 = "autonomous development spiral PRD"
        assert abs(query_similarity(q1, q2) - query_similarity(q2, q1)) < 1e-6

    def test_returns_float_in_unit_interval(self) -> None:
        sim = query_similarity("hello world", "world hello")
        assert 0.0 <= sim <= 1.0


# ── TestFindCachedResponse ────────────────────────────────────────────────────


class TestFindCachedResponse:
    def test_no_cache_file_returns_none(self, tmp_path: Any) -> None:
        result = find_cached_response("any query", str(tmp_path / "missing.json"), 0.85)
        assert result is None

    def test_empty_cache_returns_none(self, tmp_path: Any) -> None:
        cache_file = str(tmp_path / "research_cache.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({}, f)
        result = find_cached_response("any query", cache_file, 0.85)
        assert result is None

    def test_high_similarity_query_returns_cached_result(self, tmp_path: Any) -> None:
        """A near-duplicate query should reuse the cached research response."""
        cached_content = {"gemini_research": "SPIRAL improves dev velocity via PRD automation"}
        cache_file = _make_cache(
            tmp_path,
            [{"topic": "SPIRAL autonomous PRD development loop", "result": cached_content}],
        )
        # Near-duplicate query — similar tokens, slightly different wording
        result = find_cached_response(
            "SPIRAL PRD autonomous development loop",
            cache_file,
            threshold=0.5,  # lower threshold to ensure hit with TF-IDF
        )
        assert result is not None, "Expected cache hit for high-similarity query"
        assert result == cached_content

    def test_low_similarity_query_returns_none(self, tmp_path: Any) -> None:
        """A completely different query should NOT reuse the cached response."""
        cache_file = _make_cache(
            tmp_path,
            [{"topic": "machine learning neural network architectures", "result": {"x": 1}}],
        )
        result = find_cached_response(
            "French cuisine bistro recipes Paris",
            cache_file,
            threshold=0.85,
        )
        assert result is None

    def test_corrupt_cache_returns_none(self, tmp_path: Any) -> None:
        cache_file = str(tmp_path / "research_cache.json")
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("not valid json{{{{")
        result = find_cached_response("any query", cache_file, 0.85)
        assert result is None

    def test_best_match_selected_when_multiple_entries(self, tmp_path: Any) -> None:
        """find_cached_response returns the highest-similarity match above threshold."""
        result_a = {"gemini_research": "result A — general AI"}
        result_b = {"gemini_research": "result B — SPIRAL PRD loop"}
        cache_file = _make_cache(
            tmp_path,
            [
                {"topic": "general AI news", "result": result_a},
                {"topic": "SPIRAL PRD autonomous loop iteration", "result": result_b},
            ],
        )
        result = find_cached_response(
            "SPIRAL loop PRD autonomous iteration",
            cache_file,
            threshold=0.4,
        )
        assert result is not None
        # result_b has higher similarity; expect it to win
        assert result == result_b


# ── TestResearchDedupCostTracking ─────────────────────────────────────────────


class TestResearchDedupCostTracking:
    def test_dedup_hit_avoids_gemini_call(self, tmp_path: Any) -> None:
        """Simulate Phase R: dedup hit should prevent spending on a Gemini call."""
        cached_content = {"gemini_research": "cached research on SPIRAL story phases"}
        cache_file = _make_cache(
            tmp_path,
            [{"topic": "SPIRAL story phase implementation research", "result": cached_content}],
        )

        # Track whether a mock Gemini call is made
        gemini_called = {"value": False}

        def mock_gemini_call(query: str) -> str:
            gemini_called["value"] = True
            return "fresh gemini response"

        # Simulate Phase R logic: check dedup first, call Gemini only on miss
        query = "SPIRAL story phase implementation"
        hit = find_cached_response(query, cache_file, threshold=0.4)
        if hit is None:
            mock_gemini_call(query)

        assert hit is not None, "Expected dedup cache hit"
        assert not gemini_called["value"], "Gemini should NOT be called on dedup hit"
        assert hit == cached_content

    def test_dedup_miss_allows_gemini_call(self, tmp_path: Any) -> None:
        """On a dedup miss, Phase R should proceed to call Gemini normally."""
        cache_file = _make_cache(
            tmp_path,
            [{"topic": "French cooking and pastry recipes", "result": {"gemini_research": "x"}}],
        )

        gemini_called = {"value": False}

        def mock_gemini_call(query: str) -> str:
            gemini_called["value"] = True
            return "fresh AI research"

        query = "quantum computing error correction algorithms"
        hit = find_cached_response(query, cache_file, threshold=0.85)
        if hit is None:
            mock_gemini_call(query)

        assert hit is None, "Expected dedup cache miss"
        assert gemini_called["value"], "Gemini SHOULD be called on dedup miss"


# ── TestUS773AcceptanceCriteria ──────────────────────────────────────────────


class TestUS773AcceptanceCriteria:
    """US-773: Verify default threshold is 0.90 and paraphrased/novel query behavior."""

    def test_default_threshold_is_090(self) -> None:
        """AC2: Verify default threshold is >0.90 per US-773."""
        from research_dedup import SPIRAL_RESEARCH_DEDUP_THRESHOLD

        assert SPIRAL_RESEARCH_DEDUP_THRESHOLD == 0.90, (
            f"AC2 requires default threshold of 0.90, got {SPIRAL_RESEARCH_DEDUP_THRESHOLD}"
        )

    def test_paraphrased_query_cache_hit_with_default_threshold(self, tmp_path: Any) -> None:
        """AC4: Paraphrased query should return cached result with default 0.90 threshold."""
        # Original query about SPIRAL PRD development
        original = "SPIRAL autonomous PRD research implementation loop"
        # Near-identical paraphrased version (same core meaning, minor wording changes)
        paraphrased = "SPIRAL PRD autonomous research implementation loop"

        cached_content = {"gemini_research": "SPIRAL loop implementation details"}
        cache_file = _make_cache(
            tmp_path,
            [{"topic": original, "result": cached_content}],
        )

        # Use default threshold (should be 0.90)
        result = find_cached_response(paraphrased, cache_file)
        assert result is not None, "AC4: Near-identical query should hit cache with default 0.90 threshold"
        assert result == cached_content

    def test_novel_query_cache_miss_with_default_threshold(self, tmp_path: Any) -> None:
        """AC4: Novel query should NOT return cached result (miss with default threshold)."""
        cached_content = {"gemini_research": "machine learning research findings"}
        cache_file = _make_cache(
            tmp_path,
            [{"topic": "machine learning neural networks deep learning", "result": cached_content}],
        )

        # Completely different query
        result = find_cached_response(
            "French cuisine bistro restaurant cooking",
            cache_file,
        )
        assert result is None, "AC4: Novel query should miss cache with default threshold"
