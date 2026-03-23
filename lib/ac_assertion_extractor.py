#!/usr/bin/env python3
"""
lib/ac_assertion_extractor.py — Phase V: AC Assertion Extractor

Parses acceptance criteria (AC) text into executable verification assertions.
Supports 5 assertion patterns and tags unparseable AC as manual_review.

Usage:
  python lib/ac_assertion_extractor.py \
    --story-id <US-NNN> \
    --prd-file prd.json \
    --output-dir .spiral/ac_checks/

Inputs:
  --story-id        Story ID to extract assertions from (e.g., "US-1004")
  --prd-file        Path to prd.json containing story definitions
  --output-dir      Directory to write assertion JSON files (created if missing)

Output:
  .spiral/ac_checks/{story_id}.json:
    {
      "story_id": "US-1004",
      "total_assertions": 3,
      "extracted_assertions": [
        {
          "type": "exit_code",
          "raw_ac": "command exits with 0",
          "command": "echo $?",
          "expected": "0",
          "extracted": true
        },
        ...
      ],
      "manual_review": [
        {
          "raw_ac": "some complex AC that couldn't be parsed",
          "extracted": false
        }
      ],
      "extraction_metadata": {
        "timestamp": "2026-03-23T10:15:30Z",
        "total_ac_items": 10,
        "successfully_extracted": 7,
        "requires_manual_review": 3
      }
    }
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Assertion:
    """Executable verification assertion extracted from AC text."""

    type: str  # exit_code, file_exists, test_command, json_field, log_grep
    raw_ac: str  # Original AC text
    command: str  # Executable command to verify
    expected: str  # Expected result/output
    extracted: bool  # True if successfully extracted, False for manual_review


def extract_exit_code(ac_text: str) -> Optional[Assertion]:
    """
    Extract exit code assertion.

    Patterns:
      - "exits with 0", "exits 0", "exit code 0"
      - "exits with non-zero", "exits non-zero"
    """
    # Match "exits" or "exit code" followed by 0 or specific code
    match = re.search(r"(?:exits?|exit\s+code)\s+(?:with\s+)?(\d+)", ac_text, re.IGNORECASE)
    if match:
        exit_code = match.group(1)
        return Assertion(
            type="exit_code",
            raw_ac=ac_text,
            command=f"exit {exit_code}",
            expected=exit_code,
            extracted=True,
        )

    # Match "exits with non-zero"
    if re.search(r"exits?(?:\s+with)?\s+non-zero", ac_text, re.IGNORECASE):
        return Assertion(
            type="exit_code",
            raw_ac=ac_text,
            command="test $? -ne 0",
            expected="true",
            extracted=True,
        )

    return None


def extract_file_exists(ac_text: str) -> Optional[Assertion]:
    """
    Extract file existence assertion.

    Patterns:
      - "File to create: path/to/file"
      - "file X is created", "creates file X"
      - "file X should exist"
    """
    # Match "File to create: <path>" - path includes dots and slashes
    match = re.search(r"File\s+to\s+create:\s+([^\s,;]+)", ac_text, re.IGNORECASE)
    if match:
        filepath = match.group(1)
        return Assertion(
            type="file_exists",
            raw_ac=ac_text,
            command=f"test -f {filepath}",
            expected="file_exists",
            extracted=True,
        )

    # Match "creates file X" or "creates file X is created" - filepath includes dots
    match = re.search(r"creates?\s+file\s+([^\s,;]+)(?:\s+(?:is\s+)?created)?", ac_text, re.IGNORECASE)
    if match:
        filepath = match.group(1)
        return Assertion(
            type="file_exists",
            raw_ac=ac_text,
            command=f"test -f {filepath}",
            expected="file_exists",
            extracted=True,
        )

    # Match "file X is created" - filepath includes dots
    match = re.search(r"file\s+([^\s,;]+)\s+is\s+created", ac_text, re.IGNORECASE)
    if match:
        filepath = match.group(1)
        return Assertion(
            type="file_exists",
            raw_ac=ac_text,
            command=f"test -f {filepath}",
            expected="file_exists",
            extracted=True,
        )

    # Match "file X should exist" - filepath includes dots
    match = re.search(r"file\s+([^\s,;]+)\s+(?:should\s+)?exist", ac_text, re.IGNORECASE)
    if match:
        filepath = match.group(1)
        return Assertion(
            type="file_exists",
            raw_ac=ac_text,
            command=f"test -f {filepath}",
            expected="file_exists",
            extracted=True,
        )

    return None


def extract_test_command(ac_text: str) -> Optional[Assertion]:
    """
    Extract test command assertion.

    Patterns:
      - "uv run pytest X", "pytest X", "run tests in X"
      - "vitest", "jest", "bats tests"
    """
    # Match explicit test commands: "uv run pytest X", "pytest X", etc.
    # Test path includes dots, slashes, stops at space/comma/semicolon/paren
    match = re.search(r"(uv\s+run\s+pytest|pytest|vitest|jest|bats?)\s+([^\s,;)]+)", ac_text, re.IGNORECASE)
    if match:
        test_runner = match.group(1).lower()
        test_path = match.group(2)
        command = f"{test_runner} {test_path}"
        return Assertion(
            type="test_command",
            raw_ac=ac_text,
            command=command,
            expected="exit_code_0",
            extracted=True,
        )

    # Match "run tests in X" or "tests pass in X"
    match = re.search(r"(?:run\s+)?tests?(?:\s+pass)?\s+in\s+([^\s,;)]+)", ac_text, re.IGNORECASE)
    if match:
        test_path = match.group(1)
        return Assertion(
            type="test_command",
            raw_ac=ac_text,
            command=f"pytest {test_path}",
            expected="exit_code_0",
            extracted=True,
        )

    return None


def extract_json_field(ac_text: str) -> Optional[Assertion]:
    """
    Extract JSON field assertion.

    Patterns:
      - "contains field Y", "JSON contains field Y"
      - "returns field X in JSON"
      - "output includes X"
    """
    # Match "contains field Y" or "JSON contains field Y" - field includes dots/underscores
    match = re.search(r"(?:JSON\s+)?contains?\s+(?:the\s+)?field\s+([^\s,;)]+)", ac_text, re.IGNORECASE)
    if match:
        field_name = match.group(1)
        return Assertion(
            type="json_field",
            raw_ac=ac_text,
            command=f"jq .{field_name}",
            expected="field_exists",
            extracted=True,
        )

    # Match "returns field X in JSON"
    match = re.search(r"returns?(?:\s+the)?\s+field\s+([^\s,;)]+)\s+in\s+JSON", ac_text, re.IGNORECASE)
    if match:
        field_name = match.group(1)
        return Assertion(
            type="json_field",
            raw_ac=ac_text,
            command=f"jq .{field_name}",
            expected="field_exists",
            extracted=True,
        )

    # Match "output includes X" (generic field match)
    match = re.search(r"output\s+(?:includes?|contains?)\s+([^\s,;)]+)", ac_text, re.IGNORECASE)
    if match:
        field_name = match.group(1)
        return Assertion(
            type="json_field",
            raw_ac=ac_text,
            command=f"grep -q {field_name}",
            expected="found",
            extracted=True,
        )

    return None


def extract_log_grep(ac_text: str) -> Optional[Assertion]:
    """
    Extract log/grep assertion.

    Patterns:
      - "log entry matching X", "logs contain X"
      - "output contains X", "prints X"
      - "error message X appears"
    """
    # Match "log entry matching X" - handle both quoted and unquoted patterns
    match = re.search(r"log\s+entr(?:y|ies)\s+matching\s+(?:['\"]([^'\"]+)['\"]|([^\s,;.]+))", ac_text, re.IGNORECASE)
    if match:
        pattern = match.group(1) or match.group(2)
        return Assertion(
            type="log_grep",
            raw_ac=ac_text,
            command=f"grep {pattern}",
            expected="match_found",
            extracted=True,
        )

    # Match "logs contain X" or "output contains X"
    pattern_logs = r"(?:logs?|output)\s+(?:contains?|includes?)\s+(?:['\"]([^'\"]+)['\"]|([^\s,;.]+))"
    match = re.search(pattern_logs, ac_text, re.IGNORECASE)
    if match:
        pattern = match.group(1) or match.group(2)
        return Assertion(
            type="log_grep",
            raw_ac=ac_text,
            command=f"grep {pattern}",
            expected="match_found",
            extracted=True,
        )

    # Match "prints X" or "prints error X" - handle quoted and unquoted
    match = re.search(r"prints?\s+(?:error\s+)?(?:['\"]([^'\"]+)['\"]|([^\s,;.]+))", ac_text, re.IGNORECASE)
    if match:
        pattern = match.group(1) or match.group(2)
        return Assertion(
            type="log_grep",
            raw_ac=ac_text,
            command=f"grep {pattern}",
            expected="match_found",
            extracted=True,
        )

    # Match "error message X appears" - handle quoted and unquoted
    match = re.search(r"error\s+messages?\s+(?:['\"]([^'\"]+)['\"]|([^\s,;.]+))\s+appears?", ac_text, re.IGNORECASE)
    if match:
        pattern = match.group(1) or match.group(2)
        return Assertion(
            type="log_grep",
            raw_ac=ac_text,
            command=f"grep {pattern}",
            expected="match_found",
            extracted=True,
        )

    return None


def extract_assertions(story: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract all assertions from a story's acceptance criteria.

    Args:
        story: Story dict from prd.json with 'acceptanceCriteria' list

    Returns:
        Dict with:
          - extracted_assertions: list of Assertion dicts that were parsed
          - manual_review: list of AC text that couldn't be parsed
          - extraction_metadata: counts and timestamps
    """
    story_id = story.get("id", "UNKNOWN")
    ac_list = story.get("acceptanceCriteria", [])

    extracted: List[Dict[str, Any]] = []
    manual_review: List[Dict[str, Any]] = []

    # Try to extract assertions in order of pattern specificity
    # Most specific first: test_command, file_exists, exit_code, json_field, log_grep
    extractors = [
        extract_test_command,
        extract_file_exists,
        extract_exit_code,
        extract_json_field,
        extract_log_grep,
    ]

    for ac_text in ac_list:
        if not isinstance(ac_text, str) or not ac_text.strip():
            continue

        assertion_found = False
        for extractor in extractors:
            assertion = extractor(ac_text)
            if assertion:
                extracted.append(asdict(assertion))
                assertion_found = True
                break

        if not assertion_found:
            manual_review.append({"raw_ac": ac_text, "extracted": False})

    # Build metadata
    total_ac = len([ac for ac in ac_list if isinstance(ac, str) and ac.strip()])
    # Use isoformat with timespec='seconds' and replace +00:00 with Z for consistency
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    return {
        "story_id": story_id,
        "total_assertions": len(extracted) + len(manual_review),
        "extracted_assertions": extracted,
        "manual_review": manual_review,
        "extraction_metadata": {
            "timestamp": timestamp,
            "total_ac_items": total_ac,
            "successfully_extracted": len(extracted),
            "requires_manual_review": len(manual_review),
        },
    }


def main() -> None:
    """Parse CLI args and extract assertions from story."""
    parser = argparse.ArgumentParser(
        description="Extract executable assertions from acceptance criteria"
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., US-1004)")
    parser.add_argument("--prd-file", default="prd.json", help="Path to prd.json")
    parser.add_argument("--output-dir", default=".spiral/ac_checks", help="Output directory")

    args = parser.parse_args()

    # Read prd.json
    prd_path = Path(args.prd_file)
    if not prd_path.exists():
        print(f"Error: {prd_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        with open(prd_path) as f:
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
    result = extract_assertions(story)

    # Write output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{args.story_id}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Assertions extracted for {args.story_id}")
    print(f"  Successfully extracted: {result['extraction_metadata']['successfully_extracted']}")
    print(f"  Requires manual review: {result['extraction_metadata']['requires_manual_review']}")
    print(f"  Output: {output_file}")


if __name__ == "__main__":
    main()
