#!/usr/bin/env python3
"""
failure_categorizer.py — Classifies Phase I implementation failures into categories.

Parses ralph stderr/stdout output and categorizes the root cause for smarter retries
and better learning via Phase L. Returns standardized failure_type and failure_message
for storage in results.tsv.

Categories (7+):
- missing_dependency: ImportError, ModuleNotFoundError, missing package
- syntax_error: SyntaxError, IndentationError, invalid Python/shell syntax
- type_error: TypeError, mypy/type checker errors, type mismatch
- test_assertion: pytest assertion failures, test timeouts, unittest errors
- timeout: execution timeout, time limit exceeded
- oom: Out of memory, memory exhaustion, heap overflow
- context_overflow: Context window exceeded, prompt too long
- other: unclassified errors
"""

from __future__ import annotations


def categorize_failure(stderr: str, stdout: str) -> tuple[str, str]:
    """
    Classify a failure from ralph output into a category and extract error message.

    Args:
        stderr: stderr output from ralph worker
        stdout: stdout output from ralph worker

    Returns:
        (failure_type, failure_message) tuple where:
        - failure_type: one of 'missing_dependency', 'syntax_error', 'type_error',
                       'test_assertion', 'timeout', 'oom', 'context_overflow', 'other'
        - failure_message: extracted error message (first line of error, truncated to 200 chars)
    """
    combined = stderr + "\n" + stdout
    failure_type = _classify(combined)
    failure_message = _extract_message(combined, failure_type)
    return (failure_type, failure_message)


def _classify(output: str) -> str:
    """
    Determine failure category from output text.

    Check patterns in order of specificity (most to least specific).
    """
    output_lower = output.lower()

    # missing_dependency: ImportError, ModuleNotFoundError, 'No module named'
    if any(
        pat in output_lower
        for pat in [
            "importerror",
            "modulenotfounderror",
            "no module named",
            "cannot import",
            "missing dependency",
            "not found: module",
        ]
    ):
        return "missing_dependency"

    # oom: memory-related errors
    if any(
        pat in output_lower
        for pat in [
            "out of memory",
            "oom",
            "memory error",
            "heap overflow",
            "cannot allocate",
            "memoryerror",
        ]
    ):
        return "oom"

    # context_overflow: context window exceeded
    if any(
        pat in output_lower
        for pat in [
            "context window",
            "context overflow",
            "token limit",
            "too many tokens",
            "prompt too long",
        ]
    ):
        return "context_overflow"

    # timeout: timeout/deadline exceeded
    if any(
        pat in output_lower
        for pat in [
            "timeout",
            "timed out",
            "deadline exceeded",
            "time limit",
            "execution timeout",
            "hang",
        ]
    ):
        return "timeout"

    # type_error: TypeError, mypy errors, type mismatch
    if any(
        pat in output_lower
        for pat in [
            "typeerror",
            "type error",
            "mypy",
            "type checking",
            "type mismatch",
            "incompatible type",
            "argument of type",
        ]
    ):
        return "type_error"

    # syntax_error: SyntaxError, IndentationError, invalid syntax
    if any(
        pat in output_lower
        for pat in [
            "syntaxerror",
            "syntax error",
            "indentationerror",
            "invalid syntax",
            "unexpected token",
        ]
    ):
        return "syntax_error"

    # test_assertion: pytest failures, assertion errors, test failures
    if any(
        pat in output_lower
        for pat in [
            "assert",
            "failed",
            "pytest",
            "unittest",
            "test error",
            "assertion failure",
            "expected",
        ]
    ):
        return "test_assertion"

    # default to 'other' for unclassified errors
    return "other"


def _extract_message(output: str, failure_type: str) -> str:
    """
    Extract a meaningful error message from output.

    Tries to find the first error line containing the failure pattern,
    or falls back to the first non-empty line.
    """
    lines = output.split("\n")

    # Patterns to search for the error line (by failure_type)
    patterns = _get_patterns_for_type(failure_type)

    # Try to find a line matching the failure type patterns
    for line in lines:
        if line.strip():
            for pat in patterns:
                if pat in line.lower():
                    msg = line.strip()
                    # Truncate to 200 characters for TSV storage
                    return msg[:200] if msg else "unknown error"

    # Fallback: return the first non-empty line
    for line in lines:
        if line.strip():
            msg = line.strip()
            return msg[:200] if msg else "unknown error"

    return "unknown error"


def _get_patterns_for_type(failure_type: str) -> list[str]:
    """Return search patterns for a given failure type."""
    patterns_map: dict[str, list[str]] = {
        "missing_dependency": [
            "importerror",
            "modulenotfounderror",
            "no module named",
            "cannot import",
        ],
        "syntax_error": ["syntaxerror", "syntax error", "indentation"],
        "type_error": ["typeerror", "type error", "mypy"],
        "test_assertion": ["assert", "failed", "pytest", "unittest"],
        "timeout": ["timeout", "timed out", "deadline"],
        "oom": ["out of memory", "oom", "memory error"],
        "context_overflow": ["context window", "token limit"],
        "other": ["error", "exception"],
    }
    return patterns_map.get(failure_type, ["error"])
