"""Tests for lib/query_embed_cache.py — semantic query cache."""

from __future__ import annotations

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from query_embed_cache import (
    _cosine_sim,
    _query_key,
    query_list_valid,
    query_lookup,
    query_prune,
    query_store,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_VEC_A = np.array([1.0, 0.0, 0.0], dtype=np.float32)
_VEC_B = np.array([0.9, 0.1, 0.0], dtype=np.float32)  # highly similar to A
_VEC_C = np.array([0.0, 1.0, 0.0], dtype=np.float32)  # orthogonal to A (sim=0)


def _fake_model(vec: np.ndarray):
    """Return a fake SentenceTransformer that always encodes to *vec*."""
    model = MagicMock()
    model.encode.return_value = vec.reshape(1, -1)
    return model


# ── _query_key ────────────────────────────────────────────────────────────────


class TestQueryKey:
    def test_deterministic(self):
        assert _query_key("hello world") == _query_key("hello world")

    def test_strips_whitespace(self):
        assert _query_key("  hello  ") == _query_key("hello")

    def test_different_queries_different_keys(self):
        assert _query_key("query one") != _query_key("query two")

    def test_returns_sha256_hex(self):
        key = _query_key("test query")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# ── _cosine_sim ───────────────────────────────────────────────────────────────


class TestCosineSim:
    def test_identical_vectors_return_one(self):
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert abs(_cosine_sim(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_return_zero(self):
        assert abs(_cosine_sim(_VEC_A, _VEC_C)) < 1e-6

    def test_similar_vectors_above_threshold(self):
        sim = _cosine_sim(_VEC_A, _VEC_B)
        assert sim > 0.9

    def test_zero_vector_returns_zero(self):
        zero = np.zeros(3, dtype=np.float32)
        assert _cosine_sim(zero, _VEC_A) == 0.0
        assert _cosine_sim(_VEC_A, zero) == 0.0


# ── query_store ───────────────────────────────────────────────────────────────


class TestQueryStore:
    def test_creates_json_and_npy_files(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            path = query_store(cache_dir, "research query", "result content")
        assert path.endswith(".json")
        assert os.path.exists(path)
        key = _query_key("research query")
        assert os.path.exists(os.path.join(cache_dir, f"{key}.npy"))

    def test_json_contains_expected_fields(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            path = query_store(cache_dir, "my query", "cached result")
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        assert entry["query"] == "my query"
        assert entry["content"] == "cached result"
        assert "fetched_ts" in entry

    def test_npy_loads_as_float32_array(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "embed test", "content")
        key = _query_key("embed test")
        emb = np.load(os.path.join(cache_dir, f"{key}.npy"))
        assert emb.dtype == np.float32
        assert emb.ndim == 1

    def test_overwrites_existing_entry(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "q", "version 1")
            query_store(cache_dir, "q", "version 2")
            result = query_lookup(cache_dir, "q", threshold=1.0)
        assert result == "version 2"


# ── query_lookup ──────────────────────────────────────────────────────────────


class TestQueryLookup:
    def test_exact_match_returns_content(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "exact query", "exact result")
            result = query_lookup(cache_dir, "exact query", threshold=1.0)
        assert result == "exact result"

    def test_exact_match_miss_returns_none(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "stored query", "content")
            result = query_lookup(cache_dir, "different query", threshold=1.0)
        assert result is None

    def test_threshold_one_skips_embedding(self, tmp_path):
        """threshold=1.0 must not call model.encode (uses exact key match)."""
        cache_dir = str(tmp_path / "cache")
        mock_model = _fake_model(_VEC_A)
        with patch("query_embed_cache._get_model", return_value=mock_model):
            query_store(cache_dir, "q", "content")
        # Now look up with threshold=1.0 using a fresh mock
        mock_model2 = _fake_model(_VEC_A)
        with patch("query_embed_cache._get_model", return_value=mock_model2):
            query_lookup(cache_dir, "q", threshold=1.0)
        # encode should NOT be called for the lookup (exact key match shortcut)
        mock_model2.encode.assert_not_called()

    def test_similarity_lookup_finds_similar_query(self, tmp_path):
        """A vector close to the stored one should hit above threshold=0.9."""
        cache_dir = str(tmp_path / "cache")
        # Store with vec_a embedding
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "original query", "cached content")
        # Lookup with a highly similar embedding (vec_b, sim ~0.99)
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_B)):
            result = query_lookup(cache_dir, "similar query", threshold=0.9, ttl_hours=24)
        assert result == "cached content"

    def test_below_threshold_returns_none(self, tmp_path):
        """An orthogonal query (sim=0) must not hit with threshold=0.9."""
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "stored query", "content")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_C)):
            result = query_lookup(cache_dir, "orthogonal query", threshold=0.9, ttl_hours=24)
        assert result is None

    def test_returns_none_when_ttl_zero(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "q", "content")
            result = query_lookup(cache_dir, "q", threshold=1.0, ttl_hours=0)
        assert result is None

    def test_returns_none_for_missing_dir(self, tmp_path):
        result = query_lookup(str(tmp_path / "nope"), "query", threshold=0.9)
        assert result is None

    def test_returns_none_when_expired(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            path = query_store(cache_dir, "q", "content")
        # Backdate the fetched_ts to expire the entry
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            result = query_lookup(cache_dir, "q", threshold=1.0, ttl_hours=24)
        assert result is None


# ── query_prune ───────────────────────────────────────────────────────────────


class TestQueryPrune:
    def test_prunes_expired_json_and_npy(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            path = query_store(cache_dir, "old query", "content")
        # Expire the entry
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)

        key = _query_key("old query")
        npy_path = os.path.join(cache_dir, f"{key}.npy")
        assert os.path.exists(npy_path)

        count = query_prune(cache_dir, ttl_hours=24)
        assert count == 1
        assert not os.path.exists(path)
        assert not os.path.exists(npy_path)

    def test_keeps_valid_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            path = query_store(cache_dir, "fresh query", "content")
        count = query_prune(cache_dir, ttl_hours=24)
        assert count == 0
        assert os.path.exists(path)

    def test_returns_zero_for_missing_dir(self, tmp_path):
        assert query_prune(str(tmp_path / "nope"), ttl_hours=24) == 0

    def test_returns_zero_when_ttl_zero(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "q", "content")
        assert query_prune(cache_dir, ttl_hours=0) == 0

    def test_prunes_corrupt_json(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir)
        corrupt = os.path.join(cache_dir, "deadbeef.json")
        with open(corrupt, "w") as f:
            f.write("not valid json{{{")
        count = query_prune(cache_dir, ttl_hours=24)
        assert count == 1
        assert not os.path.exists(corrupt)


# ── query_list_valid ──────────────────────────────────────────────────────────


class TestQueryListValid:
    def test_returns_valid_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "query one", "c1")
            query_store(cache_dir, "query two", "c2")
        entries = query_list_valid(cache_dir, ttl_hours=24)
        assert len(entries) == 2
        queries = {e["query"] for e in entries}
        assert queries == {"query one", "query two"}

    def test_excludes_entries_without_npy(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir)
        # Write a .json without a paired .npy (e.g., URL cache entry)
        url_json = os.path.join(cache_dir, "abcd1234.json")
        with open(url_json, "w") as f:
            json.dump({"query": "url entry", "fetched_ts": time.time(), "content": "x"}, f)
        entries = query_list_valid(cache_dir, ttl_hours=24)
        assert entries == []

    def test_returns_empty_when_disabled(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        with patch("query_embed_cache._get_model", return_value=_fake_model(_VEC_A)):
            query_store(cache_dir, "q", "content")
        assert query_list_valid(cache_dir, ttl_hours=0) == []

    def test_returns_empty_for_missing_dir(self, tmp_path):
        assert query_list_valid(str(tmp_path / "nope"), ttl_hours=24) == []
