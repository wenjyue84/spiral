#!/usr/bin/env python3
"""
tests/test_failure_categorizer.py — Unit tests for lib/failure_categorizer.py

Tests verify:
- categorize_failure() classifies 7+ error types correctly
- Failure message extraction works
- Edge cases: empty input, unknown errors, multiple errors
"""

from __future__ import annotations

import pytest

from lib.failure_categorizer import categorize_failure, categorize_message


@pytest.mark.us_1090
class TestCategorizeFailure:
    """Test categorize_failure() function."""

    def test_importerror_classification(self) -> None:
        """ImportError should be classified as missing_dependency."""
        stderr = "ModuleNotFoundError: No module named 'nonexistent_lib'"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "missing_dependency"
        assert "module" in failure_message.lower()
        assert len(failure_message) <= 200

    def test_syntaxerror_classification(self) -> None:
        """SyntaxError should be classified as syntax_error."""
        stderr = "SyntaxError: invalid syntax\n  File 'test.py', line 10\n    x = ["
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "syntax_error"
        assert "syntax" in failure_message.lower() or "file" in failure_message.lower()

    def test_pytest_assertion_classification(self) -> None:
        """Pytest assertion failures should be classified as test_assertion."""
        stderr = ""
        stdout = "FAILED tests/test_example.py::test_foo - AssertionError: expected 5, got 3"
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "test_assertion"
        assert "expected" in failure_message.lower() or "failed" in failure_message.lower()

    def test_timeout_classification(self) -> None:
        """Timeout errors should be classified as timeout."""
        stderr = "ERROR: Execution timeout after 300 seconds\nExecution timed out"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "timeout"
        assert "timeout" in failure_message.lower() or "time" in failure_message.lower()

    def test_oom_classification(self) -> None:
        """Out of memory errors should be classified as oom."""
        stderr = "MemoryError: Out of memory when allocating 4GB\n"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "oom"
        assert "memory" in failure_message.lower()

    def test_typeerror_classification(self) -> None:
        """TypeError should be classified as type_error."""
        stderr = "TypeError: expected str, got int"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "type_error"
        assert "type" in failure_message.lower() or "int" in failure_message.lower()

    def test_context_overflow_classification(self) -> None:
        """Context window overflow should be classified as context_overflow."""
        stderr = "Error: Context window exceeded - prompt too long (200k > 180k tokens)"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "context_overflow"
        assert "context" in failure_message.lower() or "token" in failure_message.lower()

    def test_unknown_error_classification(self) -> None:
        """Unknown errors should be classified as other."""
        stderr = "Something went wrong with the flux capacitor"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "other"
        assert len(failure_message) > 0

    def test_empty_input(self) -> None:
        """Empty input should default to other with placeholder message."""
        stderr = ""
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "other"
        assert failure_message == "unknown error"

    def test_failure_message_truncation(self) -> None:
        """Failure message should be truncated to 200 characters."""
        long_error = "A" * 300
        stderr = long_error
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert len(failure_message) <= 200

    def test_multiple_errors_first_wins(self) -> None:
        """When multiple error types present, highest priority (earlier in check) wins."""
        stderr = "ImportError: Cannot import module\nAnd then there was a timeout after 5 minutes"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        # missing_dependency is checked before timeout, so it should win
        assert failure_type == "missing_dependency"

    def test_case_insensitive_matching(self) -> None:
        """Error classification should be case-insensitive."""
        stderr = "IMPORTERROR: NO MODULE NAMED 'xyz'"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "missing_dependency"

    def test_failure_message_from_stdout(self) -> None:
        """Failure message should be extracted from stdout if stderr is empty."""
        stderr = ""
        stdout = "Test run failed with: AssertionError: Expected 10 but got 5"
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "test_assertion"
        assert "assertion" in failure_message.lower() or "expected" in failure_message.lower()

    def test_real_world_pytest_failure(self) -> None:
        """Real-world pytest failure output."""
        stderr = ""
        stdout = """
=== FAILURES ===
test_example.py::test_calculation FAILED

def test_calculation():
    result = add(2, 2)
>   assert result == 5
E   AssertionError: assert 4 == 5

test_example.py:10: AssertionError
"""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "test_assertion"
        assert "assertion" in failure_message.lower() or "failed" in failure_message.lower()

    def test_real_world_import_error(self) -> None:
        """Real-world ImportError output."""
        stderr = """
Traceback (most recent call last):
  File "main.py", line 5, in <module>
    from nonexistent_module import SomeClass
ModuleNotFoundError: No module named 'nonexistent_module'
"""
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "missing_dependency"
        assert "module" in failure_message.lower()


