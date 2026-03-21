"""Tests for mock Claude fixture quality assurance.

Validates that mock Claude responses realistically simulate API behavior:
- Token estimates match real API within ±5%
- Error conditions present per phase (TimeoutError, RateLimitError, InvalidRequestError)
- Coverage across all phases (R, T, S, M, I, V, C) with ≥2 error scenarios each
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

from lib.mock_claude_fixture_quality import (
    PHASE_TOKEN_EXPECTATIONS,
    REQUIRED_ERROR_TYPES,
    REQUIRED_PHASES,
    MockFixtureIssue,
    calculate_coverage_score,
    flag_fixture_issues,
    validate_error_coverage,
    validate_token_count,
)

# ── Test validate_token_count ──────────────────────────────────────────────────


class TestValidateTokenCount:
    """Test token count validation within ±5% tolerance."""

    def test_valid_tokens_within_tolerance(self):
        """Tokens within ±5% should pass."""
        # Phase R expects: input 1000 ±5% = 950-1050, output 2000 ±5% = 1900-2100
        is_valid, msg = validate_token_count("R", 980, 2020)
        assert is_valid is True
        assert "OK" in msg

    def test_input_tokens_below_range(self):
        """Input tokens below acceptable range should fail."""
        is_valid, msg = validate_token_count("R", 800, 2000)
        assert is_valid is False
        assert "Input tokens out of range" in msg

    def test_output_tokens_above_range(self):
        """Output tokens above acceptable range should fail."""
        is_valid, msg = validate_token_count("R", 1000, 2200)
        assert is_valid is False
        assert "Output tokens out of range" in msg

    def test_phase_m_tokens(self):
        """Test token validation for Phase M."""
        # Phase M expects: input 400 ±5%, output 200 ±5%
        is_valid, msg = validate_token_count("M", 400, 200)
        assert is_valid is True

    def test_phase_i_tokens(self):
        """Test token validation for Phase I (most demanding)."""
        # Phase I expects: input 2000 ±5% = 1900-2100, output 3000 ±5% = 2850-3150
        is_valid, msg = validate_token_count("I", 2050, 3100)
        assert is_valid is True

    def test_unknown_phase(self):
        """Unknown phase should fail gracefully."""
        is_valid, msg = validate_token_count("Z", 100, 100)
        assert is_valid is False
        assert "Unknown phase" in msg


# ── Test validate_error_coverage ───────────────────────────────────────────────


class TestValidateErrorCoverage:
    """Test error scenario coverage validation."""

    def test_all_required_errors_present(self):
        """All required error types present should pass."""
        errors = {"TimeoutError", "RateLimitError", "InvalidRequestError"}
        is_valid, msg = validate_error_coverage("R", errors)
        assert is_valid is True
        assert "OK" in msg

    def test_insufficient_errors(self):
        """Fewer than 2 error types should fail."""
        errors = {"TimeoutError"}
        is_valid, msg = validate_error_coverage("R", errors)
        assert is_valid is False
        assert "≥2 error types" in msg

    def test_missing_error_type(self):
        """Missing required error type should fail."""
        errors = {"TimeoutError", "RateLimitError"}
        is_valid, msg = validate_error_coverage("M", errors)
        assert is_valid is False
        assert "missing error types" in msg

    def test_extra_error_types_ok(self):
        """Having more than required error types is acceptable."""
        errors = {
            "TimeoutError",
            "RateLimitError",
            "InvalidRequestError",
            "ConnectionError",
        }
        is_valid, msg = validate_error_coverage("S", errors)
        assert is_valid is True


# ── Test flag_fixture_issues ───────────────────────────────────────────────────


class TestFlagFixtureIssues:
    """Test fixture gap detection."""

    def test_no_issues_complete_fixture(self):
        """Complete fixture with all phases and errors should have no issues."""
        # Phase-specific token counts
        phase_tokens = {
            "R": (1000, 2000),
            "T": (300, 600),
            "S": (750, 400),
            "M": (400, 200),
            "I": (2000, 3000),
            "V": (300, 300),
            "C": (150, 150),
        }

        mock_responses = {}
        for phase in REQUIRED_PHASES:
            input_tokens, output_tokens = phase_tokens[phase]
            mock_responses[phase] = [
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "InvalidRequestError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": None,  # Success case
                },
            ]

        issues = flag_fixture_issues(mock_responses)
        assert issues == []

    def test_missing_phase_detected(self):
        """Missing phase should be detected."""
        mock_responses = {"R": [], "T": []}  # Missing S, M, I, V, C

        issues = flag_fixture_issues(mock_responses)
        issue_types = {(i.phase_id, i.issue_type) for i in issues}

        # Should flag S, M, I, V, C as missing
        assert ("S", "missing_phase") in issue_types
        assert ("M", "missing_phase") in issue_types

    def test_insufficient_errors_detected(self):
        """Phase with only 1 error type should be flagged."""
        mock_responses = {
            "R": [
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "TimeoutError",
                },
            ]
        }
        # Add other phases to avoid "missing" issues
        for phase in ["T", "S", "M", "I", "V", "C"]:
            mock_responses[phase] = [
                {"tokens": {"input": 500, "output": 500}, "error_type": "TimeoutError"},
                {"tokens": {"input": 500, "output": 500}, "error_type": "RateLimitError"},
                {
                    "tokens": {"input": 500, "output": 500},
                    "error_type": "InvalidRequestError",
                },
            ]

        issues = flag_fixture_issues(mock_responses)
        r_issues = [i for i in issues if i.phase_id == "R"]
        assert len(r_issues) > 0
        assert any("insufficient_errors" in i.issue_type for i in r_issues)

    def test_unrealistic_token_counts_detected(self):
        """Token counts outside ±5% range should be flagged."""
        mock_responses = {
            "R": [
                {
                    "tokens": {"input": 500, "output": 2000},  # Input too low
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "InvalidRequestError",
                },
            ]
        }
        for phase in ["T", "S", "M", "I", "V", "C"]:
            mock_responses[phase] = [
                {"tokens": {"input": 300, "output": 600}, "error_type": "TimeoutError"},
                {"tokens": {"input": 300, "output": 600}, "error_type": "RateLimitError"},
                {
                    "tokens": {"input": 300, "output": 600},
                    "error_type": "InvalidRequestError",
                },
            ]

        issues = flag_fixture_issues(mock_responses)
        r_issues = [i for i in issues if i.phase_id == "R"]
        assert any("unrealistic_tokens" in i.issue_type for i in r_issues)

    def test_issue_dataclass_format(self):
        """Returned issues should be MockFixtureIssue instances."""
        mock_responses = {}  # Empty, will flag all phases as missing

        issues = flag_fixture_issues(mock_responses)
        assert len(issues) > 0
        assert all(isinstance(i, MockFixtureIssue) for i in issues)


# ── Test calculate_coverage_score ──────────────────────────────────────────────


class TestCalculateCoverageScore:
    """Test coverage score calculation."""

    def test_perfect_score(self):
        """Complete fixture should get high score."""
        # Phase-specific token counts
        phase_tokens = {
            "R": (1000, 2000),
            "T": (300, 600),
            "S": (750, 400),
            "M": (400, 200),
            "I": (2000, 3000),
            "V": (300, 300),
            "C": (150, 150),
        }

        mock_responses = {}
        for phase in REQUIRED_PHASES:
            input_tokens, output_tokens = phase_tokens[phase]
            mock_responses[phase] = [
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "InvalidRequestError",
                },
            ]

        score = calculate_coverage_score(mock_responses)
        assert score >= 90.0  # Should meet >90% requirement

    def test_empty_fixture_score(self):
        """Empty fixture should get low score."""
        mock_responses = {}
        score = calculate_coverage_score(mock_responses)
        assert score == 0.0

    def test_partial_fixture_score(self):
        """Partial fixture should get proportional score."""
        # Only Phase R with good coverage (R expects: 1000 input, 2000 output)
        mock_responses = {
            "R": [
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "InvalidRequestError",
                },
            ]
        }

        score = calculate_coverage_score(mock_responses)
        # Should be roughly 1/7 of max score = ~14%
        assert 10.0 < score < 20.0

    def test_score_penalty_for_errors(self):
        """Missing error types should reduce score."""
        # All phases present but each missing one error type
        phase_tokens = {
            "R": (1000, 2000),
            "T": (300, 600),
            "S": (750, 400),
            "M": (400, 200),
            "I": (2000, 3000),
            "V": (300, 300),
            "C": (150, 150),
        }

        mock_responses = {}
        for phase in REQUIRED_PHASES:
            input_tokens, output_tokens = phase_tokens[phase]
            mock_responses[phase] = [
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": input_tokens, "output": output_tokens},
                    "error_type": "RateLimitError",
                },
                # Missing InvalidRequestError
            ]

        score = calculate_coverage_score(mock_responses)
        # Each missing error: -5, so 7 phases * -5 = -35 from max
        assert score < 70.0  # Should be penalized

    def test_score_penalty_for_token_issues(self):
        """Unrealistic tokens should reduce score."""
        mock_responses = {}
        for phase in REQUIRED_PHASES:
            mock_responses[phase] = [
                {
                    "tokens": {"input": 50, "output": 50},  # Way too low for any phase
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 50, "output": 50},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 50, "output": 50},
                    "error_type": "InvalidRequestError",
                },
            ]

        score = calculate_coverage_score(mock_responses)
        # Each bad token: -10, so 7 phases * 3 responses * -10 = -210
        # But score is clamped to [0, 100]
        assert score == 0.0  # Should be heavily penalized


# ── Integration: Fixture quality assertions ────────────────────────────────────


class TestFixtureQualityIntegration:
    """Integration tests for complete fixture quality validation."""

    def test_phase_token_expectations_defined(self):
        """All required phases should have token expectations."""
        for phase in REQUIRED_PHASES:
            assert phase in PHASE_TOKEN_EXPECTATIONS, f"Missing expectations for {phase}"

    def test_error_types_requirements(self):
        """Required error types should be well-defined."""
        assert len(REQUIRED_ERROR_TYPES) >= 3
        assert "TimeoutError" in REQUIRED_ERROR_TYPES
        assert "RateLimitError" in REQUIRED_ERROR_TYPES
        assert "InvalidRequestError" in REQUIRED_ERROR_TYPES

    def test_realistic_production_fixture(self):
        """Test a realistic production-like fixture."""
        # All values within ±5% of expected
        mock_responses = {
            "R": [
                {
                    "tokens": {"input": 1050, "output": 2050},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 1000, "output": 2000},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 950, "output": 1950},
                    "error_type": "InvalidRequestError",
                },
                {"tokens": {"input": 1000, "output": 2000}, "error_type": None},
            ],
            "T": [
                {
                    "tokens": {"input": 310, "output": 620},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 300, "output": 600},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 290, "output": 580},
                    "error_type": "InvalidRequestError",
                },
            ],
            "S": [
                {
                    "tokens": {"input": 780, "output": 420},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 750, "output": 400},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 720, "output": 380},
                    "error_type": "InvalidRequestError",
                },
            ],
            "M": [
                {
                    "tokens": {"input": 420, "output": 210},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 400, "output": 200},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 380, "output": 190},
                    "error_type": "InvalidRequestError",
                },
            ],
            "I": [
                {
                    "tokens": {"input": 2100, "output": 3100},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 2000, "output": 3000},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 1900, "output": 2900},
                    "error_type": "InvalidRequestError",
                },
            ],
            "V": [
                {
                    "tokens": {"input": 310, "output": 310},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 300, "output": 300},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 290, "output": 290},
                    "error_type": "InvalidRequestError",
                },
            ],
            "C": [
                {
                    "tokens": {"input": 155, "output": 155},
                    "error_type": "TimeoutError",
                },
                {
                    "tokens": {"input": 150, "output": 150},
                    "error_type": "RateLimitError",
                },
                {
                    "tokens": {"input": 145, "output": 145},
                    "error_type": "InvalidRequestError",
                },
            ],
        }

        # Check for issues
        issues = flag_fixture_issues(mock_responses)
        assert len(issues) == 0, f"Should have no issues, got: {issues}"

        # Check coverage score
        score = calculate_coverage_score(mock_responses)
        assert score > 90.0, f"Coverage score should be >90, got {score}"
