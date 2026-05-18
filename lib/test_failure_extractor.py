#!/usr/bin/env python3
"""test_failure_extractor.py — Extract test failure patterns for episodic learning.

Parses test output from Phase T (synthesized test results) to extract failure
patterns: assertion types, error messages, file paths involved. Appends patterns
to learning.md via learning_extractor.py for use in hint_recommender.py during
retry strategies.

Supports pytest, vitest, and playwright assertion patterns.
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class FailurePattern:
    """Extracted failure pattern from test output."""

    assertion_type: str  # e.g., "AssertionError", "assert", "expect"
    error_message: str  # First 100 chars of error
    file_path: str  # e.g., "tests/unit/module.py"
    framework: str  # "pytest", "vitest", "playwright"
    frequency: int = 1
    last_iteration: int = 0


def _extract_pytest_patterns(output: str) -> list[FailurePattern]:
    """Extract pytest assertion patterns.

    Matches patterns like:
    - AssertionError: ...
    - assert x == y
    - fixture "x" not found
    """
    patterns: list[FailurePattern] = []

    # Match pytest assertion errors with file paths
    assertion_pattern = r"(\w+Error):\s*([^\n]+)\n\s+File\s\"([^\"]+)\",\s+line"
    for match in re.finditer(assertion_pattern, output):
        error_type = match.group(1)
        error_msg = match.group(2)[:100].strip()
        file_path = match.group(3)
        patterns.append(
            FailurePattern(
                assertion_type=error_type,
                error_message=error_msg,
                file_path=file_path,
                framework="pytest",
            )
        )

    # Match assert statements
    assert_pattern = r"assert\s+([^\n]+)\n"
    for match in re.finditer(assert_pattern, output):
        assertion_expr = match.group(1)[:100].strip()
        patterns.append(
            FailurePattern(
                assertion_type="assert",
                error_message=assertion_expr,
                file_path="",
                framework="pytest",
            )
        )

    return patterns


def _extract_vitest_patterns(output: str) -> list[FailurePattern]:
    """Extract vitest assertion patterns.

    Matches patterns like:
    - expect(x).toBe(y)
    - AssertionError
    """
    patterns: list[FailurePattern] = []

    # Match expect().toBe() patterns
    expect_pattern = r"expect\(([^\)]+)\)\.([a-zA-Z]+)\(([^\)]*)\)"
    for match in re.finditer(expect_pattern, output):
        matcher = match.group(2)  # e.g., "toBe", "toEqual"
        assertion_expr = f"expect().{matcher}()".strip()
        patterns.append(
            FailurePattern(
                assertion_type="expect",
                error_message=assertion_expr,
                file_path="",
                framework="vitest",
            )
        )

    # Match assertion errors
    assertion_pattern = r"AssertionError:\s*([^\n]+)"
    for match in re.finditer(assertion_pattern, output):
        error_msg = match.group(1)[:100].strip()
        patterns.append(
            FailurePattern(
                assertion_type="AssertionError",
                error_message=error_msg,
                file_path="",
                framework="vitest",
            )
        )

    return patterns


def _extract_playwright_patterns(output: str) -> list[FailurePattern]:
    """Extract playwright assertion patterns.

    Matches patterns like:
    - expect(page).toHaveTitle()
    - TimeoutError
    """
    patterns: list[FailurePattern] = []

    # Match expect().toHave* or expect().toBe* patterns
    expect_pattern = r"expect\(([^\)]+)\)\.(to[A-Za-z]+)\("
    for match in re.finditer(expect_pattern, output):
        matcher = match.group(2)  # e.g., "toHaveTitle", "toBeFocused"
        assertion_expr = f"expect().{matcher}()".strip()
        patterns.append(
            FailurePattern(
                assertion_type="expect",
                error_message=assertion_expr,
                file_path="",
                framework="playwright",
            )
        )

    # Match TimeoutError
    timeout_pattern = r"(TimeoutError|Error):\s*([^\n]+)"
    for match in re.finditer(timeout_pattern, output):
        error_type = match.group(1)
        error_msg = match.group(2)[:100].strip()
        patterns.append(
            FailurePattern(
                assertion_type=error_type,
                error_message=error_msg,
                file_path="",
                framework="playwright",
            )
        )

    return patterns


def parse_test_output(output: str) -> list[FailurePattern]:
    """Parse test output to extract failure patterns.

    Detects framework (pytest/vitest/playwright) and extracts:
    - Assertion types (AssertionError, assert, expect, etc.)
    - Error messages
    - File paths

    Args:
        output: Raw test output (stdout/stderr)

    Returns:
        List of extracted failure patterns (may be empty)
    """
    if not output:
        return []

    patterns: list[FailurePattern] = []

    # Detect frameworks and extract accordingly
    if "pytest" in output.lower() or "AssertionError" in output:
        patterns.extend(_extract_pytest_patterns(output))

    if "vitest" in output.lower() or "expect(" in output:
        patterns.extend(_extract_vitest_patterns(output))

    if "playwright" in output.lower() or "page." in output.lower():
        patterns.extend(_extract_playwright_patterns(output))

    # Deduplicate by (assertion_type, error_message, framework)
    seen: set[tuple[str, str, str]] = set()
    unique_patterns: list[FailurePattern] = []
    for pattern in patterns:
        key = (pattern.assertion_type, pattern.error_message, pattern.framework)
        if key not in seen:
            seen.add(key)
            unique_patterns.append(pattern)

    return unique_patterns


def extract_from_json_output(
    test_output_path: Path,
) -> list[dict[str, Any]]:
    """Extract failure patterns from Phase T JSON output.

    Reads synthesized test output and extracts failure info from failed tests.

    Args:
        test_output_path: Path to _test_stories_output.json

    Returns:
        List of failure pattern dicts ready for learning_extractor
    """
    if not test_output_path.exists():
        return []

    try:
        with open(test_output_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    patterns: list[dict[str, Any]] = []
    stories = data.get("stories", [])

    for story in stories:
        # Extract from story description/failure info
        description = story.get("description", "")
        if description:
            extracted = parse_test_output(description)
            for pattern in extracted:
                patterns.append(asdict(pattern))

    return patterns


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Extract test failure patterns for episodic learning")
    parser.add_argument(
        "--input",
        type=str,
        help="Input file: _test_stories_output.json or raw test output",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file: patterns.jsonl",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=0,
        help="Current SPIRAL iteration number",
    )

    args = parser.parse_args()

    if not args.input:
        print("ERROR: --input required", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"WARNING: input file not found: {args.input}", file=sys.stderr)
        patterns = []
    elif args.input.endswith(".json"):
        patterns = extract_from_json_output(input_path)
    else:
        # Raw test output
        try:
            output_text = input_path.read_text(encoding="utf-8")
            patterns = [asdict(p) for p in parse_test_output(output_text)]
        except OSError:
            print(
                f"ERROR: failed to read input file: {args.input}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Add iteration number to each pattern
    for pattern in patterns:
        pattern["last_iteration"] = args.iteration

    # Write output if specified
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for pattern in patterns:
                f.write(json.dumps(pattern) + "\n")
        print(f"Extracted {len(patterns)} failure patterns to {args.output}")
    else:
        # Print to stdout
        for pattern in patterns:
            print(json.dumps(pattern))
