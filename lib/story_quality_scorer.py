#!/usr/bin/env python3
"""
lib/story_quality_scorer.py — Score AI-generated stories against the constitution

Scores stories (0-100) based on:
  1. Production value principle (Tier 1: user-facing? visible? demonstrable?)
  2. Constitution alignment (non-negotiable rules followed?)
  3. Acceptance criteria quality (clear, measurable, testable?)
  4. Scope clarity (well-scoped or too ambitious?)

Stories below SPIRAL_AI_SUGGEST_MIN_SCORE are filtered out before Phase S validation.
"""

import json
from pathlib import Path
from typing import Any, TypedDict


class ScoringBreakdown(TypedDict):
    """Breakdown of a story's quality score."""

    total_score: float
    production_value: float
    constitution_alignment: float
    acceptance_criteria_quality: float
    scope_clarity: float
    reasons: list[str]


def load_constitution(constitution_path: str) -> str:
    """Load constitution.md content."""
    try:
        with open(constitution_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def score_production_value(story: dict[str, Any], endgame: bool = False) -> tuple[float, list[str]]:
    """Score production value based on Tier 1-4 principles.

    Tier 1 (highest): User-facing, visible, demonstrable, reduces API spend
    Tier 2: Reliability, correctness, crash recovery
    Tier 3: Power user features, CLI flags, config options
    Tier 4: Infrastructure, observability (lowest)

    In endgame mode (>90% stories complete), Tier 4 infrastructure stories are
    elevated to 40.0 (the passing floor) since hardening work IS high-priority
    at the end of a project.
    """
    reasons: list[str] = []
    base_score = 40.0  # Default: medium

    title = (story.get("title") or "").lower()
    description = (story.get("description") or "").lower()
    tags = [t.lower() for t in (story.get("tags") or [])]

    # Negative indicators: internal-only, no user-facing value
    tier4_keywords = [
        "observability",
        "telemetry",
        "infrastructure",
        "ci/cd",
        "internal",
        "format",
        "structure",
    ]
    if any(kw in description for kw in tier4_keywords):
        if endgame:
            reasons.append("Story focuses on infrastructure/observability (Tier 4) — elevated in endgame mode")
            return 40.0, reasons  # Elevated: infra IS high priority at project completion
        reasons.append("Story focuses on infrastructure/observability (Tier 4)")
        return 20.0, reasons

    # Positive indicators: Tier 1 (highest)
    tier1_keywords = [
        "dashboard",
        "ui",
        "terminal",
        "user",
        "speed",
        "performance",
        "error",
        "failure",
        "reduction",
        "cost",
    ]
    if any(kw in description for kw in tier1_keywords):
        reasons.append("Story has user-facing impact (Tier 1)")
        return 90.0, reasons

    # Tier 2 indicators: reliability, correctness
    tier2_keywords = ["reliability", "crash", "recovery", "integrity", "correct"]
    if any(kw in description for kw in tier2_keywords):
        reasons.append("Story improves reliability/correctness (Tier 2)")
        return 75.0, reasons

    # Tier 3 indicators: power user, configuration
    tier3_keywords = ["feature", "flag", "config", "option", "control"]
    if any(kw in description for kw in tier3_keywords):
        reasons.append("Story adds power user features (Tier 3)")
        return 60.0, reasons

    reasons.append("Story has moderate user-facing impact (Tier 3)")
    return base_score, reasons


def score_constitution_alignment(story: dict[str, Any], constitution_text: str) -> tuple[float, list[str]]:
    """Score alignment with constitution non-negotiable rules.

    Constitution defines:
      - Phase ordering (must not skip phases)
      - Quality gates (must not remove/bypass)
      - Dependencies (story atomicity)
      - Backwards compatibility
      - Token efficiency
    """
    reasons: list[str] = []
    base_score = 50.0

    description = (story.get("description") or "").lower()
    technical_notes = " ".join(story.get("technicalNotes") or []).lower()
    full_text = description + " " + technical_notes

    # Red flags: violate constitution
    red_flags = [
        ("skip phase", "bypasses phase ordering"),
        ("remove", "removes existing functionality"),
        ("bypass", "attempts to bypass quality gates"),
        ("hard dependency", "adds hard dependencies not in setup.sh"),
    ]
    violation_count = 0
    for flag, reason_text in red_flags:
        if flag in full_text:
            reasons.append(f"Constitution violation: {reason_text}")
            violation_count += 1

    if violation_count > 0:
        return 10.0, reasons

    # Green flags: align with constitution
    green_flags = [
        ("improving existing phases", "improves existing phases"),
        ("optional capabilities", "adds optional capabilities"),
        ("env var", "uses env var flags"),
        ("test coverage", "expands test coverage"),
        ("bug fix", "fixes existing bugs"),
        ("documentation", "improves documentation"),
    ]
    alignment_count = 0
    for flag, reason_text in green_flags:
        if flag in full_text:
            reasons.append(f"Aligns with constitution: {reason_text}")
            alignment_count += 1

    if alignment_count >= 2:
        return 85.0, reasons
    elif alignment_count == 1:
        return 70.0, reasons

    reasons.append("Story does not clearly violate or align with constitution")
    return base_score, reasons


def score_acceptance_criteria_quality(
    story: dict[str, Any],
) -> tuple[float, list[str]]:
    """Score acceptance criteria for clarity, measurability, testability."""
    reasons: list[str] = []

    acs = story.get("acceptanceCriteria") or []
    if not acs:
        reasons.append("No acceptance criteria defined")
        return 20.0, reasons

    ac_count = len(acs)

    # Check each AC for quality markers
    clear_count = 0
    measurable_count = 0
    testable_count = 0

    test_keywords = ["test", "verify", "unit test", "integration test"]
    measurable_keywords = ["count", "number", "percentage", "score", "time"]
    unclear_patterns = ["maybe", "consider", "could", "might"]

    for ac in acs:
        ac_lower = str(ac).lower()

        # Measure clarity (absence of vague language)
        if not any(p in ac_lower for p in unclear_patterns):
            clear_count += 1

        # Measure measurability
        if any(kw in ac_lower for kw in measurable_keywords):
            measurable_count += 1

        # Measure testability
        if any(kw in ac_lower for kw in test_keywords):
            testable_count += 1

    clarity_ratio = clear_count / ac_count if ac_count > 0 else 0
    measurability_ratio = measurable_count / ac_count if ac_count > 0 else 0
    testability_ratio = testable_count / ac_count if ac_count > 0 else 0

    # Calculate score
    score = 40.0 + (clarity_ratio * 20) + (measurability_ratio * 20) + (testability_ratio * 20)

    reasons.append(f"Acceptance criteria count: {ac_count}")
    if clarity_ratio >= 0.75:
        reasons.append("ACs are clear and concrete")
    if measurability_ratio >= 0.5:
        reasons.append("ACs have measurable outcomes")
    if testability_ratio >= 0.5:
        reasons.append("ACs are testable")

    return min(score, 100.0), reasons


def score_scope_clarity(story: dict[str, Any]) -> tuple[float, list[str]]:
    """Score scope clarity: well-scoped vs. too ambitious."""
    reasons: list[str] = []

    complexity = story.get("estimatedComplexity", "").lower()
    acs = len(story.get("acceptanceCriteria") or [])
    description_len = len(story.get("description") or "")

    score = 50.0

    # Complexity alignment with ACs
    if complexity == "small":
        if acs <= 2:
            score = 85.0
            reasons.append("Small story with limited ACs (well-scoped)")
        elif acs <= 4:
            score = 70.0
            reasons.append("Small story with moderate ACs")
        else:
            score = 40.0
            reasons.append("Small story with many ACs (scope creep)")
    elif complexity == "medium":
        if acs <= 5:
            score = 85.0
            reasons.append("Medium story with proportional ACs (well-scoped)")
        elif acs <= 8:
            score = 65.0
            reasons.append("Medium story with many ACs")
        else:
            score = 35.0
            reasons.append("Medium story with excessive ACs (scope overflow)")
    elif complexity == "large":
        if acs <= 8:
            score = 75.0
            reasons.append("Large story with reasonable ACs")
        else:
            score = 50.0
            reasons.append("Large story with many ACs (needs decomposition?)")

    # Description clarity
    if description_len < 100:
        score -= 10
        reasons.append("Description too brief (may lack clarity)")
    elif description_len > 500:
        score -= 10
        reasons.append("Description too long (may indicate scope creep)")

    return min(score, 100.0), reasons


def score_story(story: dict[str, Any], constitution_text: str = "", endgame: bool = False) -> ScoringBreakdown:
    """Score a story across all dimensions."""
    production_score, pv_reasons = score_production_value(story, endgame=endgame)
    constitution_score, ca_reasons = score_constitution_alignment(story, constitution_text)
    ac_score, ac_reasons = score_acceptance_criteria_quality(story)
    scope_score, scope_reasons = score_scope_clarity(story)

    # Weight the dimensions
    weights = {
        "production_value": 0.35,
        "constitution_alignment": 0.25,
        "acceptance_criteria_quality": 0.25,
        "scope_clarity": 0.15,
    }

    total_score = (
        production_score * weights["production_value"]
        + constitution_score * weights["constitution_alignment"]
        + ac_score * weights["acceptance_criteria_quality"]
        + scope_score * weights["scope_clarity"]
    )

    all_reasons = pv_reasons + ca_reasons + ac_reasons + scope_reasons

    return ScoringBreakdown(
        total_score=round(total_score, 1),
        production_value=round(production_score, 1),
        constitution_alignment=round(constitution_score, 1),
        acceptance_criteria_quality=round(ac_score, 1),
        scope_clarity=round(scope_score, 1),
        reasons=all_reasons,
    )


def filter_stories(
    stories: list[dict[str, Any]],
    min_score: float = 40,
    constitution_text: str = "",
    endgame: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[str, float, list[str]]]]:
    """Filter stories by quality score.

    Returns:
        (passing_stories, filtered_stories)
        filtered_stories is list of (story_id, score, reasons)
    """
    passing: list[dict[str, Any]] = []
    filtered: list[tuple[str, float, list[str]]] = []

    for story in stories:
        breakdown = score_story(story, constitution_text, endgame=endgame)
        story_id = story.get("id", "unknown")

        if breakdown["total_score"] >= min_score:
            passing.append(story)
        else:
            filtered.append((story_id, breakdown["total_score"], breakdown["reasons"]))

    return passing, filtered


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Score and filter stories by quality")
    parser.add_argument("--prd", required=True, help="Path to prd.json")
    parser.add_argument("--input", required=True, help="Path to input stories JSON")
    parser.add_argument("--output", required=True, help="Path to output filtered stories JSON")
    parser.add_argument("--min-score", type=float, default=40, help="Minimum quality score")
    parser.add_argument(
        "--constitution",
        help="Path to constitution.md (optional)",
    )
    parser.add_argument("--log", help="Path to log filtered stories")
    parser.add_argument(
        "--endgame",
        action="store_true",
        help="Endgame mode: elevate Tier 4 infrastructure story scores (for use when >90%% stories complete)",
    )

    args = parser.parse_args()

    # Load constitution
    constitution_text = ""
    if args.constitution and Path(args.constitution).exists():
        constitution_text = load_constitution(args.constitution)

    # Load stories
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            input_data = json.load(f)
    except FileNotFoundError:
        # No input file, return empty output
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
        return

    stories = input_data if isinstance(input_data, list) else input_data.get("stories", [])
    passing, filtered = filter_stories(stories, args.min_score, constitution_text, endgame=args.endgame)

    # Write output
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(passing, f, indent=2)

    # Write log
    if args.log and filtered:
        with open(args.log, "w", encoding="utf-8") as f:
            for story_id, score, reasons in filtered:
                f.write(f"{story_id}: {score}/100 (filtered)\n")
                for reason in reasons:
                    f.write(f"  - {reason}\n")

    # Summary
    print(f"Filtered stories: {len(stories)} -> {len(passing)} passing (min score: {args.min_score})")
    if filtered:
        print(f"Rejected {len(filtered)} stories below threshold:")
        for story_id, score, reasons in filtered:
            print(f"  {story_id}: {score}/100")


if __name__ == "__main__":
    main()
