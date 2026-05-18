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


def apply_research_quality_filter(
    research_output_path: str,
    min_score: int = 40,
    quality_log_path: str = ".spiral/research_quality.jsonl",
) -> None:
    """Filter research results by source credibility before synthesis (US-1407).

    Loads research results from _research_output.json, scores each result by
    source credibility using score_research_result(), filters out low-scoring
    results, logs filtering decisions, and writes filtered results back.

    Args:
        research_output_path: Path to .spiral/_research_output.json
        min_score: Minimum credibility score to keep (default 40)
        quality_log_path: Path to write filtering log (JSONL format)
    """
    from lib.research_quality import filter_research_results_by_quality

    try:
        output_path = Path(research_output_path)
        if not output_path.exists():
            return  # No research output, nothing to filter

        # Load research results
        with open(output_path, encoding="utf-8") as f:
            results = json.load(f)

        # Apply quality filtering
        filtered = filter_research_results_by_quality(
            results,
            min_score=min_score,
            log_path=quality_log_path,
        )

        # Write filtered results back
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(filtered, f, indent=2)

        # Log summary
        skipped = filtered.get("_skipped_count", 0)
        kept = len(filtered.get("stories", []))
        if skipped > 0:
            print(
                f"[Phase R] Research quality filter: kept {kept} results, "
                f"skipped {skipped} low-credibility sources (score < {min_score})"
            )
    except Exception as e:
        # Graceful fallback — Phase R should continue even if filtering fails
        print(f"[Phase R] Research quality filter failed: {e}", file=sys.stderr)
