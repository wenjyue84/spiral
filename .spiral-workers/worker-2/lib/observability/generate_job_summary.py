#!/usr/bin/env python3
"""Generate GitHub Actions job summary with test results, coverage, and lint status."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def extract_coverage_stats(xml_file: str) -> dict[str, Any] | None:
    """Parse coverage.xml and extract stats."""
    xml_path = Path(xml_file)
    if not xml_path.exists():
        return None
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        # Extract line-rate from root element
        if "line-rate" in root.attrib:
            line_rate = float(root.attrib["line-rate"]) * 100
            return {"coverage_pct": line_rate}
    except Exception as e:
        print(f"::warning::Could not parse {xml_file}: {e}", file=sys.stderr)
    return None


def parse_pytest_output(output: str) -> dict[str, int]:
    """Parse pytest summary line to extract pass/fail/skip counts."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}

    # Look for pytest summary line like "123 passed in 5.23s"
    for line in output.split("\n"):
        if "passed" in line or "failed" in line or "skipped" in line or "error" in line:
            # Try to extract numbers
            parts = line.split()
            for i, part in enumerate(parts):
                if part == "passed" and i > 0:
                    try:
                        counts["passed"] = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass
                elif part == "failed" and i > 0:
                    try:
                        counts["failed"] = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass
                elif part == "skipped" and i > 0:
                    try:
                        counts["skipped"] = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass
                elif part == "error" and i > 0:
                    try:
                        counts["errors"] = int(parts[i - 1])
                    except (ValueError, IndexError):
                        pass
    return counts


def generate_test_summary(coverage_file: str = "coverage.xml") -> str:
    """Generate a markdown table with test results and coverage."""
    summary_lines = ["## Test Results", ""]

    # Read coverage
    coverage_data = extract_coverage_stats(coverage_file)
    coverage_pct = coverage_data["coverage_pct"] if coverage_data else 0

    # Parse pytest output from stdin if provided
    pytest_output = sys.stdin.read() if not sys.stdin.isatty() else ""
    counts = parse_pytest_output(pytest_output)

    # Build markdown table
    summary_lines.append("| Metric | Value |")
    summary_lines.append("|--------|-------|")
    summary_lines.append(f"| **Passed** | {counts['passed']} ✓ |")
    summary_lines.append(f"| **Failed** | {counts['failed']} ✗ |")
    summary_lines.append(f"| **Skipped** | {counts['skipped']} ⊘ |")
    summary_lines.append(f"| **Coverage** | {coverage_pct:.1f}% |")

    return "\n".join(summary_lines)


def generate_lint_summary(shell_lint_ok: bool, shell_count: int, py_lint_ok: bool, py_count: int = 0) -> str:
    """Generate markdown summary for lint results."""
    summary_lines = ["## Lint Results", ""]
    summary_lines.append("| Check | Status | Details |")
    summary_lines.append("|-------|--------|---------|")

    shell_status = "✓ Pass" if shell_lint_ok else "✗ Fail"
    py_status = "✓ Pass" if py_lint_ok else "✗ Fail"

    summary_lines.append(f"| ShellCheck + Shfmt | {shell_status} | {shell_count} files checked |")
    summary_lines.append(f"| Ruff (Python) | {py_status} | Python linting |")

    return "\n".join(summary_lines)


def generate_mypy_summary(mypy_ok: bool, error_count: int = 0) -> str:
    """Generate markdown summary for mypy results."""
    summary_lines = ["## Type Check Results", ""]
    summary_lines.append("| Check | Status | Details |")
    summary_lines.append("|-------|--------|---------|")

    status = "✓ Pass" if mypy_ok else "✗ Fail"
    summary_lines.append(f"| MyPy (Strict) | {status} | {error_count} errors |")

    return "\n".join(summary_lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "test":
            summary = generate_test_summary()
            print(summary)
        elif mode == "lint":
            shell_ok = sys.argv[2].lower() == "true" if len(sys.argv) > 2 else True
            print(generate_lint_summary(shell_ok, 0, True))
        elif mode == "mypy":
            mypy_ok = sys.argv[2].lower() == "true" if len(sys.argv) > 2 else True
            errors = int(sys.argv[3]) if len(sys.argv) > 3 else 0
            print(generate_mypy_summary(mypy_ok, errors))
    else:
        print(generate_test_summary())
