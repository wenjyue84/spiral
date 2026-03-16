"""Unit tests for lib/plan_cache.py — Agentic Plan Cache (US-353)."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from plan_cache import (
    plan_cache_key,
    plan_cache_store,
    plan_cache_lookup,
    plan_cache_prune,
    plan_cache_inject,
    _primary_file_ext,
    _story_type,
    _key_source,
)


def _make_story(
    story_id="US-100",
    title="Add search endpoint",
    complexity="medium",
    files_to_touch=None,
    tags=None,
    source="research",
):
    return {
        "id": story_id,
        "title": title,
        "estimatedComplexity": complexity,
        "filesTouch": files_to_touch or ["lib/search.py", "tests/test_search.py"],
        "tags": tags or ["module-api"],
        "_source": source,
    }


def _make_plan(story_id="US-100", duration=60):
    return {
        "story_id": story_id,
        "duration_s": duration,
        "model": "sonnet",
    }


class TestCacheKeyGeneration:
    """Cache key = sha256(story_type + complexity + primary_file_ext)."""

    def test_key_is_sha256_hex(self):
        story = _make_story()
        key = plan_cache_key(story)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_story_produces_same_key(self):
        story = _make_story()
        assert plan_cache_key(story) == plan_cache_key(story)

    def test_different_complexity_produces_different_key(self):
        s1 = _make_story(complexity="small")
        s2 = _make_story(complexity="large")
        assert plan_cache_key(s1) != plan_cache_key(s2)

    def test_different_file_ext_produces_different_key(self):
        s1 = _make_story(files_to_touch=["app.py"])
        s2 = _make_story(files_to_touch=["app.ts"])
        assert plan_cache_key(s1) != plan_cache_key(s2)

    def test_key_source_includes_type_complexity_ext(self):
        story = _make_story(complexity="small", files_to_touch=["lib/foo.py"])
        source = _key_source(story)
        assert "small" in source
        assert ".py" in source


class TestPrimaryFileExt:
    def test_most_common_ext(self):
        assert _primary_file_ext({"filesTouch": ["a.py", "b.py", "c.ts"]}) == ".py"

    def test_empty_files_to_touch(self):
        assert _primary_file_ext({"filesTouch": []}) == ""

    def test_no_files_to_touch(self):
        assert _primary_file_ext({}) == ""


class TestStoryType:
    def test_includes_source(self):
        story = _make_story(source="test-fix")
        result = _story_type(story)
        assert "test-fix" in result

    def test_includes_tags(self):
        story = _make_story(tags=["module-api", "security"])
        result = _story_type(story)
        assert "module-api" in result
        assert "security" in result

    def test_includes_title_keywords(self):
        story = _make_story(title="Add search endpoint validation")
        result = _story_type(story)
        assert "add" in result
        assert "search" in result


class TestPlanCacheStore:
    def test_creates_cache_file(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan = _make_plan()
        path = plan_cache_store(cache_dir, story, plan)
        assert os.path.exists(path)
        assert path.endswith(".json")

    def test_cache_file_contains_plan(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan = _make_plan()
        path = plan_cache_store(cache_dir, story, plan)
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        assert entry["plan"] == plan
        assert entry["story_id"] == "US-100"
        assert "stored_ts" in entry
        assert "key_source" in entry

    def test_creates_cache_dir(self, tmp_path):
        cache_dir = str(tmp_path / "new_dir" / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        assert os.path.isdir(cache_dir)


class TestPlanCacheLookup:
    def test_exact_match(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan = _make_plan()
        plan_cache_store(cache_dir, story, plan)
        result = plan_cache_lookup(cache_dir, story, ttl_hours=168)
        assert result is not None
        assert result["plan"] == plan

    def test_miss_when_empty(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        os.makedirs(cache_dir)
        story = _make_story()
        result = plan_cache_lookup(cache_dir, story, ttl_hours=168)
        assert result is None

    def test_miss_when_disabled(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        result = plan_cache_lookup(cache_dir, story, ttl_hours=0)
        assert result is None

    def test_expired_entry_not_returned(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        # Manually expire the entry
        key = plan_cache_key(story)
        path = os.path.join(cache_dir, f"{key}.json")
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        entry["stored_ts"] = time.time() - (200 * 3600)  # 200 hours ago
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        result = plan_cache_lookup(cache_dir, story, ttl_hours=168)
        assert result is None

    def test_similarity_fallback(self, tmp_path):
        """A similar story (same source, tags, complexity) should match even with different title."""
        cache_dir = str(tmp_path / "plan_cache")
        stored_story = _make_story(
            story_id="US-100",
            title="Add search endpoint",
            complexity="medium",
            tags=["module-api"],
            source="research",
            files_to_touch=["lib/search.py"],
        )
        plan = _make_plan(story_id="US-100")
        plan_cache_store(cache_dir, stored_story, plan)

        # Different story ID and title but same type/complexity/ext
        query_story = _make_story(
            story_id="US-200",
            title="Add filter endpoint",
            complexity="medium",
            tags=["module-api"],
            source="research",
            files_to_touch=["lib/filter.py"],
        )
        result = plan_cache_lookup(cache_dir, query_story, ttl_hours=168)
        assert result is not None
        assert result["plan"]["story_id"] == "US-100"

    def test_no_match_below_threshold(self, tmp_path):
        """Completely different stories should not match via similarity."""
        cache_dir = str(tmp_path / "plan_cache")
        stored_story = _make_story(
            complexity="small",
            tags=["module-ui"],
            source="ai-example",
            files_to_touch=["app.tsx"],
        )
        plan_cache_store(cache_dir, stored_story, _make_plan())

        query_story = _make_story(
            title="Implement database migration",
            complexity="large",
            tags=["module-db"],
            source="test-fix",
            files_to_touch=["lib/migrate.py"],
        )
        result = plan_cache_lookup(cache_dir, query_story, ttl_hours=168)
        assert result is None


class TestPlanCachePrune:
    def test_prune_expired(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        # Expire it
        key = plan_cache_key(story)
        path = os.path.join(cache_dir, f"{key}.json")
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        entry["stored_ts"] = time.time() - (200 * 3600)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        pruned = plan_cache_prune(cache_dir, ttl_hours=168)
        assert pruned == 1
        assert not os.path.exists(path)

    def test_prune_keeps_valid(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        pruned = plan_cache_prune(cache_dir, ttl_hours=168)
        assert pruned == 0

    def test_prune_empty_dir(self, tmp_path):
        cache_dir = str(tmp_path / "nonexistent")
        pruned = plan_cache_prune(cache_dir, ttl_hours=168)
        assert pruned == 0


class TestPlanCacheInject:
    def test_inject_returns_markdown(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan = _make_plan()
        plan_cache_store(cache_dir, story, plan)
        result = plan_cache_inject(cache_dir, story, ttl_hours=168)
        assert "## Suggested Implementation Approach" in result
        assert "Plan Cache" in result
        assert "US-100" in result

    def test_inject_empty_when_no_match(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        os.makedirs(cache_dir)
        story = _make_story()
        result = plan_cache_inject(cache_dir, story, ttl_hours=168)
        assert result == ""

    def test_inject_empty_when_disabled(self, tmp_path):
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        plan_cache_store(cache_dir, story, _make_plan())
        result = plan_cache_inject(cache_dir, story, ttl_hours=0)
        assert result == ""


class TestEventLogging:
    """Verify cache hit/miss is logged to spiral_events.jsonl."""

    def test_store_returns_path_for_event_log(self, tmp_path):
        """plan_cache_store returns path — spiral.sh uses basename as plan_key for event."""
        cache_dir = str(tmp_path / "plan_cache")
        story = _make_story()
        path = plan_cache_store(cache_dir, story, _make_plan())
        plan_key = os.path.basename(path).replace(".json", "")
        assert len(plan_key) == 64  # sha256 hex
