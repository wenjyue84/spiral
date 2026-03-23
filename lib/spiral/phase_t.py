"""lib/spiral/phase_t.py — Phase T: Test failure categorization utilities.

Provides categorize_test_failure() for classifying pytest output lines into one
of four failure categories used by Phase T story generation.
"""

import re


def categorize_test_failure(output: str) -> str:
    """Categorize a pytest failure output line into one of four categories.

    Args:
        output: A string containing pytest failure output (one or more lines).

    Returns:
        'syntax_error'        — SyntaxError or IndentationError in output
        'assertion_failure'   — AssertionError in output
        'timeout'             — TimeoutExpired or Timeout in output
        'integration_failure' — all other cases
    """
    if re.search(r"SyntaxError|IndentationError", output):
        return "syntax_error"
    if re.search(r"AssertionError", output):
        return "assertion_failure"
    if re.search(r"TimeoutExpired|Timeout", output):
        return "timeout"
    return "integration_failure"
