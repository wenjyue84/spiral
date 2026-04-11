#!/usr/bin/env python3
"""
lib/quality/parse_test_output.py

Parses test command output (pytest, vitest, bats) into JSON report format.
Writes report to test-reports/<TIMESTAMP>/report.json with pass/fail/error counts.

Usage:
  echo "test output" | python parse_test_output.py --format pytest --output-dir test-reports
  python parse_test_output.py --format pytest --input test.log --output-dir test-reports
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def parse_pytest_output(output: str) -> dict:
    """Parse pytest output and extract test counts."""
    passed = 0
    failed = 0
    errored = 0
    skipped = 0

    lines = output.split('\n')
    for line in lines:
        # Check for the final pytest summary line
        if 'passed' in line or 'failed' in line or 'error' in line:
            # Try to extract numbers from lines like "1 passed, 2 failed in 0.42s"
            match = re.search(r'=+\s*(.+?)\s*=+', line)
            if match:
                summary_line = match.group(1)
                # Parse individual counts
                passed_match = re.search(r'(\d+)\s+passed', summary_line)
                if passed_match:
                    passed = int(passed_match.group(1))

                failed_match = re.search(r'(\d+)\s+failed', summary_line)
                if failed_match:
                    failed = int(failed_match.group(1))

                error_match = re.search(r'(\d+)\s+error', summary_line)
                if error_match:
                    errored = int(error_match.group(1))

                skipped_match = re.search(r'(\d+)\s+skipped', summary_line)
                if skipped_match:
                    skipped = int(skipped_match.group(1))

    return {
        'passed': passed,
        'failed': failed,
        'errored': errored,
        'skipped': skipped,
        'total': passed + failed + errored,
    }


def parse_vitest_output(output: str) -> dict:
    """Parse vitest output and extract test counts."""
    passed = 0
    failed = 0
    errored = 0
    skipped = 0

    # Vitest summary: "PASS  [0.542s] 12 test files, 150 passed, 5 failed"
    lines = output.split('\n')
    for line in lines:
        if 'PASS' in line or 'FAIL' in line:
            passed_match = re.search(r'(\d+)\s+passed', line)
            if passed_match:
                passed = int(passed_match.group(1))

            failed_match = re.search(r'(\d+)\s+failed', line)
            if failed_match:
                failed = int(failed_match.group(1))

            error_match = re.search(r'(\d+)\s+error', line)
            if error_match:
                errored = int(error_match.group(1))

            skipped_match = re.search(r'(\d+)\s+skipped', line)
            if skipped_match:
                skipped = int(skipped_match.group(1))

    return {
        'passed': passed,
        'failed': failed,
        'errored': errored,
        'skipped': skipped,
        'total': passed + failed + errored,
    }


def parse_bats_output(output: str) -> dict:
    """Parse bats (bash automated test suite) output and extract test counts."""
    passed = 0
    failed = 0
    errored = 0

    # Bats output: "1..5" for test plan, then "ok 1 - test name" or "not ok 2 - test name"
    lines = output.split('\n')

    for line in lines:
        # Count pass/fail lines
        if re.match(r'^\s*ok\s+\d+', line):
            passed += 1
        elif re.match(r'^\s*not\s+ok\s+\d+', line):
            failed += 1

    return {
        'passed': passed,
        'failed': failed,
        'errored': errored,
        'skipped': 0,
        'total': passed + failed + errored,
    }


def create_report(
    test_counts: dict,
    exit_code: int,
    report_dir: str,
) -> dict:
    """Create a JSON report and write to test-reports/<TIMESTAMP>/report.json."""
    now = datetime.utcnow().isoformat() + 'Z'
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')

    report_path = Path(report_dir) / timestamp
    report_path.mkdir(parents=True, exist_ok=True)

    report = {
        'timestamp': now,
        'exit_code': exit_code,
        'summary': {
            'passed': test_counts.get('passed', 0),
            'failed': test_counts.get('failed', 0),
            'errored': test_counts.get('errored', 0),
            'skipped': test_counts.get('skipped', 0),
            'total': test_counts.get('total', 0),
        },
    }

    # Write report.json
    report_file = report_path / 'report.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Parse test output and write JSON report',
    )
    parser.add_argument(
        '--format',
        choices=['pytest', 'vitest', 'bats', 'auto'],
        default='auto',
        help='Test framework format (default: auto-detect)',
    )
    parser.add_argument(
        '--input',
        type=str,
        help='Input file (default: stdin)',
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='test-reports',
        help='Output directory for report (default: test-reports)',
    )
    parser.add_argument(
        '--exit-code',
        type=int,
        default=0,
        help='Exit code from test command (default: 0)',
    )

    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            output = f.read()
    else:
        output = sys.stdin.read()

    # Detect format if auto
    test_format = args.format
    if test_format == 'auto':
        if 'passed' in output and 'failed' in output:
            # Could be pytest or vitest, check for pytest-specific markers
            if '======' in output or 'test session starts' in output:
                test_format = 'pytest'
            else:
                test_format = 'vitest'
        elif 'ok' in output and 'not ok' in output:
            test_format = 'bats'
        else:
            # Default to pytest as it's most common
            test_format = 'pytest'

    # Parse based on format
    if test_format == 'pytest':
        test_counts = parse_pytest_output(output)
    elif test_format == 'vitest':
        test_counts = parse_vitest_output(output)
    elif test_format == 'bats':
        test_counts = parse_bats_output(output)
    else:
        # Fallback: assume pytest
        test_counts = parse_pytest_output(output)

    # Create report
    create_report(test_counts, args.exit_code, args.output_dir)

    # Output report location for shell to read
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    report_file = Path(args.output_dir) / timestamp / 'report.json'
    print(str(report_file))

    return 0


if __name__ == '__main__':
    sys.exit(main())
