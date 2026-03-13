"""Tests for lib/research_cache.py — URL-level research cache."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from research_cache import (
    _cache_key,
    _cache_path,
    cache_inject_context,
    cache_list_valid,
    cache_lookup,
    cache_prune,
    cache_store,
)


# ── _cache_key tests ─────────────────────────────────────────────────────────


class TestCacheKey:
    def test_deterministic(self):
        assert _cache_key("https://example.com") == _cache_key("https://example.com")

    def test_strips_whitespace(self):
        assert _cache_key("  https://example.com  ") == _cache_key("https://example.com")

    def test_strips_trailing_slash(self):
        assert _cache_key("https://example.com/") == _cache_key("https://example.com")

    def test_different_urls_different_keys(self):
        assert _cache_key("https://a.com") != _cache_key("https://b.com")

    def test_returns_hex_string(self):
        key = _cache_key("https://example.com")
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)


# ── cache_store tests ─────────────────────────────────────────────────────────


class TestCacheStore:
    def test_creates_cache_dir(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://example.com", "hello world")
        assert os.path.isdir(cache_dir)

    def test_creates_json_file(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://example.com", "content here")
        assert os.path.exists(path)
        assert path.endswith(".json")

    def test_file_content_structure(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://example.com", "test content")
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        assert entry["url"] == "https://example.com"
        assert entry["content"] == "test content"
        assert "fetched_ts" in entry
        assert isinstance(entry["fetched_ts"], float)

    def test_filename_is_md5(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://example.com", "x")
        fname = os.path.basename(path)
        expected = _cache_key("https://example.com") + ".json"
        assert fname == expected


# ── cache_lookup tests ────────────────────────────────────────────────────────


class TestCacheLookup:
    def test_returns_content_within_ttl(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://example.com", "cached content")
        result = cache_lookup(cache_dir, "https://example.com", ttl_hours=24)
        assert result == "cached content"

    def test_returns_none_for_missing_url(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        result = cache_lookup(cache_dir, "https://missing.com", ttl_hours=24)
        assert result is None

    def test_returns_none_when_expired(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://example.com", "old content")
        # Manually set fetched_ts to 25 hours ago
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        result = cache_lookup(cache_dir, "https://example.com", ttl_hours=24)
        assert result is None

    def test_returns_none_when_ttl_zero(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://example.com", "content")
        result = cache_lookup(cache_dir, "https://example.com", ttl_hours=0)
        assert result is None

    def test_returns_none_for_nonexistent_dir(self, tmp_path):
        result = cache_lookup(str(tmp_path / "nope"), "https://x.com", ttl_hours=24)
        assert result is None


# ── cache_prune tests ─────────────────────────────────────────────────────────


class TestCachePrune:
    def test_prunes_expired_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://old.com", "old")
        # Make it expired
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        count = cache_prune(cache_dir, ttl_hours=24)
        assert count == 1
        assert not os.path.exists(path)

    def test_keeps_valid_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://fresh.com", "fresh")
        count = cache_prune(cache_dir, ttl_hours=24)
        assert count == 0
        assert os.path.exists(path)

    def test_prunes_corrupt_json(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir)
        corrupt_path = os.path.join(cache_dir, "corrupt.json")
        with open(corrupt_path, "w") as f:
            f.write("not valid json{{{")
        count = cache_prune(cache_dir, ttl_hours=24)
        assert count == 1
        assert not os.path.exists(corrupt_path)

    def test_returns_zero_for_missing_dir(self, tmp_path):
        count = cache_prune(str(tmp_path / "nope"), ttl_hours=24)
        assert count == 0

    def test_returns_zero_when_ttl_zero(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://example.com", "x")
        count = cache_prune(cache_dir, ttl_hours=0)
        assert count == 0

    def test_ignores_non_json_files(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir)
        readme = os.path.join(cache_dir, "README.md")
        with open(readme, "w") as f:
            f.write("not a cache file")
        count = cache_prune(cache_dir, ttl_hours=24)
        assert count == 0
        assert os.path.exists(readme)


# ── cache_list_valid tests ────────────────────────────────────────────────────


class TestCacheListValid:
    def test_returns_valid_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://a.com", "content a")
        cache_store(cache_dir, "https://b.com", "content b")
        entries = cache_list_valid(cache_dir, ttl_hours=24)
        assert len(entries) == 2
        urls = {e["url"] for e in entries}
        assert urls == {"https://a.com", "https://b.com"}

    def test_excludes_expired(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://old.com", "old")
        cache_store(cache_dir, "https://fresh.com", "fresh")
        # Expire one
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        entries = cache_list_valid(cache_dir, ttl_hours=24)
        assert len(entries) == 1
        assert entries[0]["url"] == "https://fresh.com"

    def test_returns_empty_when_disabled(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://a.com", "x")
        entries = cache_list_valid(cache_dir, ttl_hours=0)
        assert entries == []

    def test_returns_empty_for_missing_dir(self, tmp_path):
        entries = cache_list_valid(str(tmp_path / "nope"), ttl_hours=24)
        assert entries == []


# ── cache_inject_context tests ────────────────────────────────────────────────


class TestCacheInjectContext:
    def test_returns_empty_when_disabled(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://a.com", "content")
        result = cache_inject_context(cache_dir, ttl_hours=0)
        assert result == ""

    def test_returns_empty_for_empty_cache(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        os.makedirs(cache_dir)
        result = cache_inject_context(cache_dir, ttl_hours=24)
        assert result == ""

    def test_returns_context_with_cached_content(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://docs.example.com", "API documentation here")
        result = cache_inject_context(cache_dir, ttl_hours=24)
        assert "Pre-Fetched URL Cache" in result
        assert "https://docs.example.com" in result
        assert "API documentation here" in result
        assert "Do NOT re-fetch" in result

    def test_excludes_expired_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        path = cache_store(cache_dir, "https://old.com", "old content")
        cache_store(cache_dir, "https://fresh.com", "fresh content")
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (25 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        result = cache_inject_context(cache_dir, ttl_hours=24)
        assert "fresh content" in result
        assert "old content" not in result

    def test_returns_empty_for_missing_dir(self, tmp_path):
        result = cache_inject_context(str(tmp_path / "nope"), ttl_hours=24)
        assert result == ""


# ── CLI integration tests ────────────────────────────────────────────────────


class TestCLI:
    def test_store_and_lookup(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        url = "https://example.com/api"
        cache_store(cache_dir, url, "response body")
        result = cache_lookup(cache_dir, url, ttl_hours=24)
        assert result == "response body"

    def test_store_prune_lookup_cycle(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        # Store, then expire, then prune, then lookup
        path = cache_store(cache_dir, "https://example.com", "data")
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
        entry["fetched_ts"] = time.time() - (48 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        pruned = cache_prune(cache_dir, ttl_hours=24)
        assert pruned == 1
        result = cache_lookup(cache_dir, "https://example.com", ttl_hours=24)
        assert result is None

    def test_overwrite_existing_entry(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        cache_store(cache_dir, "https://example.com", "version 1")
        cache_store(cache_dir, "https://example.com", "version 2")
        result = cache_lookup(cache_dir, "https://example.com", ttl_hours=24)
        assert result == "version 2"
