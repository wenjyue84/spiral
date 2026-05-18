#!/usr/bin/env python3
"""
lib/assertion_extractor.py — Phase V: Auto-Extract Verifiable Assertions from AC

Parses acceptance criteria text to extract verifiable assertions (natural language patterns).
Supports automatic pytest generation for stories without explicit verification contracts.

Patterns supported:
  - "assert X" → assertion type "assert"
  - "must have Y" → assertion type "have"
  - "should return Z" → assertion type "return"
  - "contains [item]" → assertion type "contains"

Usage:
  from lib.assertion_extractor import extract_assertions, generate_pytest_assertions

  ac_list = story.get("acceptanceCriteria", [])
  assertions = extract_assertions(ac_list)
  pytest_code = generate_pytest_assertions(story, assertions)
"""

import re
import sys
from collections import namedtuple
from typing import Any, Dict, List, Optional

# Assertion tuple with confidence scoring
Assertion = namedtuple(
    "Assertion",
    ["type", "subject", "expected_value", "confidence_score", "raw_ac"],
)


def _extract_assert_pattern(ac_text: str) -> Optional[Assertion]:
    """
    Extract 'assert X' pattern.

    Examples:
      - "assert response is valid"
      - "assert status code is 200"
      - "assert data is not empty"
    """
    # Match "assert <subject> <is/is_not/equals> <expected_value>"
    match = re.search(
        r"assert\s+([^\s]+(?:\s+[^\s]+)*?)\s+(?:is|equals|=)\s+(.+?)(?:\.|;|$)",
        ac_text,
        re.IGNORECASE,
    )
    if match:
        subject = match.group(1).strip()
        expected = match.group(2).strip()
        return Assertion(
            type="assert",
            subject=subject,
            expected_value=expected,
            confidence_score=0.95,
            raw_ac=ac_text,
        )

    # Match bare "assert X" without explicit expected value
    match = re.search(r"assert\s+([^\s]+(?:\s+[^\s]+)*?)(?:\.|;|$)", ac_text, re.IGNORECASE)
    if match:
        subject = match.group(1).strip()
        return Assertion(
            type="assert",
            subject=subject,
            expected_value="true",
            confidence_score=0.85,
            raw_ac=ac_text,
        )

    return None


def _extract_must_have_pattern(ac_text: str) -> Optional[Assertion]:
    """
    Extract 'must have Y' pattern.

    Examples:
      - "must have error message"
      - "must have user ID field"
      - "must have valid authentication"
    """
    match = re.search(
        r"must\s+have\s+([^\s]+(?:\s+[^\s]+)*?)(?:\s+(?:field|property|attribute))?(?:\.|;|$)",
        ac_text,
        re.IGNORECASE,
    )
    if match:
        subject = match.group(1).strip()
        return Assertion(
            type="have",
            subject=subject,
            expected_value="present",
            confidence_score=0.90,
            raw_ac=ac_text,
        )

    return None


def _extract_should_return_pattern(ac_text: str) -> Optional[Assertion]:
    """
    Extract 'should return Z' pattern.

    Examples:
      - "should return status code 200"
      - "should return user object"
      - "should return error message"
    """
    match = re.search(
        r"should\s+return\s+([^\s]+(?:\s+[^\s]+)*?)(?:\.|;|$)",
        ac_text,
        re.IGNORECASE,
    )
    if match:
        expected = match.group(1).strip()
        # Extract subject from expected if possible (e.g., "status code" from "status code 200")
        subject_match = re.match(r"([a-z\s]+?)\s+\d+", expected)
        subject = subject_match.group(1).strip() if subject_match else expected
        return Assertion(
            type="return",
            subject=subject,
            expected_value=expected,
            confidence_score=0.90,
            raw_ac=ac_text,
        )

    return None


def _extract_contains_pattern(ac_text: str) -> Optional[Assertion]:
    """
    Extract 'contains [item]' pattern.

    Examples:
      - "contains error message"
      - "output contains timestamp"
      - "response contains user_id"
    """
    # Match with optional prefix: "output/response/result contains X"
    # The prefix and its space are optional together
    match = re.search(
        r"(?:(?:output|response|result)\s+)?contains\s+([^\s]+(?:\s+[^\s]+)*?)(?:\.|;|$)",
        ac_text,
        re.IGNORECASE,
    )
    if match:
        item = match.group(1).strip()
        return Assertion(
            type="contains",
            subject="output",
            expected_value=item,
            confidence_score=0.85,
            raw_ac=ac_text,
        )

    return None


