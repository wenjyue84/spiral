# lib/route_stories.py
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from typing import Any, Optional

# Simple keyword-based fallback complexity classifier (no ML dependencies, instant)
_COMPLEX_PATTERNS = re.compile(
    r"\b(parallel|orchestrat|multi.agent|dag|dependency|migration|refactor|arch|"
    r"integrat|security|auth|oauth|webhook|crawl|scrape|stream|async|concurr|"
    r"distribut|circuit.break|retry|backoff|cache|shard|partition)\b",
    re.IGNORECASE,
)

# US-453: Regex-based complexity scoring patterns applied to acceptance criteria.
# Each tuple: (pattern, score_delta).  Matched against the concatenated AC text.
_SCORING_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bimplement as described\b", re.IGNORECASE), -20),
    (re.compile(r"\b(?:refactor|redesign)\b", re.IGNORECASE), 30),
    (re.compile(r"\badd tests?\b", re.IGNORECASE), 10),
    (re.compile(r"\bintegrat", re.IGNORECASE), 20),
    (re.compile(r"\bmultiple\b", re.IGNORECASE), 15),
    (re.compile(r"\b(?:parallel|concurrent|async)\b", re.IGNORECASE), 20),
    (re.compile(r"\b(?:security|auth|oauth)\b", re.IGNORECASE), 15),
    (re.compile(r"\b(?:migration|schema)\b", re.IGNORECASE), 15),
]


def score_story_complexity(story: dict[str, Any]) -> int:
    """Score a story's complexity (0-100) via regex on acceptance criteria.

    Base score is 30 (medium).  Each pattern match adds/subtracts points.
    Result is clamped to [0, 100].
    """
    ac_list = story.get("acceptanceCriteria", [])
    text = " ".join(ac_list) if ac_list else ""
    score = 30  # base
    for pattern, delta in _SCORING_PATTERNS:
        if pattern.search(text):
            score += delta
    return max(0, min(100, score))


def map_complexity_to_model(score: int) -> str:
    """Map a 0-100 complexity score to a model tier."""
    if score <= 40:
        return "haiku"
    elif score <= 75:
        return "sonnet"
    else:
        return "opus"


def _keyword_complexity(title: str) -> str:
    return "complex" if _COMPLEX_PATTERNS.search(title) else "simple"


def _try_load_semantic_router() -> Optional[Any]:
    """Load SemanticRouter with a 10-second timeout guard. Returns None on failure."""
    import threading

    result: list[Optional[Any]] = [None]
    error: list[Optional[Exception]] = [None]

    def _load() -> None:
        try:
            try:
                from .semantic_router import create_complexity_router
            except ImportError:
                from semantic_router import create_complexity_router  # type: ignore[no-redef]
            result[0] = create_complexity_router()
        except Exception as exc:
            error[0] = exc

    t = threading.Thread(target=_load, daemon=True)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        print("[router] WARNING: SemanticRouter load timed out (>10s) -- using keyword fallback")
        return None
    if error[0]:
        print(f"[router] WARNING: SemanticRouter unavailable ({error[0]}) -- using keyword fallback")
        return None
    return result[0]


def route_stories(prd_path: str, profile: str) -> None:
    """
    Analyzes each pending story in the PRD file and annotates it with a recommended model.
    Uses regex-based complexity scoring on acceptance criteria (US-453).
    """
    if not os.path.exists(prd_path):
        raise FileNotFoundError(f"[router] ERROR: PRD file not found at {prd_path}")

    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError:
        print(f"[router] ERROR: Could not decode JSON from {prd_path}")
        return

    stories_to_update = 0
    telemetry_events: list[dict[str, Any]] = []

    for story in prd.get("userStories", []):
        # Only route stories that are not yet done
        if story.get("passes") is not True:
            assigned_model = None
            complexity_score = score_story_complexity(story)
            if profile == "auto":
                # US-453: Use regex-based complexity scoring on acceptance criteria
                assigned_model = map_complexity_to_model(complexity_score)
                print(f"  [router] Story '{story.get('id')}' -> score: {complexity_score} -> model: {assigned_model}")
            else:
                # User forced a specific model (e.g., "opus", "sonnet", "haiku")
                assigned_model = profile
                print(f"  [router] Story '{story.get('id')}' -> profile: {profile} -> model: {assigned_model}")

            # US-455: Collect telemetry for emission after write
            telemetry_events.append(
                {
                    "story_id": story.get("id", "unknown"),
                    "complexity_score": complexity_score,
                    "model_tier": assigned_model,
                    "estimated_tokens": 0,
                }
            )

            if assigned_model and story.get("model") != assigned_model:
                story["model"] = assigned_model
                stories_to_update += 1

    if stories_to_update > 0:
        print(f"[router] Writing models for {stories_to_update} stories to {prd_path}...")
        # Atomic write to prevent corruption
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(prd_path))
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
                json.dump(prd, tf, indent=2)
            os.replace(temp_path, prd_path)
        except Exception as e:
            print(f"[router] ERROR: Failed to write updated PRD file: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
    else:
        print("[router] No story models needed updating.")

    # US-455: Emit routing telemetry events
    if telemetry_events:
        events_path = os.path.join(os.path.dirname(prd_path), "spiral_events.jsonl")
        try:
            from routing_telemetry import emit_routing_events

            emit_routing_events(events_path, telemetry_events)
        except ImportError:
            pass  # telemetry module not available -- skip silently


def main() -> None:
    parser = argparse.ArgumentParser(description="Route stories in prd.json to optimal models.")
    parser.add_argument("--prd", required=True, help="Path to the prd.json file.")
    parser.add_argument("--profile", required=True, help="The model routing profile (e.g., 'auto', 'opus', 'sonnet').")
    args = parser.parse_args()

    print("[router] Starting story routing...")
    route_stories(args.prd, args.profile)
    print("[router] Story routing complete.")


if __name__ == "__main__":
    main()
