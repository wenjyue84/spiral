#!/usr/bin/env python3
"""analyze_results.py — Parse results.tsv for research cache effectiveness metrics.

Reads rows with research_source column (values: 'cache' | 'gemini_api') and
computes cache hit rate, time saved, and per-iteration trend data.
"""

import csv
from pathlib import Path
from typing import Any

# Estimated seconds saved per cache hit (avoids a live Gemini API call)
CACHE_SECONDS_PER_HIT = 30


def parse_research_cache(
    results_path: Path,
    start_iteration: int = 0,
    end_iteration: int | None = None,
) -> dict[str, Any]:
    """Parse results.tsv and compute research cache statistics.

    Args:
        results_path: Path to results.tsv
        start_iteration: Minimum spiral_iter to include (inclusive)
        end_iteration: Maximum spiral_iter to include (inclusive), or None for all

    Returns:
        dict with keys: hit_rate, total_queries, cached, time_saved_seconds, trend
    """
    default: dict[str, Any] = {
        "hit_rate": 0.0,
        "total_queries": 0,
        "cached": 0,
        "time_saved_seconds": 0,
        "trend": [],
    }

    if not results_path.exists():
        return default

    # Group cache stats by iteration: {iter: {total: int, cached: int}}
    by_iter: dict[int, dict[str, int]] = {}

    try:
        with open(results_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None or "research_source" not in reader.fieldnames:
                return default

            for row in reader:
                source = (row.get("research_source") or "").strip()
                if source not in ("cache", "gemini_api"):
                    continue

                try:
                    iteration = int(row.get("spiral_iter", 0) or 0)
                except (ValueError, TypeError):
                    iteration = 0

                if iteration < start_iteration:
                    continue
                if end_iteration is not None and iteration > end_iteration:
                    continue

                if iteration not in by_iter:
                    by_iter[iteration] = {"total": 0, "cached": 0}
                by_iter[iteration]["total"] += 1
                if source == "cache":
                    by_iter[iteration]["cached"] += 1

    except OSError:
        return default

    if not by_iter:
        return default

    total_queries = sum(v["total"] for v in by_iter.values())
    total_cached = sum(v["cached"] for v in by_iter.values())
    hit_rate = total_cached / total_queries if total_queries > 0 else 0.0
    time_saved = total_cached * CACHE_SECONDS_PER_HIT

    trend = [
        {
            "iteration": iteration,
            "hit_rate": round(v["cached"] / v["total"], 4) if v["total"] > 0 else 0.0,
        }
        for iteration, v in sorted(by_iter.items())
    ]

    return {
        "hit_rate": round(hit_rate, 4),
        "total_queries": total_queries,
        "cached": total_cached,
        "time_saved_seconds": time_saved,
        "trend": trend,
    }
