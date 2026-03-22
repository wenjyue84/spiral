#!/usr/bin/env python3
"""Validate results.tsv for data integrity: duplicates and token ranges."""

import csv
import os
from typing import Any, TypedDict


class CheckCounts(TypedDict):
    """Check counts dict."""

    rows: int
    checks_run: int


class ValidationResult(TypedDict):
    """Result from validate()."""

    errors: list[str]
    warnings: list[str]
    check_counts: CheckCounts


def validate(tsv_path: str) -> ValidationResult:
    """
    Validate results.tsv for data quality.

    Checks:
    - Duplicate story_id rows
    - Token count columns in range [0, 1000000]

    Args:
        tsv_path: Path to results.tsv

    Returns:
        dict with errors, warnings, check_counts
    """
    errors: list[str] = []
    warnings: list[str] = []
    rows_checked = 0
    checks_run = 0

    if not os.path.isfile(tsv_path):
        errors.append(f"results.tsv not found: {tsv_path}")
        return {
            "errors": errors,
            "warnings": warnings,
            "check_counts": {"rows": 0, "checks_run": 0},
        }

    rows: list[dict[str, Any]] = []
    try:
        with open(tsv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader) if reader else []
    except IOError as e:
        errors.append(f"Failed to read {tsv_path}: {e}")
        return {
            "errors": errors,
            "warnings": warnings,
            "check_counts": {"rows": 0, "checks_run": 0},
        }

    # Check 1: Duplicate story_id rows
    seen_story_ids: set[str] = set()
    for row in rows:
        story_id = row.get("story_id", "").strip()
        if story_id:
            if story_id in seen_story_ids:
                errors.append(f"Duplicate story_id: {story_id}")
                checks_run += 1
            else:
                seen_story_ids.add(story_id)
                checks_run += 1

    # Check 2: Token count ranges (any numeric column with 'token' in name)
    token_columns = [k for k in (rows[0].keys() if rows else []) if "token" in k.lower()]

    for row in rows:
        rows_checked += 1
        for token_col in token_columns:
            val_str = row.get(token_col, "").strip()
            if val_str:
                try:
                    val = int(val_str)
                    if val < 0 or val > 1000000:
                        errors.append(f"Token count out of range on row {rows_checked}: {token_col}={val}")
                    checks_run += 1
                except ValueError:
                    warnings.append(f"Row {rows_checked}: {token_col} not an integer: {val_str}")

    return {
        "errors": errors,
        "warnings": warnings,
        "check_counts": {"rows": rows_checked, "checks_run": checks_run},
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <tsv_path>")
        sys.exit(1)

    result = validate(sys.argv[1])
    print(json.dumps(result, indent=2))
