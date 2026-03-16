"""lib/prompt_cache_analysis.py
US-338: Cache hit rate analysis for spiral diagnose.

Analyzes results.tsv rows to compute prompt cache hit rates and diagnose
low hit rates caused by prompt structure changes (dynamic values in
system prompt busting the cache prefix).
"""
from __future__ import annotations

from typing import Any


def analyze_cache_hit_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze cache hit rate from results.tsv rows.

    Args:
        rows: List of dicts with at least 'cache_hit' and 'cache_read_tokens' keys.

    Returns:
        Dict with:
          - hit_rate_pct: float (0-100)
          - total_calls: int
          - cache_hits: int
          - cache_misses: int
          - total_cache_read_tokens: int
          - healthy: bool (True if hit_rate >= 50% or no data)
          - diagnosis: str (human-readable explanation)
    """
    if not rows:
        return {
            "hit_rate_pct": 0.0,
            "total_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_cache_read_tokens": 0,
            "healthy": True,
            "diagnosis": "No data available for cache analysis.",
        }

    total = len(rows)
    hits = sum(1 for r in rows if str(r.get("cache_hit", "false")).lower() == "true")
    misses = total - hits
    cache_read_tokens = sum(
        int(r.get("cache_read_tokens", 0) or 0) for r in rows
    )
    hit_rate = (hits / total) * 100 if total > 0 else 0.0
    healthy = hit_rate >= 50.0 or total == 0

    if healthy:
        diagnosis = f"Cache hit rate {hit_rate:.1f}% is healthy."
    else:
        diagnosis = (
            f"Cache hit rate {hit_rate:.1f}% is below 50% threshold. "
            f"Likely cause: prompt structure changes injecting dynamic values "
            f"(timestamps, story IDs, iteration numbers) into the system prompt, "
            f"invalidating the cached prefix on each call. "
            f"Ensure all dynamic content is in the user prompt, not the system prompt."
        )

    return {
        "hit_rate_pct": round(hit_rate, 2),
        "total_calls": total,
        "cache_hits": hits,
        "cache_misses": misses,
        "total_cache_read_tokens": cache_read_tokens,
        "healthy": healthy,
        "diagnosis": diagnosis,
    }
