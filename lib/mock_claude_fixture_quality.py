"""Mock Claude fixture quality assurance utilities.

Validates that mock Claude responses realistically simulate API behavior:
- Token estimates match real API within ±5%
- Error conditions present per phase (TimeoutError, RateLimitError, InvalidRequestError)
- Coverage across all phases (R, T, S, M, I, V, C) with ≥2 error scenarios each
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class TokenExpectation:
    """Token count expectations for a phase."""

    phase_id: str
    expected_input: int
    expected_output: int

    def validate(self, actual_input: int, actual_output: int) -> tuple[bool, str]:
        """Check if actual tokens are within ±5% of expected.

        Args:
            actual_input: Actual input tokens used
            actual_output: Actual output tokens used

        Returns:
            (is_valid, message)
        """
        tol = 0.05  # ±5%

        input_min = int(self.expected_input * (1 - tol))
        input_max = int(self.expected_input * (1 + tol))
        output_min = int(self.expected_output * (1 - tol))
        output_max = int(self.expected_output * (1 + tol))

        input_ok = input_min <= actual_input <= input_max
        output_ok = output_min <= actual_output <= output_max

        if not input_ok:
            msg = (
                f"Input tokens out of range: {actual_input} "
                f"(expected ~{self.expected_input}, range {input_min}-{input_max})"
            )
            return False, msg
        if not output_ok:
            msg = (
                f"Output tokens out of range: {actual_output} "
                f"(expected ~{self.expected_output}, range {output_min}-{output_max})"
            )
            return False, msg

        return True, "OK"


# Phase-specific token expectations (based on observed real API patterns)
PHASE_TOKEN_EXPECTATIONS = {
    "R": TokenExpectation(phase_id="R", expected_input=1000, expected_output=2000),
    "T": TokenExpectation(phase_id="T", expected_input=300, expected_output=600),
    "S": TokenExpectation(phase_id="S", expected_input=750, expected_output=400),
    "M": TokenExpectation(phase_id="M", expected_input=400, expected_output=200),
    "I": TokenExpectation(phase_id="I", expected_input=2000, expected_output=3000),
    "V": TokenExpectation(phase_id="V", expected_input=300, expected_output=300),
    "C": TokenExpectation(phase_id="C", expected_input=150, expected_output=150),
}

# Error types that should be present in mock fixtures
REQUIRED_ERROR_TYPES = ["TimeoutError", "RateLimitError", "InvalidRequestError"]

# Phases that must have mocks with error scenarios
REQUIRED_PHASES = ["R", "T", "S", "M", "I", "V", "C"]


@dataclass
class MockFixtureIssue:
    """Represents a gap in mock fixture coverage."""

    phase_id: str
    issue_type: str  # "missing_phase", "insufficient_errors", "unrealistic_tokens"
    message: str


def flag_fixture_issues(
    mock_responses: dict[str, Any],
) -> list[MockFixtureIssue]:
    """Detect gaps in mock fixture coverage.

    Args:
        mock_responses: Dict mapping phase_id to list of mock response dicts
                       Each response should have: {tokens: {input: N, output: M}, error_type: str or None}

    Returns:
        List of MockFixtureIssue objects for each gap found
    """
    issues: list[MockFixtureIssue] = []

    # Check all required phases are present
    for phase in REQUIRED_PHASES:
        if phase not in mock_responses or not mock_responses[phase]:
            issues.append(
                MockFixtureIssue(
                    phase_id=phase,
                    issue_type="missing_phase",
                    message=f"Phase {phase} has no mock responses",
                )
            )
            continue

        responses = mock_responses[phase]

        # Check error type coverage (≥2 per phase)
        error_types = set()
        for resp in responses:
            if resp.get("error_type"):
                error_types.add(resp["error_type"])

        if len(error_types) < 2:
            issues.append(
                MockFixtureIssue(
                    phase_id=phase,
                    issue_type="insufficient_errors",
                    message=f"Phase {phase} has only {len(error_types)} error types (need ≥2)",
                )
            )

        # Verify all required error types are represented
        missing_errors = set(REQUIRED_ERROR_TYPES) - error_types
        if missing_errors:
            issues.append(
                MockFixtureIssue(
                    phase_id=phase,
                    issue_type="insufficient_errors",
                    message=f"Phase {phase} missing error types: {', '.join(missing_errors)}",
                )
            )

        # Check token counts are realistic
        expectation = PHASE_TOKEN_EXPECTATIONS.get(phase)
        if expectation:
            for i, resp in enumerate(responses):
                tokens = resp.get("tokens", {})
                actual_input = tokens.get("input", 0)
                actual_output = tokens.get("output", 0)

                if actual_input and actual_output:
                    is_valid, msg = expectation.validate(actual_input, actual_output)
                    if not is_valid:
                        issues.append(
                            MockFixtureIssue(
                                phase_id=phase,
                                issue_type="unrealistic_tokens",
                                message=f"Response {i}: {msg}",
                            )
                        )

    return issues


def calculate_coverage_score(mock_responses: dict[str, Any]) -> float:
    """Calculate overall fixture quality coverage score (0-100).

    Scoring:
    - 100/7 points per phase present
    - -5 points per missing error scenario (max 2 per phase)
    - -10 points per unrealistic token count

    Args:
        mock_responses: Dict mapping phase_id to list of mock responses

    Returns:
        Coverage score (0-100)
    """
    score = 0.0
    points_per_phase = 100.0 / len(REQUIRED_PHASES)

    for phase in REQUIRED_PHASES:
        if phase not in mock_responses or not mock_responses[phase]:
            continue

        score += points_per_phase

        responses = mock_responses[phase]

        # Check error coverage
        error_types = set()
        for resp in responses:
            if resp.get("error_type"):
                error_types.add(resp["error_type"])

        # Deduct for missing error types
        missing_count = len(REQUIRED_ERROR_TYPES) - len(error_types)
        if missing_count > 0:
            score -= missing_count * 5

        # Check token realism
        expectation = PHASE_TOKEN_EXPECTATIONS.get(phase)
        if expectation:
            for resp in responses:
                tokens = resp.get("tokens", {})
                actual_input = tokens.get("input", 0)
                actual_output = tokens.get("output", 0)

                if actual_input and actual_output:
                    is_valid, _ = expectation.validate(actual_input, actual_output)
                    if not is_valid:
                        score -= 10

    return max(0.0, min(100.0, score))


def validate_token_count(
    phase: str, actual_input: int, actual_output: int
) -> tuple[bool, str]:
    """Validate token count for a phase is within ±5% of expected.

    Args:
        phase: Phase ID (R, T, S, M, I, V, C)
        actual_input: Actual input tokens
        actual_output: Actual output tokens

    Returns:
        (is_valid, message)
    """
    expectation = PHASE_TOKEN_EXPECTATIONS.get(phase)
    if not expectation:
        return False, f"Unknown phase: {phase}"

    return expectation.validate(actual_input, actual_output)


def validate_error_coverage(phase: str, error_types: set[str]) -> tuple[bool, str]:
    """Validate error scenario coverage for a phase.

    Args:
        phase: Phase ID (R, T, S, M, I, V, C)
        error_types: Set of error type names present in mocks

    Returns:
        (is_valid, message)
    """
    if len(error_types) < 2:
        return False, f"Phase {phase} needs ≥2 error types, got {len(error_types)}"

    missing = set(REQUIRED_ERROR_TYPES) - error_types
    if missing:
        return (
            False,
            f"Phase {phase} missing error types: {', '.join(missing)}",
        )

    return True, "OK"
