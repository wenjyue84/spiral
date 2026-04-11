#!/usr/bin/env python3
"""lib/routing/ucb1_select.py — UCB1-based model selection from results.tsv history.

Uses the Upper Confidence Bound (UCB1) algorithm to recommend the best Claude model
based on historical pass rates grouped by (model, story_tag).

UCB1 formula: score = wins/attempts + sqrt(2 * ln(total) / attempts)

Usage:
  python lib/routing/ucb1_select.py --results-tsv results.tsv --story-tag "[Regression Test]"
  python lib/routing/ucb1_select.py --results-tsv results.tsv --story-tag "[Security Test]"
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def extract_story_tag(title: str) -> str:
    """Extract the first [Tag] from a story title.

    Examples:
        "[Regression Test] CLI: check-federated-deps" -> "[Regression Test]"
        "[Security Test] Auth Control" -> "[Security Test]"
        "Regular Story Title" -> ""
    """
    match = re.match(r"(\[.+?\])", title)
    return match.group(1) if match else ""


def parse_results_tsv(tsv_path: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Parse results.tsv and group by (model, story_tag).

    Returns:
        {
            ("haiku", "[Regression Test]"): {"wins": 5, "attempts": 10, ...},
            ("sonnet", "[Regression Test]"): {"wins": 8, "attempts": 12, ...},
            ...
        }
    """
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"wins": 0, "attempts": 0})

    if not Path(tsv_path).exists():
        return groups

    try:
        with open(tsv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                if not row or not row.get("story_title"):
                    continue
                title = row["story_title"]
                model = row.get("model", "").strip()
                status = row.get("status", "").strip().lower()

                if not model:
                    continue

                tag = extract_story_tag(title)
                # If no explicit tag, use "untagged"
                tag = tag or "untagged"

                key = (model, tag)
                groups[key]["attempts"] += 1
                if status == "pass":
                    groups[key]["wins"] += 1
    except Exception as e:
        print(f"[ucb1] ERROR parsing {tsv_path}: {e}", file=sys.stderr)
        return groups

    return groups


def calculate_ucb1_score(
    model: str,
    tag: str,
    groups: dict[tuple[str, str], dict[str, Any]],
    min_attempts: int = 2,
) -> float:
    """Calculate UCB1 score for a (model, tag) pair.

    UCB1 = wins/attempts + sqrt(2 * ln(total_attempts) / attempts)

    Penalizes models with <min_attempts attempts to avoid overfitting to noise.
    """
    key = (model, tag)
    if key not in groups:
        return -1.0  # Unknown model+tag pair

    data = groups[key]
    attempts = data["attempts"]
    wins = data["wins"]

    # Penalize models with too few attempts
    if attempts < min_attempts:
        return -0.5

    # Win rate (exploitation term)
    exploit = wins / attempts if attempts > 0 else 0.0

    # Total number of attempts across all groups for this tag
    total_attempts: int = sum(g["attempts"] for (m, t), g in groups.items() if t == tag)

    # Exploration term (boost uncertainty)
    explore = math.sqrt(2.0 * math.log(total_attempts) / attempts) if total_attempts > 0 and attempts > 0 else 0.0

    return exploit + explore


def select_best_model(tag: str, groups: dict[tuple[str, str], dict[str, Any]]) -> str | None:
    """Select the best model for a given story tag using UCB1.

    Returns the model with the highest UCB1 score, or None if no valid models.
    """
    models = set(m for m, t in groups.keys() if t == tag)
    if not models:
        return None

    scores = {model: calculate_ucb1_score(model, tag, groups) for model in models}
    # Filter out penalty scores
    valid_scores = {m: s for m, s in scores.items() if s >= 0.0}

    if not valid_scores:
        return None

    best_model = max(valid_scores, key=lambda m: valid_scores[m])
    return best_model


def main() -> None:
    parser = argparse.ArgumentParser(description="UCB1-based model selection from results.tsv")
    parser.add_argument("--results-tsv", required=True, help="Path to results.tsv file")
    parser.add_argument(
        "--story-tag",
        required=True,
        help="Story tag to recommend model for (e.g., '[Regression Test]')",
    )
    args = parser.parse_args()

    groups = parse_results_tsv(args.results_tsv)
    best_model = select_best_model(args.story_tag, groups)

    if best_model:
        print(best_model)
        sys.exit(0)
    else:
        # Fallback to sonnet if no data
        print("sonnet")
        sys.exit(0)


if __name__ == "__main__":
    main()
