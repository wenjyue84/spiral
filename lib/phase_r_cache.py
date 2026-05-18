"""Phase R query-level research caching with configurable TTL.

Caches Gemini API research results by query string hash in .spiral/research-cache/
with configurable TTL (default 24 hours). Reduces redundant API calls when similar
queries are executed across iterations.

Usage:
    from lib.phase_r_cache import get_cached_research, cache_research

    # Check cache before calling Gemini
    cached = get_cached_research(query_string)
    if cached:
        results = cached
    else:
        results = call_gemini_api(query_string)
        cache_research(query_string, results)

Cache key is sha256(query), stored in .spiral/research-cache/{hash}.json
Cache format: {"query": str, "results": dict, "timestamp_created": ISO8601, "timestamp_expires": ISO8601}
TTL configurable via SPIRAL_RESEARCH_CACHE_TTL_HOURS environment variable (default 24 hours)
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _get_ttl_hours() -> int:
    """Get TTL in hours from environment variable, default 24."""
    try:
        return int(os.environ.get("SPIRAL_RESEARCH_CACHE_TTL_HOURS", "24"))
    except (ValueError, TypeError):
        return 24


def _get_cache_dir() -> Path:
    """Get cache directory path, creating if needed."""
    cache_dir = Path(".spiral") / "research-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _query_to_hash(query: str) -> str:
    """Convert query string to sha256 hash for use as cache key."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _get_now_utc() -> str:
    """Get current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _add_hours_to_now(hours: int) -> str:
    """Get future timestamp (now + hours) in ISO 8601 format."""
    future = datetime.now(timezone.utc) + timedelta(hours=hours)
    return future.isoformat()


def get_cached_research(query: str) -> dict[str, Any] | None:
    """Get cached research results if available and within TTL.

    Args:
        query: Query string to look up

    Returns:
        Cached results dict if cache hit and TTL valid, else None
    """
    cache_file = _get_cache_dir() / f"{_query_to_hash(query)}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Validate TTL
    expires_at = entry.get("timestamp_expires")
    if not expires_at:
        return None

    # Parse ISO 8601 timestamp and compare with now
    try:
        expires_dt = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) >= expires_dt:
            # Expired, don't return
            return None
    except (ValueError, TypeError):
        # Invalid timestamp, treat as miss
        return None

    # Return the cached results
    results = entry.get("results")
    if isinstance(results, dict):
        return results
    return None


def cache_research(query: str, results: dict[str, Any]) -> None:
    """Cache research results with TTL.

    Args:
        query: Query string (used to derive cache key)
        results: Results dict to cache
    """
    cache_dir = _get_cache_dir()
    cache_file = cache_dir / f"{_query_to_hash(query)}.json"

    ttl_hours = _get_ttl_hours()

    entry = {
        "query": query,
        "results": results,
        "timestamp_created": _get_now_utc(),
        "timestamp_expires": _add_hours_to_now(ttl_hours),
    }

    # Write atomically: temp file then rename
    temp_file = cache_file.parent / f"{cache_file.name}.tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=2)

        # Atomic rename
        if cache_file.exists():
            cache_file.unlink()
        temp_file.rename(cache_file)
    except OSError:
        # Clean up temp file on error
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def clear_cache() -> int:
    """Clear all cached research results.

    Returns:
        Number of cache files deleted
    """
    cache_dir = _get_cache_dir()

    if not cache_dir.exists():
        return 0

    count = 0
    for cache_file in cache_dir.glob("*.json"):
        try:
            cache_file.unlink()
            count += 1
        except OSError:
            pass

    return count


# ---------------------------------------------------------------------------
# Story-level cache: tracks research by story title hash for invalidation
# ---------------------------------------------------------------------------


def cache_key_from_story(story: dict[str, Any]) -> str:
    """Generate a stable cache key from story title using sha256.

    Args:
        story: Story dict with 'title' key

    Returns:
        sha256 hex digest of the story title
    """
    title = story.get("title", "")
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def _get_story_cache_file(cache_path: str | None = None) -> Path:
    """Get the story-level research_cache.json file path."""
    if cache_path:
        p = Path(cache_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    cache_dir = Path(os.environ.get("SPIRAL_HOME", ".spiral"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "research_cache.json"


def _load_story_cache(cache_path: str | None = None) -> dict[str, Any]:
    """Load the story-level research cache from disk."""
    cache_file = _get_story_cache_file(cache_path)
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_story_cache(cache: dict[str, Any], cache_path: str | None = None) -> None:
    """Save the story-level research cache atomically."""
    cache_file = _get_story_cache_file(cache_path)
    temp_file = cache_file.parent / f"{cache_file.name}.tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        if cache_file.exists():
            cache_file.unlink()
        temp_file.rename(cache_file)
    except OSError:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def check_cache_validity(story: dict[str, Any], cache_data: dict[str, Any]) -> bool:
    """Check if a cache entry is still valid for the current story.

    Compares the sha256 hash of the current story title against the hash
    stored in the cache entry. Returns False if the title has changed or
    the entry was previously invalidated.

    Args:
        story: Current story dict (must have 'title' key)
        cache_data: Cache entry dict (must have 'story_title_hash' key)

    Returns:
        True if cache is valid (title unchanged), False if stale
    """
    if "invalidated_at" in cache_data:
        return False
    current_hash = cache_key_from_story(story)
    return cache_data.get("story_title_hash") == current_hash


def cache_story_research(
    story: dict[str, Any],
    results: dict[str, Any],
    cache_path: str | None = None,
) -> str:
    """Cache research results for a story with title hash for invalidation detection.

    Args:
        story: Story dict with 'id' and 'title'
        results: Research results dict to store
        cache_path: Optional override for cache file path (useful in tests)

    Returns:
        Cache key (title hash) used for this entry
    """
    title_hash = cache_key_from_story(story)
    cache = _load_story_cache(cache_path)
    cache[title_hash] = {
        "story_id": story.get("id", "unknown"),
        "story_title": story.get("title", ""),
        "story_title_hash": title_hash,
        "results": results,
        "timestamp_created": _get_now_utc(),
    }
    _save_story_cache(cache, cache_path)
    return title_hash


def invalidate_story_cache_if_stale(
    story: dict[str, Any],
    cache_path: str | None = None,
) -> bool:
    """Invalidate cache entries whose story_id matches but title hash differs.

    Marks stale entries with an 'invalidated_at' timestamp. Leaves valid
    entries and already-invalidated entries untouched.

    Args:
        story: Current story dict (with updated title)
        cache_path: Optional override for cache file path (useful in tests)

    Returns:
        True if any entries were invalidated, False otherwise
    """
    story_id = story.get("id", "")
    current_hash = cache_key_from_story(story)
    cache = _load_story_cache(cache_path)
    invalidated = False
    for key, entry in cache.items():
        if (
            isinstance(entry, dict)
            and entry.get("story_id") == story_id
            and key != current_hash
            and "invalidated_at" not in entry
        ):
            entry["invalidated_at"] = _get_now_utc()
            invalidated = True
    if invalidated:
        _save_story_cache(cache, cache_path)
    return invalidated
