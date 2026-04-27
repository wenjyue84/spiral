"""File-backed JSON cache for Phase R research queries with TTL and statistics.

This module provides two implementations:
1. ResearchCache: Simple key-value cache with 24h TTL for story research summaries
2. Semantic research caching (imported from lib.research.research_cache for backward compatibility)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

# Import semantic caching functions for backward compatibility
_here = os.path.dirname(os.path.abspath(__file__))
exec(
    open(os.path.join(_here, "research", "research_cache.py"), encoding="utf-8").read(),
    globals(),
)


class ResearchCache:
    """Simple file-backed cache for Phase R research queries with 24h TTL."""

    def __init__(self, cache_path: str = ".spiral/research_cache.json") -> None:
        """Initialize cache and prune expired entries on startup.

        Args:
            cache_path: Path to cache file. Creates .spiral/ dir if needed.
        """
        self.cache_path = Path(cache_path)
        self.hit_count = 0
        self.miss_count = 0
        self._cache: dict[str, dict[str, Any]] = {}
        self._load()
        self.prune()

    def _load(self) -> None:
        """Load cache from disk if it exists."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache = data.get("entries", {})
                    self.hit_count = data.get("hit_count", 0)
                    self.miss_count = data.get("miss_count", 0)
            except (json.JSONDecodeError, KeyError):
                self._cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": self._cache,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
        }
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired.
        """
        if key in self._cache:
            self.hit_count += 1
            self._save()
            return self._cache[key].get("value")
        self.miss_count += 1
        self._save()
        return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        """Store value in cache with current timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        self._cache[key] = {
            "value": value,
            "timestamp": time.time(),
        }
        self._save()

    def prune(self) -> None:
        """Remove entries older than 24 hours."""
        now = time.time()
        ttl_seconds = 24 * 60 * 60
        expired_keys = [
            k
            for k, v in self._cache.items()
            if now - v.get("timestamp", 0) > ttl_seconds
        ]
        for k in expired_keys:
            del self._cache[k]
        if expired_keys:
            self._save()

    def stats(self) -> dict[str, int]:
        """Return cache statistics.

        Returns:
            Dict with hit_count and miss_count.
        """
        return {"hit_count": self.hit_count, "miss_count": self.miss_count}
