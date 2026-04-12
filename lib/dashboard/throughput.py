#!/usr/bin/env python3
"""throughput.py — Hourly story completion aggregation for dashboard.

Parses results.tsv and aggregates completed stories by hour,
enabling real-time throughput visualization.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..results_tsv import parse_results_tsv

# Cache for throughput data (5-second TTL per acceptance criteria)
_THROUGHPUT_CACHE: dict[str, Any] = {}
_CACHE_TIMESTAMP: float = 0.0
_CACHE_TTL_SECONDS = 5


def aggregate(
    results_path: str = ".spiral/results.tsv",
    checkpoint_path: str = ".spiral/_checkpoint.json",
) -> list[dict[str, Any]]:
    """Aggregate completed stories by hour for current iteration.

    Args:
        results_path: Path to results.tsv file
        checkpoint_path: Path to _checkpoint.json for current iteration

    Returns:
        List of dicts: [{hour: '2026-04-05T14:00', count: 3, stories: ['US-100', 'US-101']}, ...]
        Sorted by hour ascending.
    """
    global _THROUGHPUT_CACHE, _CACHE_TIMESTAMP

    # Check cache (5-second TTL)
    current_time = time.time()
    if _CACHE_TIMESTAMP and (current_time - _CACHE_TIMESTAMP) < _CACHE_TTL_SECONDS:
        cached = _THROUGHPUT_CACHE.get("result", [])
        if isinstance(cached, list):
            return cached
        return []

    # Get current iteration from checkpoint
    current_iter = None
    try:
        checkpoint_file = Path(checkpoint_path)
        if checkpoint_file.exists():
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
                current_iter = checkpoint.get("iter")
    except (json.JSONDecodeError, FileNotFoundError, KeyError):
        pass

    # Parse results.tsv
    results_path_obj = Path(results_path)
    if not results_path_obj.exists():
        _THROUGHPUT_CACHE = {"result": []}
        _CACHE_TIMESTAMP = current_time
        return []

    records = parse_results_tsv(results_path)

    # Filter: status='passed' and current iteration (if known)
    passed_records = [
        r for r in records if r.status == "passed" and (current_iter is None or r.spiral_iter == str(current_iter))
    ]

    # Group by hour
    hourly_aggregation: dict[str, dict[str, Any]] = {}
    for record in passed_records:
        try:
            # Parse timestamp: e.g., "2026-04-05T14:23:45Z"
            dt = datetime.fromisoformat(record.timestamp.replace("Z", "+00:00"))
            # Hour string: "2026-04-05T14:00"
            hour_key = dt.strftime("%Y-%m-%dT%H:00")

            if hour_key not in hourly_aggregation:
                hourly_aggregation[hour_key] = {"count": 0, "stories": []}

            hourly_aggregation[hour_key]["count"] += 1
            hourly_aggregation[hour_key]["stories"].append(record.story_id)
        except (ValueError, AttributeError):
            # Skip malformed timestamps
            continue

    # Build result list and sort by hour
    result = [
        {"hour": hour, "count": data["count"], "stories": data["stories"]}
        for hour, data in sorted(hourly_aggregation.items())
    ]

    # Cache the result
    _THROUGHPUT_CACHE = {"result": result}
    _CACHE_TIMESTAMP = current_time

    return result
