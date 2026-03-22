"""Tests for lib/phases/research_cache.py — Topic-level research cache (US-519)."""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import importlib.util

_rc_path = os.path.join(os.path.dirname(__file__), "..", "lib", "phases", "research_cache.py")
_spec = importlib.util.spec_from_file_location("phases_research_cache", _rc_path)
assert _spec and _spec.loader
_rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rc)

cache_clear_expired = _rc.cache_clear_expired
cache_init = _rc.cache_init
cache_research_result = _rc.cache_research_result
lookup_cached_research = _rc.lookup_cached_research


class TestTopicLevelCache:
    """Tests for topic-level research cache."""

    def setup_method(self) -> None:
        """Create temporary .spiral directory for each test."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        os.makedirs(".spiral", exist_ok=True)

    def teardown_method(self) -> None:
        """Clean up temporary directory after each test."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cache_miss_returns_none(self) -> None:
        """Cache miss: looking up non-existent topic returns None."""
        result = lookup_cached_research("nonexistent_topic")
        assert result is None

    def test_cache_hit_returns_dict(self) -> None:
        """Cache hit: stored result is returned unchanged."""
        topic = "test_topic"
        stored_result = {"data": "value", "count": 42}

        cache_research_result(topic, stored_result)
        retrieved = lookup_cached_research(topic)

        assert retrieved == stored_result

    def test_expired_entry_returns_none(self) -> None:
        """Expired entry: lookup returns None for entries older than 24 hours."""
        topic = "old_topic"
        result = {"old": "data"}

        cache_research_result(topic, result)

        # Manually corrupt the cache to set an old timestamp
        cache_file = Path(".spiral") / "research_cache.json"
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)

        # Set expires_at to 25 hours ago
        for key in cache:
            cache[key]["expires_at"] = time.time() - (25 * 3600)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f)

        # Now lookup should return None
        retrieved = lookup_cached_research(topic)
        assert retrieved is None

    def test_clear_expired_returns_count(self) -> None:
        """Cache clear: --clear-expired returns count of pruned entries."""
        # Add some entries
        cache_research_result("topic1", {"a": 1})
        cache_research_result("topic2", {"b": 2})
        cache_research_result("topic3", {"c": 3})

        # Expire one of them
        cache_file = Path(".spiral") / "research_cache.json"
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)

        # Get first key and expire it
        first_key = list(cache.keys())[0]
        cache[first_key]["expires_at"] = time.time() - (25 * 3600)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f)

        # Clear expired should return 1
        count = cache_clear_expired()
        assert count == 1

        # Verify the expired entry is gone
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        assert len(cache) == 2

    def test_multiple_topics_independent(self) -> None:
        """Multiple topics: entries for different topics are independent."""
        topic1_result = {"topic": "1", "value": "a"}
        topic2_result = {"topic": "2", "value": "b"}

        cache_research_result("topic_1", topic1_result)
        cache_research_result("topic_2", topic2_result)

        assert lookup_cached_research("topic_1") == topic1_result
        assert lookup_cached_research("topic_2") == topic2_result

    def test_cache_init_prunes_expired(self) -> None:
        """cache_init: pruning works correctly on module initialization."""
        # Add entries
        cache_research_result("fresh", {"status": "new"})
        cache_research_result("old", {"status": "old"})

        # Expire one
        cache_file = Path(".spiral") / "research_cache.json"
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)

        old_key = list(cache.keys())[-1]
        cache[old_key]["expires_at"] = time.time() - (25 * 3600)

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f)

        # Run cache_init which should prune
        cache_init()

        # Verify old entry is gone
        assert lookup_cached_research("old") is None
        assert lookup_cached_research("fresh") is not None


# Module-level test functions matching AC criteria
def test_cache_miss_returns_none() -> None:
    """AC: Cache miss returns None."""
    test = TestTopicLevelCache()
    test.setup_method()
    try:
        test.test_cache_miss_returns_none()
    finally:
        test.teardown_method()


def test_cache_hit_returns_dict() -> None:
    """AC: Cache hit returns stored dict."""
    test = TestTopicLevelCache()
    test.setup_method()
    try:
        test.test_cache_hit_returns_dict()
    finally:
        test.teardown_method()


def test_expired_entry_returns_none() -> None:
    """AC: Entry older than 24h returns None."""
    test = TestTopicLevelCache()
    test.setup_method()
    try:
        test.test_expired_entry_returns_none()
    finally:
        test.teardown_method()
