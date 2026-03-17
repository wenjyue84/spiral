"""Deterministic and model-graded rubric checkers for SPIRAL evals."""

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class GradeResult:
    """Result of a single grading evaluation."""

    passed: bool
    score: float  # 0.0 to 1.0
    reasoning: str


def check_valid_json(output: str) -> GradeResult:
    """Check if output contains valid JSON."""
    try:
        json.loads(output)
        return GradeResult(passed=True, score=1.0, reasoning="Valid JSON found")
    except json.JSONDecodeError as e:
        return GradeResult(passed=False, score=0.0, reasoning=f"Invalid JSON: {e}")


def check_required_fields(output: str, required_fields: List[str]) -> GradeResult:
    """Check if JSON output contains all required fields."""
    try:
        data = json.loads(output)
        missing = [f for f in required_fields if f not in data]
        if missing:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Missing required fields: {missing}",
            )
        return GradeResult(passed=True, score=1.0, reasoning="All required fields present")
    except json.JSONDecodeError as e:
        return GradeResult(passed=False, score=0.0, reasoning=f"Invalid JSON: {e}")


def check_regex_match(output: str, pattern: str, required: bool = True) -> GradeResult:
    """Check if output matches regex pattern."""
    try:
        match = re.search(pattern, output, re.MULTILINE | re.DOTALL)
        if required and not match:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Pattern not found: {pattern}",
            )
        elif not required and match:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Pattern should not be found: {pattern}",
            )
        return GradeResult(
            passed=True,
            score=1.0,
            reasoning=f"Pattern match successful: {pattern}",
        )
    except re.error as e:
        return GradeResult(passed=False, score=0.0, reasoning=f"Regex error: {e}")


def check_list_length(output: str, min_length: int = 0, max_length: Optional[int] = None) -> GradeResult:
    """Check if JSON array has expected length."""
    try:
        data = json.loads(output)
        if not isinstance(data, list):
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning="Output is not a JSON array",
            )
        length = len(data)
        if length < min_length:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Array too short: {length} < {min_length}",
            )
        if max_length is not None and length > max_length:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Array too long: {length} > {max_length}",
            )
        return GradeResult(
            passed=True,
            score=1.0,
            reasoning=f"Array length {length} within bounds",
        )
    except json.JSONDecodeError as e:
        return GradeResult(passed=False, score=0.0, reasoning=f"Invalid JSON: {e}")


def check_string_contains(output: str, substrings: List[str], all_required: bool = True) -> GradeResult:
    """Check if output contains substrings."""
    found = [s for s in substrings if s in output]
    missing = [s for s in substrings if s not in output]

    if all_required and missing:
        return GradeResult(
            passed=False,
            score=len(found) / len(substrings),
            reasoning=f"Missing substrings: {missing}",
        )

    if not all_required and not found:
        return GradeResult(
            passed=False,
            score=0.0,
            reasoning="None of the expected substrings found",
        )

    return GradeResult(
        passed=True,
        score=min(1.0, len(found) / len(substrings)) if substrings else 1.0,
        reasoning=f"Found {len(found)}/{len(substrings)} expected substrings",
    )


def check_no_errors(output: str, error_keywords: Optional[List[str]] = None) -> GradeResult:
    """Check that output doesn't contain error indicators."""
    if error_keywords is None:
        error_keywords = ["error", "exception", "traceback", "failed", "invalid"]

    found_errors = [kw for kw in error_keywords if kw.lower() in output.lower()]

    if found_errors:
        return GradeResult(
            passed=False,
            score=0.0,
            reasoning=f"Found error keywords: {found_errors}",
        )

    return GradeResult(
        passed=True,
        score=1.0,
        reasoning="No error keywords detected",
    )


class DeterministicGrader:
    """Runner for deterministic grading criteria."""

    CHECKERS: Dict[str, Callable[..., GradeResult]] = {
        "valid_json": check_valid_json,
        "required_fields": check_required_fields,
        "regex_match": check_regex_match,
        "list_length": check_list_length,
        "string_contains": check_string_contains,
        "no_errors": check_no_errors,
    }

    @classmethod
    def grade(cls, output: str, criteria: Dict[str, Any]) -> GradeResult:
        """Apply deterministic grading criteria."""
        checker_type = criteria.get("type")
        if checker_type not in cls.CHECKERS:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Unknown checker type: {checker_type}",
            )

        checker = cls.CHECKERS[checker_type]
        try:
            # Pass all params except 'type' to the checker
            params = {k: v for k, v in criteria.items() if k != "type"}
            return checker(output, **params)
        except TypeError as e:
            return GradeResult(
                passed=False,
                score=0.0,
                reasoning=f"Invalid parameters for {checker_type}: {e}",
            )


class ModelGradedRubric:
    """Placeholder for model-graded rubric (future LLM-judge implementation)."""

    @staticmethod
    def grade(output: str, rubric: Dict[str, Any], _model: Optional[str] = None) -> GradeResult:
        """Grade using LLM-based rubric. Currently returns placeholder."""
        # In a full implementation, this would use an LLM to grade based on rubric
        # For now, return a warning that model-grading is not yet implemented
        return GradeResult(
            passed=False,
            score=0.0,
            reasoning="Model-graded rubric not yet implemented (placeholder)",
        )
