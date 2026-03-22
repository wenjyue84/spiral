#!/usr/bin/env python3
"""
lib/test_blame.py — Phase V: Test Blame Attribution

Correlates newly failing tests to the story that broke them by matching
test file names to changed source files.

Usage:
  python lib/test_blame.py \
    --baseline-results <path/to/test_baseline.json> \
    --new-results <path/to/report.json> \
    --changed-files <path/to/changed_files.txt> \
    --story-id <US-NNN> \
    --output <path/to/attribution.json>

Inputs:
  --baseline-results    Path to baseline test results JSON
  --new-results         Path to new test results JSON (after Phase I)
  --changed-files       Path to file (one per line) of files modified by story
  --story-id            Story ID to attribute failures to (e.g., "US-782")

Output:
  attribution.json:
    {
      "story_id": "US-782",
      "newly_failed_tests": ["test_foo.py::test_bar", ...],
      "changed_files": ["lib/foo.py", ...],
      "attribution": [
        {
          "test": "test_foo.py::test_bar",
          "likely_source": "lib/foo.py",
          "confidence": "high"
        },
        ...
      ]
    }
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


def parse_test_results(results_json: Dict[str, Any]) -> Dict[str, str]:
    """
    Parse pytest report.json format to extract test status.

    Supports both raw pytest output and processed report.json formats.

    Args:
        results_json: Parsed JSON from report.json or custom test results format

    Returns:
        Dict mapping test name -> status ("passed", "failed", "skipped", "error")
    """
    tests = {}

    # Handle pytest report.json format (with "tests" key as list)
    if "tests" in results_json:
        tests_container = results_json.get("tests", [])
        if isinstance(tests_container, list):
            # pytest report.json format: list of test objects
            for test_item in tests_container:
                if isinstance(test_item, dict):
                    test_name = test_item.get("nodeid", "")
                    outcome = test_item.get("outcome", "unknown")
                    if test_name:
                        tests[test_name] = outcome
        elif isinstance(tests_container, dict):
            # Custom format: dict of test_name -> status
            for key, value in tests_container.items():
                if isinstance(value, str) and value in ("passed", "failed", "skipped", "error"):
                    tests[key] = value

    # Handle custom test results format (flat dict without "tests" key)
    elif isinstance(results_json, dict):
        for key, value in results_json.items():
            if isinstance(value, str) and value in ("passed", "failed", "skipped", "error"):
                tests[key] = value

    return tests


def find_newly_failed_tests(baseline: Dict[str, str], current: Dict[str, str]) -> List[str]:
    """
    Find tests that passed in baseline but failed in current run.

    Args:
        baseline: Dict of test_name -> status from baseline
        current: Dict of test_name -> status from current run

    Returns:
        List of test names that newly failed
    """
    newly_failed = []
    for test_name, status in current.items():
        baseline_status = baseline.get(test_name, "unknown")
        # A test newly failed if it was passing (or missing) before and failing now
        if baseline_status in ("passed", "unknown") and status == "failed":
            newly_failed.append(test_name)
    return newly_failed


def extract_test_file(test_name: str) -> str:
    """Extract the test file base name (without 'test_' prefix) from a pytest node ID.

    Examples:
        "tests/test_foo.py::test_bar" -> "foo"  (test_foo -> foo)
        "tests/test_merge.py::TestClass::test_method" -> "merge"  (test_merge -> merge)
    """
    # pytest node IDs are like "path/to/test_foo.py::test_name"
    if "::" in test_name:
        file_part = test_name.split("::")[0]
    else:
        file_part = test_name

    # Remove .py extension and path prefix
    base = os.path.basename(file_part)
    if base.endswith(".py"):
        base = base[:-3]

    # Remove 'test_' prefix if present (test_foo -> foo)
    if base.startswith("test_"):
        base = base[5:]  # Remove 'test_' (5 characters)

    return base


def extract_source_file(file_path: str) -> str:
    """Extract the base name from a source file path.

    Examples:
        "lib/foo.py" -> "foo"
        "lib/subdir/bar.py" -> "bar"
    """
    base = os.path.basename(file_path)
    if base.endswith(".py"):
        base = base[:-3]
    return base


def attribute_test_to_file(test_name: str, changed_files: List[str]) -> Tuple[Optional[str], str]:
    """
    Match a failing test to a changed source file using naming conventions.

    Heuristic: "test_foo" matches "lib/foo.py" or "src/foo.py"

    Args:
        test_name: Full pytest node ID (e.g., "tests/test_foo.py::test_bar")
        changed_files: List of file paths that were changed (e.g., ["lib/foo.py"])

    Returns:
        (matched_file, confidence): matched source file or None, and confidence level
    """
    test_base = extract_test_file(test_name)

    # Exact match: look for files where source name == test base
    for file_path in changed_files:
        source_base = extract_source_file(file_path)
        if source_base == test_base:
            return (file_path, "high")

    # Partial match: if only one file changed, assume it's the culprit
    if len(changed_files) == 1:
        return (changed_files[0], "medium")

    # No match found
    return (None, "low")


def blame_tests(
    baseline_results: Dict[str, Any],
    new_results: Dict[str, Any],
    changed_files: List[str],
    story_id: str
) -> Dict[str, Any]:
    """
    Main blame attribution logic.

    Args:
        baseline_results: Parsed baseline test results JSON
        new_results: Parsed new test results JSON
        changed_files: List of file paths modified by the story
        story_id: Story ID to attribute to (e.g., "US-782")

    Returns:
        Attribution result dict with newly_failed_tests and attribution details
    """
    # Parse test results
    baseline_tests = parse_test_results(baseline_results)
    current_tests = parse_test_results(new_results)

    # Find newly failed tests
    newly_failed = find_newly_failed_tests(baseline_tests, current_tests)

    # Attribute each failure to a changed file
    attribution = []
    for test_name in newly_failed:
        matched_file, confidence = attribute_test_to_file(test_name, changed_files)
        attribution.append({
            "test": test_name,
            "likely_source": matched_file,
            "confidence": confidence
        })

    return {
        "story_id": story_id,
        "newly_failed_tests": newly_failed,
        "changed_files": changed_files,
        "attribution": attribution
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attribute failing tests to the story that broke them"
    )
    parser.add_argument(
        "--baseline-results",
        required=True,
        help="Path to baseline test results JSON"
    )
    parser.add_argument(
        "--new-results",
        required=True,
        help="Path to new test results JSON"
    )
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Path to file listing changed files (one per line)"
    )
    parser.add_argument(
        "--story-id",
        required=True,
        help="Story ID (e.g., US-782)"
    )
    parser.add_argument(
        "--output",
        help="Output file for attribution results (default: stdout)"
    )

    args = parser.parse_args()

    # Load baseline results
    try:
        with open(args.baseline_results, "r", encoding="utf-8") as f:
            baseline = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Baseline file not found: {args.baseline_results}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: Baseline JSON parse error: {e}", file=sys.stderr)
        return 1

    # Load new results
    try:
        with open(args.new_results, "r", encoding="utf-8") as f:
            new_results = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: New results file not found: {args.new_results}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: New results JSON parse error: {e}", file=sys.stderr)
        return 1

    # Load changed files
    changed_files = []
    try:
        with open(args.changed_files, "r", encoding="utf-8") as f:
            changed_files = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"ERROR: Changed files file not found: {args.changed_files}", file=sys.stderr)
        return 1

    # Run attribution
    result = blame_tests(baseline, new_results, changed_files, args.story_id)

    # Output
    output_json = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Attribution saved to {args.output}")
    else:
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
