#!/usr/bin/env python3
"""
stuck_story_analyzer.py — Analyze stories stuck in retry loops.

Identifies stories with 3+ retry attempts, tracks model escalation patterns,
and provides metrics for suggesting decomposition strategies.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StuckStory:
    """Metrics for a story stuck in retry exhaustion."""

    story_id: str
    attempt_count: int
    last_model_tried: str
    escalation_chain: str
    original_token_count: int


def analyze_exhaustion(results_tsv_path: str) -> list[StuckStory]:
    """
    Analyze results.tsv for stuck stories (3+ attempts).

    Groups records by story_id, filters for attempt_count >= 3,
    builds escalation_chain from model column, and extracts token counts.

    Args:
        results_tsv_path: Path to results.tsv file

    Returns:
        List of StuckStory objects representing stories with 3+ attempts
    """
    results_file = Path(results_tsv_path)
    if not results_file.exists():
        return []

    # Group records by story_id
    story_records: dict[str, list[dict[str, str]]] = {}

    try:
        with open(results_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return []

            for row in reader:
                story_id = row.get("story_id", "").strip()
                if not story_id:
                    continue
                if story_id not in story_records:
                    story_records[story_id] = []
                story_records[story_id].append(row)
    except (FileNotFoundError, ValueError):
        return []

    # Analyze each story for retry exhaustion
    stuck_stories: list[StuckStory] = []

    for story_id, records in story_records.items():
        attempt_count = len(records)

        # Only include stories with 3+ attempts
        if attempt_count < 3:
            continue

        # Build escalation chain from model column (order matters)
        models: list[str] = []
        for record in records:
            model = record.get("model", "").strip()
            if model:
                models.append(model)

        escalation_chain = "→".join(models) if models else "unknown"

        # Get last model tried
        last_model = models[-1] if models else "unknown"

        # Extract token count from first or last record
        # Priority: cache_read_tokens -> review_tokens -> 0
        original_token_count = 0
        for record in records:
            try:
                cache_tokens = int(record.get("cache_read_tokens", 0) or 0)
                review_tokens = int(record.get("review_tokens", 0) or 0)
                if cache_tokens > 0 or review_tokens > 0:
                    original_token_count = cache_tokens + review_tokens
                    break
            except (ValueError, TypeError):
                continue

        stuck_stories.append(
            StuckStory(
                story_id=story_id,
                attempt_count=attempt_count,
                last_model_tried=last_model,
                escalation_chain=escalation_chain,
                original_token_count=original_token_count,
            )
        )

    # Sort by attempt count descending
    stuck_stories.sort(key=lambda x: x.attempt_count, reverse=True)

    return stuck_stories
