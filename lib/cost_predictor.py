#!/usr/bin/env python3
"""
cost_predictor.py — Simple cost prediction interface for Phase I cost guard.

Provides a predict_story_cost() function that estimates the USD cost of implementing
a single story based on historical results.tsv data.

This module is used by Phase I to check story costs before decomposition,
preventing the decompose stage when a story's cost exceeds SPIRAL_COST_CEILING.
"""

from __future__ import annotations

import os
from typing import Any

from lib.predict_cost import KNNEstimator


def predict_story_cost(
    story: dict[str, Any],
    history_path: str = "results.tsv",
) -> dict[str, Any]:
    """Predict the USD cost of implementing a story.

    Args:
        story: Story dict with at least 'id', 'title', and optionally 'estimatedComplexity'
        history_path: Path to results.tsv for training KNN estimator

    Returns:
        dict with keys:
          - tokens: estimated total input+output tokens
          - cost_usd: estimated USD cost (float)
          - confidence: confidence as fraction 0-1 (confidence_pct / 100)
          - similar_stories: list of similar historical stories used for estimation
    """
    # Initialize and fit KNN estimator on history
    estimator = KNNEstimator(k=5)

    if os.path.isfile(history_path):
        estimator.fit(history_path)

    # Get prediction
    prediction = estimator.predict(story)

    # Normalize confidence from percentage (0-100) to fraction (0-1)
    confidence_frac = prediction.get("confidence_pct", 0) / 100.0

    return {
        "tokens": prediction.get("estimated_tokens", 0),
        "cost_usd": prediction.get("estimated_cost", 0.0),
        "confidence": confidence_frac,
        "similar_stories": prediction.get("similar_stories", []),
    }