def extract_assertions(ac_list: List[str]) -> List[Assertion]:
    """
    Extract verifiable assertions from acceptance criteria list.

    Args:
        ac_list: List of acceptance criteria strings

    Returns:
        List of Assertion namedtuples with type, subject, expected_value, confidence_score
    """
    assertions = []
    extractors = [
        _extract_assert_pattern,
        _extract_must_have_pattern,
        _extract_should_return_pattern,
        _extract_contains_pattern,
    ]

    for ac_text in ac_list:
        if not isinstance(ac_text, str) or not ac_text.strip():
            continue

        # Try extractors in order of specificity
        for extractor in extractors:
            assertion = extractor(ac_text)
            if assertion:
                assertions.append(assertion)
                break

    return assertions


def generate_pytest_assertions(story: Dict[str, Any], assertions: List[Assertion]) -> str:
    """
    Generate pytest assertion code from extracted assertions.

    Args:
        story: Story dict with id, title
        assertions: List of Assertion namedtuples

    Returns:
        Python pytest test code as string
    """
    story_id = story.get("id", "UNKNOWN")
    title = story.get("title", "Untitled")

    # Escape title for docstring
    escaped_title = title.replace('"', '\\"')

    code_lines = [
        '"""',
        f"Auto-generated assertions for {story_id}: {escaped_title}",
        '"""',
        "",
        "import pytest",
        "",
        "",
        f'@pytest.mark.{story_id.lower().replace("-", "_")}',
        f'class Test{story_id.replace("-", "_")}:',
        f'    """Auto-generated test assertions for {story_id}."""',
        "",
    ]

    # Generate test method for each assertion
    for i, assertion in enumerate(assertions, 1):
        test_name = f"test_{assertion.type}_{i}".lower()
        code_lines.append(f"    def {test_name}(self) -> None:")
        code_lines.append(f'        """Test assertion: {assertion.raw_ac}"""')

        # Generate assertion based on type
        if assertion.type == "assert":
            code_lines.append(f'        assert {assertion.subject} == "{assertion.expected_value}"')
        elif assertion.type == "have":
            code_lines.append(f'        assert "{assertion.subject}" in dir()')
        elif assertion.type == "return":
            code_lines.append(f'        # TODO: implement return value check for {assertion.expected_value}')
            code_lines.append(f'        assert True  # Placeholder')
        elif assertion.type == "contains":
            code_lines.append(f'        assert "{assertion.expected_value}" in output')

        code_lines.append("")

    return "\n".join(code_lines)


def main() -> None:
    """CLI entry point: extract assertions and generate pytest files."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Auto-extract verifiable assertions from acceptance criteria"
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., US-1413)")
    parser.add_argument("--prd-file", default="prd.json", help="Path to prd.json")
    parser.add_argument(
        "--output-dir", default=".spiral/auto_assertions", help="Output directory for .py files"
    )

    args = parser.parse_args()

    # Read prd.json
    prd_path = Path(args.prd_file)
    if not prd_path.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        with open(prd_path, encoding="utf-8") as f:
            prd_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {prd_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Find story
    stories = prd_data.get("userStories", [])
    story = None
    for s in stories:
        if s.get("id") == args.story_id:
            story = s
            break

    if not story:
        print(f"Error: story {args.story_id} not found in {prd_path}", file=sys.stderr)
        sys.exit(1)

    # Extract assertions
    ac_list = story.get("acceptanceCriteria", [])
    assertions = extract_assertions(ac_list)

    # Generate pytest code
    pytest_code = generate_pytest_assertions(story, assertions)

    # Write output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{args.story_id}.py"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pytest_code)

    print(f"Assertions generated for {args.story_id}")
    print(f"  Extracted assertions: {len(assertions)}")
    print(f"  Output: {output_file}")


if __name__ == "__main__":
    main()
