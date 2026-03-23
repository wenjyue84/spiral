"""tests/test_phase_t_error_categorization.py — Integration tests for Phase T error categorization (US-1042).

Tests categorize_test_failure() against all 4 categories using
realistic mock pytest output strings.
"""

from lib.spiral.phase_t import categorize_test_failure


def test_syntax_error() -> None:
    output = "SyntaxError: invalid syntax"
    assert categorize_test_failure(output) == "syntax_error"


def test_assertion_failure() -> None:
    output = "AssertionError: assert 1 == 2"
    assert categorize_test_failure(output) == "assertion_failure"


def test_timeout() -> None:
    output = "TimeoutExpired: Command timed out after 30 seconds"
    assert categorize_test_failure(output) == "timeout"


def test_integration_failure() -> None:
    output = "ConnectionRefusedError: [Errno 111] Connection refused"
    assert categorize_test_failure(output) == "integration_failure"
