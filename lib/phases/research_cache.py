"""research_cache.py — Topic-level cache for Phase R research results.

Caches research results by topic in .spiral/research_cache.json with a 24-hour TTL.
Prevents duplicate Gemini calls when the same topic is researched multiple times.

Usage (CLI):
    python lib/phases/research_cache.py --clear-expired

Functions:
    lookup_cached_research(topic: str) -> dict | None
        Return cached result for topic if within TTL, else None.

    cache_research_result(topic: str, result: dict) -> None
        Store research result for topic with current timestamp.

    cache_init() -> None
        Prune expired entries from cache on module import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any

# Configuration
CACHE_FILE = os.path.join(".spiral", "research_cache.json")
TTL_SECONDS = 24 * 3600  # 24 hours


def _topic_key(topic: str) -> str:
    """Return first 16 chars of sha256 hash of topic."""
    digest = hashlib.sha256(topic.strip().lower().encode("utf-8")).hexdigest()
    return digest[:16]


def _now_ts() -> float:
    """Return current Unix timestamp."""
    return time.time()


def _load_cache() -> dict[str, Any]:
    """Load cache from JSON file. Return empty dict if missing or corrupted."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    """Save cache to JSON file atomically."""
    os.makedirs(".spiral", exist_ok=True)
    # Write to temp file first, then rename for atomicity
    temp_path = CACHE_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        # Atomic rename
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        os.rename(temp_path, CACHE_FILE)
    except OSError:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _is_valid(entry: dict[str, Any]) -> bool:
    """Check if cache entry is within TTL."""
    expires_at = entry.get("expires_at", 0)
    if not isinstance(expires_at, (int, float)):
        return False
    return _now_ts() < expires_at


def lookup_cached_research(topic: str) -> dict[str, Any] | None:
    """Return cached research result for topic if within TTL, else None."""
    cache = _load_cache()
    key = _topic_key(topic)

    if key not in cache:
        return None

    entry = cache[key]
    if not isinstance(entry, dict):
        return None
    if not _is_valid(entry):
        return None

    result = entry.get("result")
    if isinstance(result, dict):
        return result
    return None


def cache_research_result(topic: str, result: dict[str, Any]) -> None:
    """Store research result for topic with 24-hour TTL."""
    cache = _load_cache()
    key = _topic_key(topic)

    cache[key] = {
        "topic": topic.strip(),
        "result": result,
        "fetched_ts": _now_ts(),
        "expires_at": _now_ts() + TTL_SECONDS,
    }

    _save_cache(cache)


def cache_init() -> None:
    """Prune expired entries from cache. Called on module import."""
    cache = _load_cache()
    if not cache:
        return

    # Filter out expired entries
    expired_keys = [k for k, v in cache.items() if not _is_valid(v)]
    for key in expired_keys:
        del cache[key]

    if expired_keys:
        _save_cache(cache)


def cache_clear_expired() -> int:
    """Remove expired entries and return count of pruned entries."""
    cache = _load_cache()
    if not cache:
        return 0

    expired_keys = [k for k, v in cache.items() if not _is_valid(v)]
    for key in expired_keys:
        del cache[key]

    if expired_keys:
        _save_cache(cache)

    return len(expired_keys)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="SPIRAL topic research cache manager")
    parser.add_argument("--clear-expired", action="store_true", help="Prune expired entries")
    parser.add_argument("--lookup", type=str, help="Lookup cached result by topic (outputs JSON or empty)")
    parser.add_argument("--store", type=str, help="Store research result (requires --result parameter with JSON)")
    parser.add_argument("--result", type=str, help="JSON result to store (used with --store)")

    args = parser.parse_args()

    if args.clear_expired:
        count = cache_clear_expired()
        print(count)
    elif args.lookup:
        result = lookup_cached_research(args.lookup)
        if result:
            print(json.dumps(result))
        # else: print nothing (empty output means cache miss)
    elif args.store and args.result:
        try:
            result_dict = json.loads(args.result)
            cache_research_result(args.store, result_dict)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON in --result: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


# Prune expired entries on module import
cache_init()


if __name__ == "__main__":
    main()
