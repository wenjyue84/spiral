#!/usr/bin/env python3
"""
predict_cost.py — KNN-based token/cost estimator for SPIRAL stories.

Reads results.tsv, finds K nearest neighbors by story type, and outputs
a JSON estimate with tokens, cost, confidence, and matched stories.

Usage:
    python lib/predict_cost.py --story-id US-001 --prd prd.json --history results.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.constants import (
    INPUT_OUTPUT_RATIO,
    MIN_HISTORY_ROWS,
    PRICING,
    TOKENS_PER_SEC_OUTPUT,
)
from routing.velocity_model import classify_story

K_NEIGHBORS = 5  # Number of nearest neighbors to use


def _load_history(tsv_path: str) -> list[dict[str, Any]]:
    """Load results.tsv and return list of row dicts."""
    if not os.path.isfile(tsv_path):
        return []
    rows: list[dict[str, Any]] = []
    with open(tsv_path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(dict(row))
    return rows


def _tokens_from_row(row: dict[str, Any]) -> float:
    """Estimate total tokens from a results.tsv row."""
    # Try explicit token columns first
    try:
        tokens_in = float(row.get("tokens_in") or 0)
        tokens_out = float(row.get("tokens_out") or 0)
        if tokens_in + tokens_out > 0:
            return tokens_in + tokens_out
    except (ValueError, TypeError):
        pass

    # Fall back to duration-based estimation
    try:
        duration = float(row.get("duration_sec") or row.get("duration_s") or 0)
    except (ValueError, TypeError):
        duration = 0.0

    if duration <= 0:
        return 0.0
    output_tokens = duration * TOKENS_PER_SEC_OUTPUT
    return float(output_tokens * (1 + INPUT_OUTPUT_RATIO))


def _normalise_model(raw: str) -> str:
    raw_lower = raw.strip().lower() if raw else ""
    for key in PRICING:
        if key in raw_lower:
            return str(key)
    return "sonnet"


def _cost_from_tokens(tokens: float, model_raw: str) -> float:
    """Estimate USD cost from total tokens and model string."""
    model = _normalise_model(model_raw)
    p = PRICING[model]
    output_t = tokens / (1 + INPUT_OUTPUT_RATIO)
    input_t = tokens - output_t
    return float((input_t / 1_000_000) * p["input"] + (output_t / 1_000_000) * p["output"])


class KNNEstimator:
    """K-nearest-neighbors cost estimator over results.tsv data."""

    def __init__(self, k: int = K_NEIGHBORS) -> None:
        self.k = k
        self._data: list[dict[str, Any]] = []

    def fit(self, tsv_path: str) -> None:
        """Load history from results.tsv."""
        rows = _load_history(tsv_path)
        enriched: list[dict[str, Any]] = []
        for row in rows:
            title = (row.get("story_title") or "").strip()
            story_type = classify_story(title) if title else "general"
            tokens = _tokens_from_row(row)
            cost = _cost_from_tokens(tokens, row.get("model") or "sonnet")
            enriched.append(
                {
                    "story_id": row.get("story_id", ""),
                    "story_title": title,
                    "story_type": story_type,
                    "tokens": tokens,
                    "cost_usd": cost,
                    "model": row.get("model", ""),
                    "status": row.get("status", ""),
                }
            )
        self._data = enriched

    def predict(self, story: dict[str, Any]) -> dict[str, Any]:
        """
        Predict cost for a story.

        Args:
            story: dict with keys: id, title (and optionally estimatedComplexity)

        Returns:
            dict with: estimated_tokens, estimated_cost, confidence_pct, similar_stories
        """
        if len(self._data) < MIN_HISTORY_ROWS:
            return {
                "estimated_tokens": 0,
                "estimated_cost": 0.0,
                "confidence_pct": 0.0,
                "similar_stories": [],
            }

        title = (story.get("title") or "").strip()
        target_type = classify_story(title)

        # Score each historical entry: same type = closer neighbor
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self._data:
            if entry["tokens"] <= 0:
                continue
            dist = 0.0 if entry["story_type"] == target_type else 1.0
            scored.append((dist, entry))

        # Sort by distance, take K nearest
        scored.sort(key=lambda x: x[0])
        neighbors = [entry for _, entry in scored[: self.k]]

        if not neighbors:
            return {
                "estimated_tokens": 0,
                "estimated_cost": 0.0,
                "confidence_pct": 0.0,
                "similar_stories": [],
            }

        token_vals = [n["tokens"] for n in neighbors]
        cost_vals = [n["cost_usd"] for n in neighbors]

        mean_tokens = sum(token_vals) / len(token_vals)
        mean_cost = sum(cost_vals) / len(cost_vals)

        # Confidence: consistency * history size * type match rate
        if len(token_vals) > 1 and mean_tokens > 0:
            variance = sum((t - mean_tokens) ** 2 for t in token_vals) / len(token_vals)
            std_dev = math.sqrt(variance)
            cv = std_dev / mean_tokens
            consistency_score = max(0.0, 1.0 - cv)
        else:
            consistency_score = 0.5

        history_factor = min(1.0, len(self._data) / 20)
        same_type_count = sum(1 for n in neighbors if n["story_type"] == target_type)
        type_factor = same_type_count / len(neighbors)

        confidence_pct = round(
            100.0 * (consistency_score * 0.4 + history_factor * 0.3 + type_factor * 0.3),
            1,
        )

        similar = [
            {
                "story_id": n["story_id"],
                "story_title": n["story_title"],
                "story_type": n["story_type"],
                "tokens": round(n["tokens"]),
                "cost_usd": round(n["cost_usd"], 6),
            }
            for n in neighbors
        ]

        return {
            "estimated_tokens": round(mean_tokens),
            "estimated_cost": round(mean_cost, 6),
            "confidence_pct": confidence_pct,
            "similar_stories": similar,
        }


def predict_story(story_id: str, prd_path: str, history_path: str) -> dict[str, Any]:
    """Load story from prd.json, fit estimator, return prediction."""
    if not os.path.isfile(prd_path):
        raise FileNotFoundError(f"PRD file not found: {prd_path}")

    with open(prd_path, encoding="utf-8") as f:
        prd: dict[str, Any] = json.load(f)

    stories = prd.get("userStories", [])
    story = next((s for s in stories if s.get("id") == story_id), None)
    if story is None:
        raise ValueError(f"Story {story_id!r} not found in {prd_path}")

    estimator = KNNEstimator()
    estimator.fit(history_path)
    return estimator.predict(story)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="KNN-based story cost estimator from results.tsv history"
    )
    parser.add_argument(
        "--story-id", required=True, help="Story ID to estimate (e.g. US-001)"
    )
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--history", required=True, help="Path to results.tsv")
    parser.add_argument(
        "--budget-remaining",
        type=float,
        default=None,
        help="Remaining budget in USD; exit 2 if estimated cost exceeds this",
    )
    args = parser.parse_args(argv)

    result = predict_story(args.story_id, args.prd, args.history)

    # Budget check: exit code 2 if over budget
    if args.budget_remaining is not None:
        estimated_cost = result.get("estimated_cost", 0.0)
        if estimated_cost > args.budget_remaining:
            result["budget_exceeded"] = True
            result["budget_remaining"] = args.budget_remaining
            print(json.dumps(result, indent=2))
            sys.exit(2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
