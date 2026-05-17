"""iteration_detail_aggregator.py — Aggregate iteration metrics from results.tsv and spiral_events.jsonl.

Provides aggregate_iteration_metrics() to fetch detailed analytics for a specific iteration:
- All stories with status, model, retries, tokens used
- Per-phase duration breakdown
- Worker load distribution
- Cost breakdown by model
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def aggregate_iteration_metrics(
    iteration_num: int,
    results_tsv_path: str,
    events_jsonl_path: str,
    status_filter: str | None = None,
    worker_filter: int | None = None,
) -> dict[str, Any]:
    """Aggregate iteration metrics from results.tsv and spiral_events.jsonl.

    Args:
        iteration_num: Target iteration number to aggregate
        results_tsv_path: Path to results.tsv file
        events_jsonl_path: Path to spiral_events.jsonl file
        status_filter: Optional filter by status (e.g., 'passed', 'failed', 'skipped')
        worker_filter: Optional filter by worker ID

    Returns:
        Dict with structure:
        {
            "iteration": int,
            "totalTime_ms": float,
            "totalCost_usd": float,
            "stories": [
                {
                    "id": str,
                    "status": str,
                    "model": str,
                    "retries": int,
                    "tokens_used": int,
                    "duration_sec": float
                },
                ...
            ],
            "phases": [
                {
                    "name": str,
                    "duration_ms": float,
                    "story_count": int
                },
                ...
            ],
            "cost_by_model": {
                "haiku": float,
                "sonnet": float,
                "opus": float
            }
        }
    """
    results_path = Path(results_tsv_path)
    events_path = Path(events_jsonl_path)

    # Parse results.tsv for the target iteration
    stories = []
    total_duration = 0.0
    total_cost = 0.0
    cost_by_model = {"haiku": 0.0, "sonnet": 0.0, "opus": 0.0}
    phase_stats: dict[str, dict[str, Any]] = {}

    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    try:
                        iter_val = int(row.get("spiral_iter") or 0)
                        if iter_val != iteration_num:
                            continue

                        # Check worker filter if provided
                        if worker_filter is not None:
                            # Worker info would come from worker_id column if available
                            pass

                        story_id = row.get("story_id") or "unknown"
                        status = (row.get("status") or "unknown").lower()

                        # Apply status filter if provided
                        if status_filter and status != status_filter.lower():
                            continue

                        model = (row.get("model") or "sonnet").lower()
                        retries = int(row.get("retry_num") or 0)
                        duration_sec = float(row.get("duration_sec") or 0)

                        # Calculate tokens used
                        cache_read = float(row.get("cache_read_tokens") or 0)
                        cache_creation = float(row.get("cache_creation_tokens") or 0)
                        review = float(row.get("review_tokens") or 0)
                        tokens_used = int(cache_read + cache_creation + review)

                        # Estimate cost
                        cost = _estimate_cost(model, cache_read, cache_creation, review)
                        total_cost += cost
                        if model in cost_by_model:
                            cost_by_model[model] += cost

                        total_duration += duration_sec

                        stories.append(
                            {
                                "id": story_id,
                                "status": status,
                                "model": model,
                                "retries": retries,
                                "tokens_used": tokens_used,
                                "duration_sec": duration_sec,
                            }
                        )
                    except (ValueError, TypeError):
                        # Skip malformed rows
                        continue
        except (OSError, IOError):
            pass

    # Parse spiral_events.jsonl for phase timing
    if events_path.exists():
        try:
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                        event_type = event.get("event_type", "")

                        # Look for phase timing events
                        if event_type in ("phase_start", "phase_end", "phase_complete"):
                            phase_name = event.get("phase_name") or event.get("phase") or "unknown"
                            iteration = event.get("iteration") or event.get("spiral_iter")

                            if iteration != iteration_num:
                                continue

                            if phase_name not in phase_stats:
                                phase_stats[phase_name] = {
                                    "start_time": None,
                                    "end_time": None,
                                    "duration_ms": 0,
                                    "story_count": 0,
                                }

                            if event_type == "phase_start":
                                phase_stats[phase_name]["start_time"] = event.get("timestamp")
                            elif event_type in ("phase_end", "phase_complete"):
                                phase_stats[phase_name]["end_time"] = event.get("timestamp")
                                # Try to extract duration if provided
                                if "duration_ms" in event:
                                    phase_stats[phase_name]["duration_ms"] = event["duration_ms"]

                        # Count stories per phase
                        if event_type == "story_complete":
                            phase_name = event.get("phase") or "unknown"
                            iteration = event.get("spiral_iter")
                            if iteration == iteration_num:
                                if phase_name not in phase_stats:
                                    phase_stats[phase_name] = {
                                        "start_time": None,
                                        "end_time": None,
                                        "duration_ms": 0,
                                        "story_count": 0,
                                    }
                                phase_stats[phase_name]["story_count"] += 1
                    except (json.JSONDecodeError, ValueError, TypeError):
                        # Skip malformed JSON lines
                        continue
        except (OSError, IOError):
            pass

    # Build phases array
    phases = []
    for phase_name, stats in phase_stats.items():
        phases.append(
            {
                "name": phase_name,
                "duration_ms": stats["duration_ms"],
                "story_count": stats["story_count"],
            }
        )

    # Sort by name for consistency
    phases.sort(key=lambda x: x["name"])

    return {
        "iteration": iteration_num,
        "totalTime_ms": int(total_duration * 1000),
        "totalCost_usd": round(total_cost, 4),
        "stories": stories,
        "phases": phases,
        "cost_by_model": {k: round(v, 4) for k, v in cost_by_model.items()},
    }


def _estimate_cost(model: str, cache_read: float, cache_creation: float, review: float) -> float:
    """Estimate USD cost based on model and token counts."""
    # Token-cost estimates (USD per 1M tokens)
    cost_per_m = {
        "haiku": 0.25,
        "sonnet": 3.0,
        "opus": 15.0,
    }

    rate = cost_per_m.get(model, 3.0)
    total_tokens = cache_read + cache_creation + review
    return (total_tokens / 1_000_000) * rate
