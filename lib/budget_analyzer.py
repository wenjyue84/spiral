#!/usr/bin/env python3
"""
budget_analyzer.py — Calculate current spend and estimate pending story costs.

Provides utilities to:
  - Parse results.tsv and calculate total tokens/cost spent
  - Estimate tokens/cost for pending stories in prd.json
  - Support Phase I budget gate decisions
"""

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

sys.path.insert(0, os.path.dirname(__file__))
from constants import DEFAULT_TOKENS_PER_STORY, INPUT_OUTPUT_RATIO, PRICING, TOKENS_PER_SEC_OUTPUT


class SpendResult(TypedDict):
    """Result of calculate_current_spend."""

    total_tokens: float
    total_cost_usd: float
    by_model: Dict[str, float]
    row_count: int


class EstimateResult(TypedDict):
    """Result of estimate_pending_story_cost."""

    total_cost_usd: float
    total_tokens: float
    by_model: Dict[str, float]
    story_count: int
    by_story: List[Tuple[str, float]]


class BudgetCheckResult(TypedDict):
    """Result of check_budget_gate."""

    would_exceed: bool
    current_spend_usd: float
    estimated_pending_usd: float
    total_projected_usd: float
    ceiling_usd: Optional[float]
    remaining_budget_usd: float
    pending_count: int


def _total_tokens_from_duration(duration_sec: float) -> float:
    """Total (input + output) tokens estimated from wall-clock duration."""
    output = duration_sec * float(TOKENS_PER_SEC_OUTPUT)
    input_ = output * float(INPUT_OUTPUT_RATIO)
    return float(input_ + output)


def _cost_per_token(model: str) -> float:
    """Cost in USD per input token for the given model (pricing is per million tokens)."""
    model_norm = model.lower() if model else ""
    for key in PRICING:
        if key in model_norm:
            input_cost = float(PRICING[key]["input"])
            return input_cost / 1_000_000.0
    sonnet_pricing = PRICING.get("sonnet", {"input": 0.003})
    sonnet_cost = float(sonnet_pricing.get("input", 0.003))
    return sonnet_cost / 1_000_000.0


