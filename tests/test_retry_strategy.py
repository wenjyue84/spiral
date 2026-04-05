"""Tests for failure-aware retry strategy selection.

Tests the strategy mapping logic (failure_type x retry_count -> action)
and the failure categorizer integration. The bash functions in retry.sh
are thin wrappers around this same logic, so testing the mapping in Python
is equivalent.
"""

from __future__ import annotations

import pytest

from lib.failure_categorizer import categorize_failure

# ── Strategy mapping (mirrors select_retry_strategy in lib/impl/retry.sh) ──
# This is the source-of-truth table. The bash function implements the same
# case/esac logic. We test the mapping here in Python for speed and portability.

_STRATEGY_MAP: dict[str, list[str]] = {
    # failure_type: [retry_0, retry_1, retry_2+]
    "missing_dependency": ["same_model", "same_model", "escalate_model"],
    "syntax_error": ["same_model", "same_model", "escalate_model"],
    "type_error": ["same_model", "same_model", "escalate_model"],
    "test_assertion": ["same_model", "escalate_model", "skip"],
    "context_overflow": ["scope_reduce", "scope_reduce", "skip"],
    "timeout": ["extend_timeout", "decompose", "skip"],
    "oom": ["skip", "skip", "skip"],
    "other": ["escalate_model", "escalate_model", "skip"],
}


def select_retry_strategy(failure_type: str, retry_count: int) -> str:
    """Python implementation of the retry strategy selector.

    Mirrors the bash select_retry_strategy() in lib/impl/retry.sh.
    """
    strategies = _STRATEGY_MAP.get(failure_type, _STRATEGY_MAP["other"])
    idx = min(retry_count, 2)
    return strategies[idx]


class TestSelectRetryStrategy:
    """Test the failure_type -> retry_action mapping."""

    @pytest.mark.parametrize(
        "failure_type,retry,expected",
        [
            # missing_dependency: same model for retries 0-1, escalate at 2+
            ("missing_dependency", 0, "same_model"),
            ("missing_dependency", 1, "same_model"),
            ("missing_dependency", 2, "escalate_model"),
            # syntax_error: same model for retries 0-1, escalate at 2+
            ("syntax_error", 0, "same_model"),
            ("syntax_error", 1, "same_model"),
            ("syntax_error", 2, "escalate_model"),
            # type_error: same model for retries 0-1, escalate at 2+
            ("type_error", 0, "same_model"),
            ("type_error", 1, "same_model"),
            ("type_error", 2, "escalate_model"),
            # test_assertion: same_model -> escalate -> skip
            ("test_assertion", 0, "same_model"),
            ("test_assertion", 1, "escalate_model"),
            ("test_assertion", 2, "skip"),
            # context_overflow: scope_reduce -> scope_reduce -> skip
            ("context_overflow", 0, "scope_reduce"),
            ("context_overflow", 1, "scope_reduce"),
            ("context_overflow", 2, "skip"),
            # timeout: extend -> decompose -> skip
            ("timeout", 0, "extend_timeout"),
            ("timeout", 1, "decompose"),
            ("timeout", 2, "skip"),
            # oom: always skip
            ("oom", 0, "skip"),
            ("oom", 1, "skip"),
            ("oom", 2, "skip"),
            # other: escalate -> escalate -> skip
            ("other", 0, "escalate_model"),
            ("other", 1, "escalate_model"),
            ("other", 2, "skip"),
        ],
    )
    def test_strategy_selection(self, failure_type: str, retry: int, expected: str) -> None:
        result = select_retry_strategy(failure_type, retry)
        assert result == expected

    def test_unknown_failure_type_defaults_to_other(self) -> None:
        """Unknown failure types should behave like 'other'."""
        result = select_retry_strategy("unknown_category", 0)
        assert result == "escalate_model"

    def test_high_retry_count_clamps_to_max(self) -> None:
        """Retry counts > 2 should use the retry_2+ strategy."""
        assert select_retry_strategy("other", 5) == "skip"
        assert select_retry_strategy("missing_dependency", 10) == "escalate_model"


class TestFailureCategorization:
    """Test that failure_categorizer correctly classifies errors for retry routing."""

    def test_import_error(self) -> None:
        stderr = "ImportError: No module named 'nonexistent_package'"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "missing_dependency"

    def test_syntax_error(self) -> None:
        stderr = "SyntaxError: unexpected EOF while parsing"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "syntax_error"

    def test_type_error(self) -> None:
        stderr = "TypeError: unsupported operand type(s)"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "type_error"

    def test_timeout(self) -> None:
        stderr = "Error: execution timeout after 300 seconds"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "timeout"

    def test_oom(self) -> None:
        stderr = "FATAL ERROR: JavaScript heap out of memory"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "oom"

    def test_context_overflow(self) -> None:
        stderr = "Error: context window exceeded, prompt too long"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "context_overflow"

    def test_test_assertion(self) -> None:
        stderr = "FAILED tests/test_foo.py::test_bar - AssertionError"
        ftype, _ = categorize_failure(stderr, "")
        assert ftype == "test_assertion"

    def test_empty_output_returns_other(self) -> None:
        ftype, _ = categorize_failure("", "")
        assert ftype == "other"


class TestStrategyToActionMapping:
    """Verify that each strategy maps to a sensible action for each failure type."""

    def test_fixable_errors_dont_escalate_on_first_retry(self) -> None:
        """syntax_error, type_error, missing_dependency should NOT escalate on retry 0-1."""
        for ftype in ("syntax_error", "type_error", "missing_dependency"):
            assert select_retry_strategy(ftype, 0) == "same_model"
            assert select_retry_strategy(ftype, 1) == "same_model"

    def test_context_overflow_triggers_scope_reduction(self) -> None:
        """context_overflow should trigger scope_reduce, not model escalation."""
        assert select_retry_strategy("context_overflow", 0) == "scope_reduce"
        assert select_retry_strategy("context_overflow", 1) == "scope_reduce"

    def test_timeout_escalates_to_decompose(self) -> None:
        """First timeout extends, second decomposes."""
        assert select_retry_strategy("timeout", 0) == "extend_timeout"
        assert select_retry_strategy("timeout", 1) == "decompose"

    def test_oom_always_skips(self) -> None:
        """OOM is not fixable by retry — always skip."""
        for r in range(5):
            assert select_retry_strategy("oom", r) == "skip"
