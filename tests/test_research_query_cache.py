"""Integration tests for lib/phases/research_query_cache.py (US-701).

Verifies:
1. Duplicate queries skip API calls (2 identical calls → 1 API request).
2. Different queries make separate calls.
3. Cache hits are recorded in results.tsv with cache_hit: true.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "phases"))

from research_query_cache import ResearchResult, _compute_hash, get_or_research


# ── _compute_hash tests ───────────────────────────────────────────────────────


class TestComputeHash:
    def test_deterministic(self) -> None:
        h1 = _compute_hash("my query", {"topic": "AI"})
        h2 = _compute_hash("my query", {"topic": "AI"})
        assert h1 == h2

    def test_different_queries_differ(self) -> None:
        h1 = _compute_hash("query A", {})
        h2 = _compute_hash("query B", {})
        assert h1 != h2

    def test_different_context_differs(self) -> None:
        h1 = _compute_hash("query", {"x": 1})
        h2 = _compute_hash("query", {"x": 2})
        assert h1 != h2

    def test_context_order_invariant(self) -> None:
        """Context dict ordering must not affect the hash."""
        h1 = _compute_hash("q", {"a": 1, "b": 2})
        h2 = _compute_hash("q", {"b": 2, "a": 1})
        assert h1 == h2

    def test_returns_sha256_hex(self) -> None:
        h = _compute_hash("q", {})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_context_differs_from_nonempty(self) -> None:
        assert _compute_hash("q", {}) != _compute_hash("q", {"x": 1})


# ── get_or_research tests ─────────────────────────────────────────────────────


class TestGetOrResearch:
    def setup_method(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        os.makedirs(".spiral", exist_ok=True)
        self.cache_path = os.path.join(self.test_dir, ".spiral", "research_cache.json")
        self.results_tsv = os.path.join(self.test_dir, "results.tsv")

    def teardown_method(self) -> None:
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _client(self, return_value: str = "gemini result") -> MagicMock:
        return MagicMock(return_value=return_value)

    # ── AC1: duplicate queries skip API calls ─────────────────────────────────

    def test_cache_miss_calls_gemini_once(self) -> None:
        """First call on an empty cache hits Gemini exactly once."""
        client = self._client("content A")
        result = get_or_research(
            "spiral query", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        assert result["content"] == "content A"
        assert result["cached"] is False
        client.assert_called_once_with("spiral query")

    def test_duplicate_queries_skip_api_call(self) -> None:
        """Two identical (query, context) calls → only 1 Gemini API request."""
        client = self._client("cached content")

        r1 = get_or_research(
            "identical query", {"ctx": "value"}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        r2 = get_or_research(
            "identical query", {"ctx": "value"}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )

        assert client.call_count == 1, (
            f"Expected 1 Gemini API call, got {client.call_count}"
        )
        assert r1["content"] == "cached content"
        assert r2["content"] == "cached content"
        assert r1["cached"] is False
        assert r2["cached"] is True

    def test_triple_duplicate_queries_skip_api_call(self) -> None:
        """Three identical calls → still only 1 Gemini API request."""
        client = self._client("result")
        for _ in range(3):
            get_or_research(
                "same query", {}, client,
                cache_path=self.cache_path, results_tsv=self.results_tsv,
            )
        assert client.call_count == 1

    # ── AC2: different queries make separate calls ────────────────────────────

    def test_different_queries_make_separate_calls(self) -> None:
        """Different queries each trigger their own Gemini call."""
        client: MagicMock = MagicMock(side_effect=["result A", "result B"])

        r1 = get_or_research(
            "query A", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        r2 = get_or_research(
            "query B", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )

        assert client.call_count == 2
        assert r1["content"] == "result A"
        assert r2["content"] == "result B"
        assert r1["cached"] is False
        assert r2["cached"] is False

    def test_same_query_different_context_makes_separate_calls(self) -> None:
        """Same query with different context dict → separate cache entries."""
        client: MagicMock = MagicMock(side_effect=["res 1", "res 2"])

        get_or_research(
            "q", {"x": 1}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        get_or_research(
            "q", {"x": 2}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )

        assert client.call_count == 2

    # ── AC3: cache hits recorded in results.tsv ───────────────────────────────

    def test_cache_hit_recorded_in_results_tsv(self) -> None:
        """Cache hit appends a row to results.tsv with cache_hit=true."""
        client = self._client("content")

        # First call: miss — no TSV row written
        get_or_research(
            "my query", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        # Second call: hit — TSV row written
        get_or_research(
            "my query", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )

        assert os.path.exists(self.results_tsv), "results.tsv must be created"
        with open(self.results_tsv, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        assert len(rows) == 1, f"Expected 1 cache-hit row, found {len(rows)}"
        assert rows[0]["cache_hit"] == "true"

    def test_multiple_cache_hits_recorded(self) -> None:
        """Each cache hit appends one row; 3 hits → 3 rows."""
        client = self._client("content")

        for _ in range(4):  # 1 miss + 3 hits
            get_or_research(
                "repeated query", {}, client,
                cache_path=self.cache_path, results_tsv=self.results_tsv,
            )

        with open(self.results_tsv, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        assert len(rows) == 3
        assert all(r["cache_hit"] == "true" for r in rows)

    def test_no_tsv_row_on_cache_miss(self) -> None:
        """A cache miss must NOT write to results.tsv."""
        client = self._client("content")
        get_or_research(
            "unique query", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        # Either file doesn't exist or has no data rows
        if os.path.exists(self.results_tsv):
            with open(self.results_tsv, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                rows = list(reader)
            assert len(rows) == 0, "No rows expected on a cache miss"

    # ── Cache entry field tests ───────────────────────────────────────────────

    def test_cache_entry_has_required_fields(self) -> None:
        """Cache entry must store content, timestamp, source, and usage_count."""
        client = self._client("research content")
        get_or_research(
            "query", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )

        with open(self.cache_path, encoding="utf-8") as f:
            cache: dict[str, Any] = json.load(f)

        assert len(cache) == 1
        entry = list(cache.values())[0]
        assert entry["content"] == "research content"
        assert "timestamp" in entry
        assert entry["source"] == "gemini"
        assert entry["usage_count"] == 1

    def test_usage_count_increments_on_each_hit(self) -> None:
        """usage_count increments for every cache hit."""
        client = self._client("content")

        for _ in range(4):  # 1 miss + 3 hits
            get_or_research(
                "q", {}, client,
                cache_path=self.cache_path, results_tsv=self.results_tsv,
            )

        with open(self.cache_path, encoding="utf-8") as f:
            cache: dict[str, Any] = json.load(f)
        entry = list(cache.values())[0]
        assert entry["usage_count"] == 4

    def test_query_hash_in_result(self) -> None:
        """Returned ResearchResult includes the SHA256 query_hash."""
        client = self._client("content")
        result = get_or_research(
            "q", {"k": "v"}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        expected = _compute_hash("q", {"k": "v"})
        assert result["query_hash"] == expected

    # ── Edge case tests ───────────────────────────────────────────────────────

    def test_missing_cache_dir_handled_gracefully(self) -> None:
        """get_or_research creates cache dir if it doesn't exist."""
        deep_cache = os.path.join(self.test_dir, "deep", "nested", "cache.json")
        client = self._client("result")
        result = get_or_research(
            "q", {}, client,
            cache_path=deep_cache, results_tsv=self.results_tsv,
        )
        assert result["content"] == "result"
        assert os.path.exists(deep_cache)

    def test_corrupt_cache_falls_back_to_api(self) -> None:
        """Corrupt cache JSON is treated as a miss — API is called."""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            f.write("not valid json {{{{")
        client = self._client("fresh result")
        result = get_or_research(
            "q", {}, client,
            cache_path=self.cache_path, results_tsv=self.results_tsv,
        )
        assert result["content"] == "fresh result"
        assert result["cached"] is False
        client.assert_called_once()
