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
        rows: List of dicts with at least 'cache_hit', 'cache_read_tokens',
              and optionally 'cache_creation_tokens' keys.

    Returns:
        Dict with:
          - hit_rate_pct: float (0-100)
          - total_calls: int
          - cache_hits: int
          - cache_misses: int
          - total_cache_read_tokens: int
          - total_cache_creation_tokens: int
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
            "total_cache_creation_tokens": 0,
            "healthy": True,
            "diagnosis": "No data available for cache analysis.",
        }

    total = len(rows)
    hits = sum(1 for r in rows if str(r.get("cache_hit", "false")).lower() == "true")
    misses = total - hits
    cache_read_tokens = sum(
        int(r.get("cache_read_tokens", 0) or 0) for r in rows
    )
    cache_creation_tokens = sum(
        int(r.get("cache_creation_tokens", 0) or 0) for r in rows
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
        "total_cache_creation_tokens": cache_creation_tokens,
        "healthy": healthy,
        "diagnosis": diagnosis,
    }


def per_story_cache_ratio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute per-story cache hit ratio: cache_read / (cache_read + cache_creation).

    This measures what fraction of cacheable prompt content was served from
    cache vs freshly created. High ratio = cache working well.

    Args:
        rows: List of dicts from results.tsv with story_id, cache_read_tokens,
              and cache_creation_tokens fields.

    Returns:
        List of dicts with story_id, cache_read_tokens, cache_creation_tokens,
        cache_ratio_pct (0-100), sorted by ratio ascending (worst first).
    """
    if not rows:
        return []

    stories: dict[str, dict[str, int]] = {}
    for r in rows:
        sid = str(r.get("story_id", ""))
        if not sid:
            continue
        if sid not in stories:
            stories[sid] = {"cache_read": 0, "cache_creation": 0}
        stories[sid]["cache_read"] += int(r.get("cache_read_tokens", 0) or 0)
        stories[sid]["cache_creation"] += int(
            r.get("cache_creation_tokens", 0) or 0
        )

    result = []
    for sid, vals in stories.items():
        denominator = vals["cache_read"] + vals["cache_creation"]
        if denominator > 0:
            ratio = (vals["cache_read"] / denominator) * 100
        else:
            ratio = 0.0
        result.append({
            "story_id": sid,
            "cache_read_tokens": vals["cache_read"],
            "cache_creation_tokens": vals["cache_creation"],
            "cache_ratio_pct": round(ratio, 1),
        })

    def _sort_key(entry: dict[str, Any]) -> float:
        val = entry["cache_ratio_pct"]
        return float(val) if isinstance(val, (int, float)) else 0.0

    result.sort(key=_sort_key)
    return result
