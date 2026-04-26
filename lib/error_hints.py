#!/usr/bin/env python3
"""
error_hints.py — Maps failure types to actionable recovery hints.

Enriches Phase I implementation failures with recovery suggestions indexed by
failure type. Each hint includes:
  - failure_type: one of 8 categories
  - suggestion: actionable recovery text (e.g., "Reduce scope to atomic steps")
  - action: clickable action for spiral-ui (e.g., "View decomposition")
  - recovery_hint: formatted string for results.tsv
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecoveryHint:
    """Structured recovery hint with suggestion and action."""

    failure_type: str
    suggestion: str
    action: str
    recovery_hint: str

    def to_tsv(self) -> str:
        """Format hint as TSV-safe string (no newlines, tabs, quotes)."""
        safe = self.recovery_hint.replace("\t", " ").replace("\n", " ").replace('"', "'")
        return safe[:200]  # Truncate to 200 chars for TSV


class FailureHintMapper:
    """Maps failure types to recovery hints with actions."""

    # Registry of failure type → (suggestion, action)
    HINT_REGISTRY: dict[str, tuple[str, str]] = {
        "missing_dependency": (
            "Ensure all required modules are imported at the top of the file. Check "
            "that each imported name is used in the implementation.",
            "Check imports",
        ),
        "syntax_error": (
            "Fix Python syntax: check for unmatched brackets, quotes, indentation, "
            "and line continuations. Validate the code with Python parser.",
            "Validate syntax",
        ),
        "type_error": (
            "Verify function signatures and argument types. Use type hints throughout "
            "and ensure compatibility. Check mypy --strict output for details.",
            "Review types",
        ),
        "test_assertion": (
            "Re-read test code and acceptance criteria carefully. Ensure the "
            "implementation matches expected behavior and all assertions pass.",
            "Review tests",
        ),
        "timeout": (
            "Optimize performance: avoid inefficient algorithms, infinite loops, and "
            "expensive operations. Consider increasing SPIRAL_TIMEOUT if limits are too tight.",
            "Increase timeout",
        ),
        "oom": (
            "Optimize memory usage: avoid creating large objects in memory, avoid loading "
            "entire datasets at once, and use streaming/chunking where possible.",
            "Check memory",
        ),
        "context_overflow": (
            "Reduce scope to atomic, focused changes. Break story into smaller parts, "
            "defer non-critical files (tests, docs), and keep implementation concise.",
            "View decomposition",
        ),
        "other": (
            "Try a fundamentally different implementation strategy. Review the error "
            "message for clues about the root cause and adjust approach accordingly.",
            "Review error log",
        ),
    }

    @staticmethod
    def generate_hint(failure_type: str, error_message: str = "") -> RecoveryHint:
        """
        Generate a recovery hint for a failure type.

        Args:
            failure_type: one of 8 failure categories from failure_categorizer
            error_message: extracted error message (optional, for context)

        Returns:
            RecoveryHint with suggestion, action, and formatted hint
        """
        failure_type = failure_type.lower().strip()
        if failure_type not in FailureHintMapper.HINT_REGISTRY:
            failure_type = "other"

        suggestion, action = FailureHintMapper.HINT_REGISTRY[failure_type]

        # Format recovery_hint for display
        recovery_hint = f"{suggestion} [{action}]"

        return RecoveryHint(
            failure_type=failure_type,
            suggestion=suggestion,
            action=action,
            recovery_hint=recovery_hint,
        )

    @staticmethod
    def get_hint_by_pattern(error_output: str, failure_type: str = "") -> RecoveryHint:
        """
        Generate hint by matching error output against patterns.

        First attempts to categorize the error using regex patterns,
        then generates the corresponding hint.

        Args:
            error_output: stderr/stdout from failed execution
            failure_type: (optional) pre-categorized failure type

        Returns:
            RecoveryHint for the matched failure type
        """
        if not failure_type:
            failure_type = _categorize_by_pattern(error_output)

        return FailureHintMapper.generate_hint(failure_type)


def _categorize_by_pattern(error_output: str) -> str:
    """
    Categorize failure by regex pattern matching on error output.

    Returns one of 8 failure types, or "other" if no pattern matches.
    Order matters: check specific patterns before general ones.
    """
    output_lower = error_output.lower()

    # Patterns for each failure type (order matters: check specific first)
    patterns: dict[str, list[str]] = {
        "missing_dependency": [
            "importerror",
            "modulenotfounderror",
            "no module named",
            "cannot import",
        ],
        "oom": [
            "out of memory",
            "oom",
            "memory error",
            "heap overflow",
            "cannot allocate",
            "memoryerror",
        ],
        "context_overflow": ["context window", "context overflow", "token limit"],
        "timeout": ["timeout", "timed out", "deadline exceeded"],
        "type_error": [
            "typeerror",
            "type error",
            "mypy",
            "incompatible type",
            "type checking",
        ],
        "syntax_error": [
            "syntaxerror",
            "syntax error",
            "indentation",
            "unexpected token",
        ],
        "test_assertion": [
            "assert",
            "failed",
            "pytest",
            "unittest",
            "expected",
        ],
    }

    for failure_type, pattern_list in patterns.items():
        if any(pat in output_lower for pat in pattern_list):
            return failure_type

    return "other"


def hint_text(failure_type: str) -> str:
    """
    Convenience function: return hint as TSV-safe string.

    Args:
        failure_type: one of 8 failure categories

    Returns:
        TSV-safe hint string (no tabs, newlines, quotes)
    """
    hint = FailureHintMapper.generate_hint(failure_type)
    return hint.to_tsv()
