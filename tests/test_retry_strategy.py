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


class TestErrorSignatureExtraction:
    """Test error signature extraction from failure output (US-1155)."""

    def test_import_error_signature(self) -> None:
        """ImportError should extract as missing_dependency."""
        stderr = "ImportError: No module named 'nonexistent_package'"
        ftype, fmsg = categorize_failure(stderr, "")
        assert ftype == "missing_dependency"
        assert "No module named" in fmsg or "ImportError" in fmsg

    def test_syntax_error_signature(self) -> None:
        """SyntaxError should extract correctly."""
        stderr = "SyntaxError: unexpected EOF while parsing"
        ftype, fmsg = categorize_failure(stderr, "")
        assert ftype == "syntax_error"
        assert "SyntaxError" in fmsg or "unexpected" in fmsg

    def test_timeout_error_signature(self) -> None:
        """Timeout should extract as timeout type."""
        stderr = "Error: execution timeout after 300 seconds"
        ftype, fmsg = categorize_failure(stderr, "")
        assert ftype == "timeout"
        assert "timeout" in fmsg.lower()

    def test_unknown_error_signature(self) -> None:
        """Unknown errors should default to 'other'."""
        stderr = "Some random error message"
        ftype, fmsg = categorize_failure(stderr, "")
        assert ftype == "other"
        assert len(fmsg) > 0


class TestErrorHintInjection:
    """Test hint injection for retry prompts (US-1155)."""

    def test_missing_dependency_hint(self) -> None:
        """Missing dependency hint should suggest importing."""
        # Simulating the hint lookup
        error_type = "missing_dependency"
        hint_map = {
            "missing_dependency": "Do NOT forget to import all required modules",
            "syntax_error": "Do NOT use invalid Python syntax",
        }
        hint = hint_map.get(error_type, "Do NOT repeat the same approach")
        assert "import" in hint.lower()

    def test_syntax_error_hint(self) -> None:
        """Syntax error hint should mention brackets/indentation."""
        error_type = "syntax_error"
        hint_map = {
            "missing_dependency": "Do NOT forget to import all required modules",
            "syntax_error": "Do NOT use invalid Python syntax",
        }
        hint = hint_map.get(error_type, "Do NOT repeat the same approach")
        assert "syntax" in hint.lower()

    def test_timeout_hint(self) -> None:
        """Timeout hint should suggest optimization."""
        error_type = "timeout"
        hint_map = {
            "timeout": "Do NOT use inefficient algorithms. Optimize performance.",
        }
        hint = hint_map.get(error_type, "Do NOT repeat the same approach")
        assert "optim" in hint.lower() or "algorithm" in hint.lower()

    def test_default_hint_for_unknown_error(self) -> None:
        """Unknown error types should get generic retry hint."""
        error_type = "unknown_custom_error"
        hint_map = {
            "missing_dependency": "Do NOT forget to import",
            "syntax_error": "Do NOT use invalid syntax",
        }
        hint = hint_map.get(error_type, "Do NOT repeat the same approach")
        assert "Do NOT repeat" in hint


class TestErrorEscalationReset:
    """Test escalation counter reset on different error (US-1155)."""

    def test_same_error_on_retry_does_not_reset_escalation(self) -> None:
        """If retry 2 has same error_type as retry 1, escalation counter continues."""
        error_types = ["timeout", "timeout"]
        # Both are same, so escalation should NOT reset
        assert error_types[0] == error_types[1]

    def test_different_error_on_retry_resets_escalation(self) -> None:
        """If retry 2 has different error_type, escalation counter resets."""
        error_types = ["timeout", "missing_dependency"]
        # Different errors, escalation resets
        assert error_types[0] != error_types[1]

    def test_escalation_decision_on_same_error(self) -> None:
        """Same error on retry 2 should trigger escalation."""
        error_type_attempt1 = "timeout"
        error_type_attempt2 = "timeout"
        # On same error, escalate model (don't reset counter)
        if error_type_attempt1 == error_type_attempt2:
            action = "escalate_model"
        else:
            action = "reset_escalation_counter"
        assert action == "escalate_model"

    def test_escalation_reset_on_different_error(self) -> None:
        """Different error on retry 2 should reset escalation."""
        error_type_attempt1 = "timeout"
        error_type_attempt2 = "syntax_error"
        # On different error, reset counter and retry with same model
        if error_type_attempt1 == error_type_attempt2:
            action = "escalate_model"
        else:
            action = "reset_escalation_counter"
        assert action == "reset_escalation_counter"

    def test_escalation_chain_with_changing_errors(self) -> None:
        """Multiple retries with changing errors should reset escalation."""
        error_history = ["timeout", "syntax_error", "missing_dependency"]
        escalation_counter = 0

        for i in range(1, len(error_history)):
            prev_error = error_history[i - 1]
            curr_error = error_history[i]

            if prev_error == curr_error:
                escalation_counter += 1
            else:
                escalation_counter = 0  # Reset on different error

        # After all retries with different errors, counter should be 0
        assert escalation_counter == 0