def calculate_current_spend(results_tsv: Path) -> SpendResult:
    """
    Parse results.tsv and calculate total tokens and cost spent.

    Args:
        results_tsv: Path to results.tsv file

    Returns:
        dict with keys:
          - total_tokens: sum of all token counts
          - total_cost_usd: sum of all costs
          - by_model: dict of model -> cost
          - row_count: number of result rows processed
    """
    total_tokens = 0.0
    total_cost_usd = 0.0
    by_model: Dict[str, float] = {}
    row_count = 0

    if not results_tsv.exists():
        return SpendResult(
            total_tokens=0.0,
            total_cost_usd=0.0,
            by_model={},
            row_count=0,
        )

    try:
        with open(results_tsv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                return {
                    "total_tokens": 0.0,
                    "total_cost_usd": 0.0,
                    "by_model": {},
                    "row_count": 0,
                }

            for row in reader:
                if not row.get("duration_sec") or not row.get("model"):
                    continue

                try:
                    duration = float(row["duration_sec"])
                    model = row["model"].strip()
                    if duration <= 0 or not model:
                        continue

                    tokens = _total_tokens_from_duration(duration)
                    cost_per_tok = _cost_per_token(model)
                    cost = tokens * cost_per_tok

                    total_tokens += tokens
                    total_cost_usd += cost

                    if model not in by_model:
                        by_model[model] = 0.0
                    by_model[model] += cost

                    row_count += 1
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass

    return SpendResult(
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
        by_model=by_model,
        row_count=row_count,
    )


def estimate_pending_story_cost(
    prd_dict: Dict[str, Any], velocity_model: Optional[Dict[str, Any]] = None
) -> EstimateResult:
    """
    Estimate total cost for all pending stories in prd.json.

    Args:
        prd_dict: parsed prd.json
        velocity_model: optional velocity model with story_types -> {mean_cost, ...}

    Returns:
        dict with keys:
          - total_cost_usd: estimated cost for all pending stories
          - total_tokens: estimated tokens
          - by_model: estimated cost by model assignment
          - story_count: number of pending stories counted
          - by_story: list of (story_id, estimated_cost) tuples
    """
    pending_stories = [s for s in prd_dict.get("userStories", []) if s.get("passes") != True]

    total_cost = 0.0
    total_tokens = 0.0
    by_model: Dict[str, float] = {}
    by_story: List[Tuple[str, float]] = []

    for story in pending_stories:
        story_id = story.get("id", "unknown")
        model = story.get("model", "sonnet").lower()

        # Try to estimate from velocity model first
        if velocity_model and "story_types" in velocity_model:
            story_type = _classify_story_type(story.get("title", ""))
            type_data = velocity_model["story_types"].get(story_type)
            if type_data and type_data.get("mean_cost"):
                cost = type_data["mean_cost"]
                tokens = type_data.get("mean_tokens", DEFAULT_TOKENS_PER_STORY)
                total_cost += cost
                total_tokens += tokens
                if model not in by_model:
                    by_model[model] = 0.0
                by_model[model] += cost
                by_story.append((story_id, cost))
                continue

        # Fallback: use default tokens per story
        tokens = DEFAULT_TOKENS_PER_STORY
        cost_per_tok = _cost_per_token(model)
        cost = tokens * cost_per_tok
        total_cost += cost
        total_tokens += tokens
        if model not in by_model:
            by_model[model] = 0.0
        by_model[model] += cost
        by_story.append((story_id, cost))

    return EstimateResult(
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        by_model=by_model,
        story_count=len(pending_stories),
        by_story=by_story,
    )


def _classify_story_type(title: str) -> str:
    """Simple heuristic to classify story type from title."""
    title_lower = (title or "").lower()
    if "test" in title_lower or "integration" in title_lower:
        return "test"
    if "fix" in title_lower or "bug" in title_lower:
        return "bug_fix"
    if "add" in title_lower or "implement" in title_lower:
        return "implementation"
    if "refactor" in title_lower:
        return "refactoring"
    return "other"


def check_budget_gate(
    prd_file: Path,
    results_tsv: Path,
    cost_ceiling_usd: Optional[float] = None,
    velocity_model_file: Optional[Path] = None,
) -> BudgetCheckResult:
    """
    Check if implementing all pending stories would exceed budget.

    Args:
        prd_file: path to prd.json
        results_tsv: path to results.tsv
        cost_ceiling_usd: budget ceiling in USD (or None to skip check)
        velocity_model_file: optional path to velocity model JSON

    Returns:
        dict with keys:
          - would_exceed: bool, whether total would exceed ceiling
          - current_spend_usd: float, amount already spent
          - estimated_pending_usd: float, estimated cost for pending
          - total_projected_usd: float, current + estimated
          - ceiling_usd: float, the ceiling value
          - remaining_budget_usd: float, ceiling - current
          - pending_count: int, number of pending stories
    """
    if cost_ceiling_usd is None or cost_ceiling_usd <= 0:
        return BudgetCheckResult(
            would_exceed=False,
            current_spend_usd=0.0,
            estimated_pending_usd=0.0,
            total_projected_usd=0.0,
            ceiling_usd=cost_ceiling_usd,
            remaining_budget_usd=cost_ceiling_usd or 0.0,
            pending_count=0,
        )

    # Load PRD
    try:
        with open(prd_file, "r", encoding="utf-8") as f:
            prd_dict = json.load(f)
    except Exception as e:
        raise ValueError(f"Cannot read prd.json: {e}")

    # Load velocity model if provided
    velocity_model = None
    if velocity_model_file and velocity_model_file.exists():
        try:
            with open(velocity_model_file, "r", encoding="utf-8") as f:
                velocity_model = json.load(f)
        except Exception:
            pass

    # Calculate spend and estimate
    current = calculate_current_spend(results_tsv)
    pending = estimate_pending_story_cost(prd_dict, velocity_model)

    total_projected = current["total_cost_usd"] + pending["total_cost_usd"]
    would_exceed = total_projected > cost_ceiling_usd
    remaining = max(0.0, cost_ceiling_usd - current["total_cost_usd"])

    return BudgetCheckResult(
        would_exceed=would_exceed,
        current_spend_usd=current["total_cost_usd"],
        estimated_pending_usd=pending["total_cost_usd"],
        total_projected_usd=total_projected,
        ceiling_usd=cost_ceiling_usd,
        remaining_budget_usd=remaining,
        pending_count=pending["story_count"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check budget gate for SPIRAL Phase I")
    parser.add_argument("--prd", type=Path, default="prd.json")
    parser.add_argument("--results", type=Path, default="results.tsv")
    parser.add_argument("--ceiling", type=float, help="Cost ceiling in USD")
    parser.add_argument("--velocity-model", type=Path, help="Path to velocity model JSON")
    args = parser.parse_args()

    result = check_budget_gate(
        args.prd,
        args.results,
        cost_ceiling_usd=args.ceiling,
        velocity_model_file=args.velocity_model,
    )
    print(json.dumps(result, indent=2))
