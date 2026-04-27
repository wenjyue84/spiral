"""Phase R cache integration with ResearchCache and telemetry logging.

This module wraps ResearchCache for Phase R research queries, tracking cache hits/misses
and writing telemetry to .spiral/research_telemetry.jsonl.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Optional

# Make lib importable by adding parent of lib to path
_spiral_root = str(Path(__file__).parent.parent.parent)
if _spiral_root not in sys.path:
    sys.path.insert(0, _spiral_root)

# Import from lib.research_cache (the module, not the research subdirectory)
from lib.research_cache import ResearchCache


class PhaseRCache:
    """Wrapper for ResearchCache with Phase R telemetry logging."""

    def __init__(
        self,
        cache_path: str = ".spiral/research_cache.json",
        telemetry_path: str = ".spiral/research_telemetry.jsonl",
    ) -> None:
        """Initialize Phase R cache with ResearchCache backend.

        Args:
            cache_path: Path to research_cache.json
            telemetry_path: Path to research_telemetry.jsonl
        """
        self.cache = ResearchCache(cache_path=cache_path)
        self.telemetry_path = Path(telemetry_path)
        self.start_time = time.time()
        self.queries_issued = 0

    def get_or_fetch(
        self, key: str, fetch_fn: Callable[..., dict[str, Any] | None], *fetch_args: Any, **fetch_kwargs: Any
    ) -> Optional[dict[str, Any]]:
        """Get from cache or fetch via provided function.

        Args:
            key: Cache key
            fetch_fn: Function to call if cache misses
            *fetch_args: Positional args for fetch_fn
            **fetch_kwargs: Keyword args for fetch_fn

        Returns:
            Cached or fetched value, or None on error
        """
        # Check cache first
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        # Cache miss: invoke fetch function
        self.queries_issued += 1
        try:
            result: dict[str, Any] | None = fetch_fn(*fetch_args, **fetch_kwargs)
            if result is not None:
                self.cache.put(key, result)
            return result
        except Exception as e:
            # Log but don't raise — Phase R should continue
            print(f"[PhaseRCache] fetch_fn failed: {e}", file=sys.stderr)
            return None

    def append_telemetry(self) -> None:
        """Write telemetry line to .spiral/research_telemetry.jsonl.

        Telemetry includes:
        - ts: ISO 8601 timestamp
        - hit_count: Cache hits
        - miss_count: Cache misses
        - api_calls_saved: Queries skipped via cache
        - time_saved_seconds: Estimated time saved
        """
        stats = self.cache.stats()
        hit_count = stats.get("hit_count", 0)
        miss_count = stats.get("miss_count", 0)
        api_calls_saved = hit_count
        time_saved_seconds = hit_count * 10.0  # Heuristic: ~10s per API call saved

        telemetry = {
            "ts": datetime.now(UTC).isoformat(),
            "hit_count": hit_count,
            "miss_count": miss_count,
            "api_calls_saved": api_calls_saved,
            "time_saved_seconds": time_saved_seconds,
        }

        # Append to telemetry file
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.telemetry_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(telemetry) + "\n")