@pytest.mark.us_1090
class TestCategorizeMessage:
    """Test categorize_message() single-message classification wrapper."""

    def test_categorize_single_import_error(self) -> None:
        """categorize_message should classify single error message."""
        message = "ModuleNotFoundError: No module named 'xyz'"
        failure_type = categorize_message(message)

        assert failure_type == "missing_dependency"

    def test_categorize_single_syntax_error(self) -> None:
        """categorize_message should handle SyntaxError."""
        message = "SyntaxError: invalid syntax"
        failure_type = categorize_message(message)

        assert failure_type == "syntax_error"

    def test_categorize_single_type_error(self) -> None:
        """categorize_message should handle TypeError."""
        message = "TypeError: expected str, got int"
        failure_type = categorize_message(message)

        assert failure_type == "type_error"

    def test_categorize_single_context_overflow(self) -> None:
        """categorize_message should handle context overflow."""
        message = "Error: Context window exceeded (200k tokens)"
        failure_type = categorize_message(message)

        assert failure_type == "context_overflow"


@pytest.mark.us_1090
class TestFailureCategorizerIntegration:
    """Integration tests for failure categorizer as used by Phase I."""

    def test_phase_i_use_case_import_failure(self) -> None:
        """Phase I captures ralph stderr/stdout with import failure."""
        # Simulate ralph's actual output format
        stderr = (
            "Traceback (most recent call last):\n"
            "  File '/spiral/ralph.sh', line 1000, in <module>\n"
            "    from missing_lib import something\n"
            "ImportError: cannot import name 'something'\n"
        )
        stdout = "Story US-123 started"
        failure_type, failure_message = categorize_failure(stderr, stdout)

        # Phase I should detect this as missing_dependency
        assert failure_type == "missing_dependency"
        assert "import" in failure_message.lower() or "missing" in failure_message.lower()
        assert len(failure_message) <= 200

    def test_phase_i_use_case_test_failure(self) -> None:
        """Phase I captures test assertion failure during verification."""
        stderr = ""
        stdout = (
            "Running test suite...\n"
            "FAILED tests/test_new_feature.py::test_basic - "
            "AssertionError: expected 42 but got 41\n"
            "=== 1 failed in 0.23s ===\n"
        )
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "test_assertion"
        assert "assertion" in failure_message.lower() or "expected" in failure_message.lower()

    def test_phase_i_use_case_timeout(self) -> None:
        """Phase I captures timeout during implementation."""
        stderr = "Execution timed out after 600 seconds (10 minutes)\nStory did not complete within the time limit\n"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "timeout"
        assert "timed" in failure_message.lower() or "timeout" in failure_message.lower()

    def test_stderr_takes_precedence_over_stdout(self) -> None:
        """When both stderr and stdout have errors, earlier pattern wins."""
        # missing_dependency is checked before test_assertion
        stderr = "ImportError: missing package 'xyz'"
        stdout = "AssertionError in test_foo"
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "missing_dependency"
        assert "import" in failure_message.lower()

    def test_indentation_error_classification(self) -> None:
        """IndentationError (subtype of SyntaxError) should classify correctly."""
        stderr = "IndentationError: expected an indented block\n  File 'test.py', line 5\n"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "syntax_error"

    def test_mypy_type_error_classification(self) -> None:
        """MyPy type checking errors should be classified as type_error."""
        stderr = "test.py:10: error: Argument 1 to 'func' has incompatible type 'str'; expected 'int'  [arg-type]\n"
        stdout = ""
        failure_type, failure_message = categorize_failure(stderr, stdout)

        assert failure_type == "type_error"
