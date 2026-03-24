"""Integration tests for US-1065: Phase R research query deduplication cache effectiveness.

Validates:
1. 5 identical queries across stories → 1 Gemini call, 4 cache hits
2. results.tsv shows research_cache_hit_count=4, research_cache_miss_count=1
3. Cached queries execute in <100ms (production Gemini calls take 2000ms+)
"""

from __future__ import annotations

import csv
import os
import shutil
import sys
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "phases"))

from research_query_cache import get_or_research  # noqa: E402

_QUERY = "best practices for autonomous agent loop reliability and resilience"


def _setup() -> tuple[str, str, str]:
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, ".spiral"), exist_ok=True)
    cache = os.path.join(tmpdir, ".spiral", "research_cache.json")
    tsv = os.path.join(tmpdir, "results.tsv")
    return tmpdir, cache, tsv


def _read_tsv_rows(tsv_path: str) -> list[dict[str, Any]]:
    if not os.path.exists(tsv_path):
        return []
    with open(tsv_path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class TestPhaseRDedup5IdenticalQueries:
    """AC1 — 5 identical queries simulate multiple stories sharing the same research topic."""

    def setup_method(self) -> None:
        self.tmpdir, self.cache_path, self.results_tsv = _setup()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_5_identical_queries_1_gemini_call(self) -> None:
        """5 stories all use the same query: only 1 Gemini API call made."""
        client = MagicMock(return_value="gemini research output")

        results = [
            get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)
            for _ in range(5)
        ]

        assert client.call_count == 1, f"Expected 1 Gemini call, got {client.call_count}"
        assert results[0]["cached"] is False, "First call must be a cache miss"
        assert all(r["cached"] is True for r in results[1:]), "Calls 2-5 must be cache hits"
        assert all(r["content"] == "gemini research output" for r in results)

    def test_4_cache_hits_recorded(self) -> None:
        """The 4 cache hits from 5 identical queries are written to results.tsv."""
        client = MagicMock(return_value="research content")

        for _ in range(5):
            get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)

        rows = _read_tsv_rows(self.results_tsv)
        hit_rows = [r for r in rows if r.get("cache_hit") == "true"]
        assert len(hit_rows) == 4, f"Expected 4 cache-hit rows in results.tsv, got {len(hit_rows)}"


class TestPhaseRResultsTsvCacheStats:
    """AC2 — results.tsv shows research_cache_hit_count=4 and research_cache_miss_count=1."""

    def setup_method(self) -> None:
        self.tmpdir, self.cache_path, self.results_tsv = _setup()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_research_cache_hit_count_equals_4(self) -> None:
        """TSV hit count == 4 (rows with cache_hit='true')."""
        client = MagicMock(return_value="data")
        for _ in range(5):
            get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)
        research_cache_hit_count = sum(1 for r in _read_tsv_rows(self.results_tsv) if r.get("cache_hit") == "true")
        assert research_cache_hit_count == 4

    def test_research_cache_miss_count_equals_1(self) -> None:
        """Miss count == 1: Gemini client called exactly once."""
        client = MagicMock(return_value="data")
        for _ in range(5):
            get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)
        research_cache_miss_count = client.call_count
        assert research_cache_miss_count == 1


class TestPhaseRCachedLatencyBenchmark:
    """AC3 — Cached queries must execute in <100ms (Gemini baseline: 2000ms+)."""

    def setup_method(self) -> None:
        self.tmpdir, self.cache_path, self.results_tsv = _setup()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cached_query_executes_under_100ms(self) -> None:
        """A cache hit (JSON file read) completes well under 100ms."""
        client = MagicMock(return_value="cached content")

        # Prime the cache (first call is a miss)
        get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)

        # Measure cached call latency
        start = time.perf_counter()
        result = get_or_research(_QUERY, {}, client, cache_path=self.cache_path, results_tsv=self.results_tsv)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result["cached"] is True
        assert elapsed_ms < 100, f"Cached query took {elapsed_ms:.1f}ms; expected <100ms"
