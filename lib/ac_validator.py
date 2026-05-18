#!/usr/bin/env python3
"""
lib/ac_validator.py — AC (Acceptance Criteria) Validation

Detects and warns on incomplete acceptance criteria before story merge.
Checks for: empty AC lists, ACs with <5 words, ACs lacking technical specifics.

Adds _validation field to stories with warnings and risk levels (low/medium/high).
"""

import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ACValidationResult:
    """Result of validating a story's acceptance criteria."""

    story_id: str
    warnings: list[str]
    risk_level: str  # "low" | "medium" | "high"
    ac_count: int


def check_empty_acs(acs: list[str]) -> tuple[bool, str]:
    """Check if acceptance criteria list is empty."""
    if not acs or len(acs) == 0:
        return True, "Empty acceptance criteria list"
    return False, ""


def check_ac_word_count(acs: list[str]) -> list[str]:
    """Detect ACs with fewer than 5 words (likely incomplete)."""
    warnings = []
    for i, ac in enumerate(acs):
        word_count = len(ac.split())
        if word_count < 5:
            warnings.append(f"AC {i + 1} has only {word_count} words (< 5): '{ac[:50]}...'")
    return warnings


def detect_technical_references(acs: list[str]) -> list[str]:
    """Detect ACs lacking specific technical references (filenames, functions, test markers)."""
    warnings = []

    # Patterns for technical references
    patterns: dict[str, Callable[[str], bool]] = {
        "filename": lambda text: bool(re.search(r"\b[\w-]+\.(py|js|ts|tsx|jsx|sh|json|md|yaml|yml)\b", text)),
        "function": lambda text: bool(re.search(r"\b(def|function|class|interface)\s+\w+|(\w+\(\))|(\w+::\w+)", text)),
        "test": lambda text: bool(
            re.search(
                r"\b(test_\w+|spec_\w+|assert|expect|test:|should:|pytest|vitest|unittest|@test)",
                text,
                re.IGNORECASE,
            )
        ),
        "api_endpoint": lambda text: bool(re.search(r"(/\w+){2,}|/api/\w+", text)),
        "file_path": lambda text: bool(re.search(r"(src/|lib/|tests/|modules/|components/)", text)),
    }

    for i, ac in enumerate(acs):
        # Check if AC has any technical reference
        has_reference = any(check(ac) for check in patterns.values())
        if not has_reference:
            warnings.append(f"AC {i + 1} lacks technical reference (filename/function/test/endpoint): '{ac[:50]}...'")

    return warnings


def calculate_risk_level(warnings: list[str]) -> str:
    """Calculate risk level based on number and type of warnings."""
    if not warnings:
        return "low"
    if len(warnings) >= 3:
        return "high"
    if any("empty" in w.lower() for w in warnings):
        return "high"
    if len(warnings) >= 2:
        return "medium"
    return "low"


def validate_story_acs(story: dict[str, Any]) -> ACValidationResult:
    """Validate acceptance criteria for a single story."""
    story_id: str = story.get("id", "UNKNOWN")
    acs: list[str] = story.get("acceptanceCriteria", [])

    warnings: list[str] = []

    # Check for empty ACs
    is_empty, empty_msg = check_empty_acs(acs)
    if is_empty:
        warnings.append(empty_msg)

    # Check AC word count
    if acs:
        word_count_warnings = check_ac_word_count(acs)
        warnings.extend(word_count_warnings)

        # Check for technical references
        ref_warnings = detect_technical_references(acs)
        warnings.extend(ref_warnings)

    risk_level = calculate_risk_level(warnings)

    return ACValidationResult(
        story_id=story_id,
        warnings=warnings,
        risk_level=risk_level,
        ac_count=len(acs),
    )


def score_acceptance_criteria(prd_file: str) -> list[ACValidationResult]:
    """
    Score all acceptance criteria in a PRD file.

    Returns list of validation results, one per story with warnings.
    """
    try:
        with open(prd_file, "r", encoding="utf-8") as f:
            prd_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading PRD file: {e}", file=sys.stderr)
        return []

    stories: list[dict[str, Any]] = prd_data.get("userStories", [])
    results: list[ACValidationResult] = []

    for story in stories:
        result = validate_story_acs(story)
        if result.warnings:  # Only include stories with warnings
            results.append(result)

    return results


def main() -> int:
    """CLI entry point for AC validator."""
    if len(sys.argv) < 2:
        print("Usage: python -m lib.ac_validator <prd.json>", file=sys.stderr)
        return 1

    prd_file = sys.argv[1]
    results = score_acceptance_criteria(prd_file)

    # Print summary
    if results:
        risk_counts = {"low": 0, "medium": 0, "high": 0}
        for result in results:
            risk_counts[result.risk_level] += 1

        print(f"AC Validation: {len(results)} stories with incomplete ACs found")
        print(f"  Risk breakdown: high={risk_counts['high']}, medium={risk_counts['medium']}, low={risk_counts['low']}")

        # Print detailed warnings
        for result in results:
            print(f"\n{result.story_id} [{result.risk_level}] ({result.ac_count} ACs):")
            for warning in result.warnings:
                print(f"  - {warning}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
