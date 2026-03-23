#!/usr/bin/env python3
"""
lib/ac_verification_runner.py — Phase V: AC Verification Runner

Executes extracted assertions independently with timeout and result aggregation.
Each assertion runs in isolation; one failure does not skip others.
Results are reported as {passed, failed, skipped, details}.

Usage:
  python lib/ac_verification_runner.py \
    --story-id <US-NNN> \
    --assertions-file .spiral/ac_checks/<US-NNN>.json \
    --timeout 30

Inputs:
  --story-id            Story ID for logging (e.g., "US-1005")
  --assertions-file     Path to .spiral/ac_checks/{story_id}.json
  --timeout             Timeout per assertion in seconds (default: 30)

Output:
  {
    "story_id": "US-1005",
    "total": 3,
    "passed": 2,
    "failed": 1,
    "skipped": 0,
    "details": [
      {
        "index": 0,
        "type": "exit_code",
        "raw_ac": "exits with 0",
        "command": "exit 0",
        "status": "passed",
        "return_code": 0,
        "stdout": "",
        "stderr": ""
      },
      ...
    ]
  }
"""

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def run_assertions(story_id: str, assertions_file: Path, timeout: int = 30) -> Dict[str, Any]:
    """
    Execute extracted assertions independently, collect results.

    Args:
      story_id: Story ID for logging (e.g., "US-1005")
      assertions_file: Path to .spiral/ac_checks/{story_id}.json
      timeout: Timeout per assertion in seconds (default: 30)

    Returns:
      {
        "story_id": str,
        "total": int,
        "passed": int,
        "failed": int,
        "skipped": int,
        "details": [
          {
            "index": int,
            "type": str,
            "raw_ac": str,
            "command": str,
            "status": "passed|failed|skipped|timeout",
            "return_code": int,
            "stdout": str,
            "stderr": str
          },
          ...
        ]
      }
    """
    if not assertions_file.exists():
        return {
            "story_id": story_id,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
            "error": f"Assertions file not found: {assertions_file}",
        }

    try:
        with open(assertions_file, encoding="utf-8") as f:
            assertion_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "story_id": story_id,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "details": [],
            "error": f"Failed to read assertions file: {e}",
        }

    # Extract assertions from the file
    extracted_assertions = assertion_data.get("extracted_assertions", [])
    manual_review = assertion_data.get("manual_review", [])

    passed = 0
    failed = 0
    skipped = len(manual_review)  # Manual review items are skipped
    details: List[Dict[str, Any]] = []

    # Run each extracted assertion
    for idx, assertion_dict in enumerate(extracted_assertions):
        assertion_type = assertion_dict.get("type", "unknown")
        raw_ac = assertion_dict.get("raw_ac", "")
        command = assertion_dict.get("command", "")
        expected = assertion_dict.get("expected", "")
        extracted = assertion_dict.get("extracted", False)

        # Skip unparseable assertions
        if not extracted:
            details.append(
                {
                    "index": idx,
                    "type": assertion_type,
                    "raw_ac": raw_ac,
                    "command": command,
                    "status": "skipped",
                    "return_code": -1,
                    "stdout": "",
                    "stderr": "Unparseable assertion",
                }
            )
            skipped += 1
            continue

        # Run the assertion command
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout,
                text=True,
                cwd=Path.cwd(),
            )
            return_code = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            # Determine if assertion passed
            # For exit_code assertions: check if return code matches expected
            # For file_exists assertions: return code 0 means file exists
            # For test_command assertions: return code 0 means tests passed
            if assertion_type == "exit_code":
                if expected == "true":
                    # Non-zero expected
                    passed_assertion = return_code != 0
                else:
                    # Specific exit code expected
                    try:
                        expected_code = int(expected)
                        passed_assertion = return_code == expected_code
                    except ValueError:
                        passed_assertion = return_code == 0
            elif assertion_type in ("file_exists", "test_command"):
                # Exit code 0 means success
                passed_assertion = return_code == 0
            elif assertion_type in ("json_field", "log_grep"):
                # For these types, we check if output contains expected pattern
                # Return code 0 is considered success
                passed_assertion = return_code == 0
            else:
                # Unknown type: treat as success if exit code 0
                passed_assertion = return_code == 0

            if passed_assertion:
                passed += 1
                status = "passed"
            else:
                failed += 1
                status = "failed"

            details.append(
                {
                    "index": idx,
                    "type": assertion_type,
                    "raw_ac": raw_ac,
                    "command": command,
                    "status": status,
                    "return_code": return_code,
                    "stdout": stdout[:500],  # Limit output size
                    "stderr": stderr[:500],
                }
            )

        except subprocess.TimeoutExpired:
            failed += 1
            details.append(
                {
                    "index": idx,
                    "type": assertion_type,
                    "raw_ac": raw_ac,
                    "command": command,
                    "status": "timeout",
                    "return_code": -1,
                    "stdout": "",
                    "stderr": f"Assertion timed out after {timeout}s",
                }
            )
        except Exception as e:
            failed += 1
            details.append(
                {
                    "index": idx,
                    "type": assertion_type,
                    "raw_ac": raw_ac,
                    "command": command,
                    "status": "failed",
                    "return_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                }
            )

    return {
        "story_id": story_id,
        "total": passed + failed,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "details": details,
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Execute extracted AC assertions and report results")
    parser.add_argument(
        "--story-id",
        required=True,
        metavar="ID",
        help="Story ID (e.g., US-1005)",
    )
    parser.add_argument(
        "--assertions-file",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to .spiral/ac_checks/{story_id}.json",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="SECS",
        help="Timeout per assertion in seconds (default: 30)",
    )

    args = parser.parse_args()
    results = run_assertions(args.story_id, args.assertions_file, args.timeout)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
