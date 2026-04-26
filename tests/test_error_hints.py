"""
test_error_hints.py — Validate failure type → hint mapping and pattern matching.

Tests that:
  1. All 8 failure types generate hints with suggestion + action
  2. Hints are TSV-safe (no tabs, newlines, unescaped quotes)
  3. Pattern matching correctly identifies failure types from error output
  4. 8+ regex patterns are tested end-to-end
"""

from __future__ import annotations

import pytest

from lib.error_hints import FailureHintMapper, RecoveryHint, hint_text


class TestFailureHintRegistry:
    """Test the hint registry covers all 8 failure types."""

    def test_registry_has_all_8_types(self) -> None:
        """Verify all 8 failure types are registered."""
        expected_types = {
            "missing_dependency",
            "syntax_error",
            "type_error",
            "test_assertion",
            "timeout",
            "oom",
            "context_overflow",
            "other",
        }
        actual_types = set(FailureHintMapper.HINT_REGISTRY.keys())
        assert actual_types == expected_types

    def test_each_type_has_suggestion_and_action(self) -> None:
        """Verify each registered type has non-empty suggestion and action."""
        for failure_type, (suggestion, action) in FailureHintMapper.HINT_REGISTRY.items():
            assert suggestion, f"{failure_type} missing suggestion"
            assert action, f"{failure_type} missing action"
            assert len(suggestion) > 10, f"{failure_type} suggestion too short"
            assert len(action) > 2, f"{failure_type} action too short"

    def test_hint_coverage(self) -> None:
        """Test that hints are generated for all 8+ failure patterns."""
        failure_patterns = {
            "missing_dependency": [
                "ImportError: cannot import name 'xyz'",
                "ModuleNotFoundError: No module named 'missing_lib'",
            ],
            "syntax_error": [
                "SyntaxError: unexpected token at line 42",
                "IndentationError: invalid indentation",
            ],
            "type_error": [
                "TypeError: argument must be int, not str",
                "mypy error: incompatible type",
            ],
            "test_assertion": [
                "AssertionError: assert False",
                "FAILED tests/test_x.py::test_foo",
            ],
            "timeout": [
                "TimeoutError: execution timeout after 30s",
                "Deadline exceeded",
            ],
            "oom": [
                "MemoryError: out of memory",
                "OutOfMemoryError: heap overflow",
            ],
            "context_overflow": [
                "Error: context window exceeded",
                "Token limit exceeded: 128000 > 128000",
            ],
        }

        for failure_type, error_messages in failure_patterns.items():
            for error_msg in error_messages:
                hint = FailureHintMapper.generate_hint(failure_type)
                assert hint.failure_type == failure_type
                assert hint.suggestion
                assert hint.action
                assert hint.recovery_hint


class TestRecoveryHintStructure:
    """Test RecoveryHint dataclass and TSV formatting."""

    def test_recovery_hint_has_required_fields(self) -> None:
        """Verify RecoveryHint has all required fields."""
        hint = FailureHintMapper.generate_hint("syntax_error")
        assert isinstance(hint, RecoveryHint)
        assert hint.failure_type == "syntax_error"
        assert hint.suggestion
        assert hint.action
        assert hint.recovery_hint

    def test_to_tsv_removes_tabs(self) -> None:
        """Verify to_tsv() replaces tabs with spaces."""
        hint = RecoveryHint(
            failure_type="test",
            suggestion="test\tseparated",
            action="action",
            recovery_hint="line1\tline2",
        )
        tsv_safe = hint.to_tsv()
        assert "\t" not in tsv_safe

    def test_to_tsv_removes_newlines(self) -> None:
        """Verify to_tsv() replaces newlines with spaces."""
        hint = RecoveryHint(
            failure_type="test",
            suggestion="line1\nline2",
            action="action",
            recovery_hint="line1\nline2",
        )
        tsv_safe = hint.to_tsv()
        assert "\n" not in tsv_safe
        assert "line1" in tsv_safe and "line2" in tsv_safe

    def test_to_tsv_escapes_quotes(self) -> None:
        """Verify to_tsv() escapes double quotes."""
        hint = RecoveryHint(
            failure_type="test",
            suggestion='use "quotes"',
            action="action",
            recovery_hint='fix "error"',
        )
        tsv_safe = hint.to_tsv()
        assert '"' not in tsv_safe
        assert "'" in tsv_safe

    def test_to_tsv_truncates_at_200_chars(self) -> None:
        """Verify to_tsv() truncates to 200 characters."""
        long_hint = "x" * 300
        hint = RecoveryHint(
            failure_type="test",
            suggestion="x",
            action="x",
            recovery_hint=long_hint,
        )
        tsv_safe = hint.to_tsv()
        assert len(tsv_safe) <= 200


class TestPatternMatching:
    """Test regex pattern matching for error categorization."""

    @pytest.mark.parametrize(
        "failure_type,error_outputs",
        [
            (
                "missing_dependency",
                [
                    "ImportError: cannot import name 'xyz' from 'lib'",
                    "ModuleNotFoundError: No module named 'missing_lib'",
                    "ERROR: cannot import missing_dependency",
                ],
            ),
            (
                "syntax_error",
                [
                    "SyntaxError: unexpected token '<' at line 42",
                    "IndentationError: invalid indentation on line 10",
                    "ERROR: unexpected token in file.py",
                ],
            ),
            (
                "type_error",
                [
                    "TypeError: argument must be int, not str",
                    "mypy error: Incompatible type assignment",
                    "Type checking failed: expected str got int",
                ],
            ),
            (
                "test_assertion",
                [
                    "AssertionError: assert False",
                    "FAILED tests/test_x.py::test_foo - AssertionError",
                    "pytest: assertion failed, expected True but got False",
                ],
            ),
            (
                "timeout",
                [
                    "TimeoutError: execution timeout after 30 seconds",
                    "Error: timed out waiting for response",
                    "Deadline exceeded: request took too long",
                ],
            ),
            (
                "oom",
                [
                    "MemoryError: out of memory",
                    "OutOfMemoryError: heap overflow detected",
                    "Error: cannot allocate memory for array",
                ],
            ),
            (
                "context_overflow",
                [
                    "Error: context window exceeded",
                    "Context overflow: prompt too long for model",
                    "Token limit exceeded: 150000 > 128000",
                ],
            ),
        ],
        ids=[
            "missing_dependency",
            "syntax_error",
            "type_error",
            "test_assertion",
            "timeout",
            "oom",
            "context_overflow",
        ],
    )
    def test_generate_hint_by_pattern(self, failure_type: str, error_outputs: list[str]) -> None:
        """Test pattern matching for each failure type (8 patterns)."""
        for error_output in error_outputs:
            hint = FailureHintMapper.get_hint_by_pattern(error_output)
            assert hint.failure_type == failure_type, (
                f"Expected {failure_type}, got {hint.failure_type} for: {error_output}"
            )
            assert hint.suggestion
            assert hint.action

    def test_unknown_error_defaults_to_other(self) -> None:
        """Test that unrecognized errors default to 'other' type."""
        unknown_output = "Some random error message that doesn't match any pattern"
        hint = FailureHintMapper.get_hint_by_pattern(unknown_output)
        assert hint.failure_type == "other"
        assert hint.suggestion
        assert hint.action

    def test_explicit_failure_type_overrides_pattern(self) -> None:
        """Test that explicit failure_type parameter overrides pattern matching."""
        # Error output matches "timeout" but we explicitly say it's "syntax_error"
        error_output = "TimeoutError: execution timed out"
        hint = FailureHintMapper.get_hint_by_pattern(error_output, failure_type="syntax_error")
        assert hint.failure_type == "syntax_error"


class TestConvenienceFunctions:
    """Test helper functions like hint_text()."""

    def test_hint_text_returns_tsv_safe_string(self) -> None:
        """Verify hint_text() returns a TSV-safe string."""
        result = hint_text("syntax_error")
        assert isinstance(result, str)
        assert "\t" not in result
        assert "\n" not in result
        assert len(result) <= 200

    def test_hint_text_for_all_types(self) -> None:
        """Test hint_text() for all 8 failure types."""
        for failure_type in [
            "missing_dependency",
            "syntax_error",
            "type_error",
            "test_assertion",
            "timeout",
            "oom",
            "context_overflow",
            "other",
        ]:
            result = hint_text(failure_type)
            assert result
            assert isinstance(result, str)
            assert len(result) <= 200

    def test_hint_text_case_insensitive(self) -> None:
        """Test that hint_text() handles mixed case failure types."""
        result1 = hint_text("syntax_error")
        result2 = hint_text("SYNTAX_ERROR")
        result3 = hint_text("Syntax_Error")
        assert result1 == result2 == result3


class TestHintCompleteness:
    """Integration tests for hint content completeness."""

    def test_all_hints_have_actionable_content(self) -> None:
        """Verify all hints contain actionable guidance."""
        action_keywords = {
            "missing_dependency": ["import"],
            "syntax_error": ["fix", "syntax", "check"],
            "type_error": ["type", "verify", "signature"],
            "test_assertion": ["read", "review", "test"],
            "timeout": ["optimize", "increase", "timeout"],
            "oom": ["optimize", "memory"],
            "context_overflow": ["reduce", "scope", "decomposition"],
            "other": ["review", "different", "approach"],
        }

        for failure_type, keywords in action_keywords.items():
            hint = FailureHintMapper.generate_hint(failure_type)
            full_text = (hint.suggestion + " " + hint.action).lower()
            assert any(kw in full_text for kw in keywords), (
                f"{failure_type} hint missing actionable keywords: {keywords}"
            )
