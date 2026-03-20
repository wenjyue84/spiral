#!/usr/bin/env python3
"""
validate_results_tsv.py — Validate results.tsv data quality against prd.json.

Performs 5 validation checks:
  1. Missing story_ids from prd.json
  2. Duplicate (story_id, iteration, attempt) tuples
  3. token_count outside [50, 500000]
  4. phase_duration_ms outside [100, 600000]
  5. model not in {haiku, sonnet, opus}

Returns dict with errors, warnings, passed_checks, total_rows_checked.
"""

import csv
import json
import os
from typing import Any, TypedDict


class ValidationResult(TypedDict):
    """Result dict from validate()."""

    errors: list[str]
    warnings: list[str]
    passed_checks: int
    total_rows_checked: int


VALID_MODELS = {"haiku", "sonnet", "opus"}
TOKEN_COUNT_MIN = 50
TOKEN_COUNT_MAX = 500000
DURATION_MIN = 100  # milliseconds
DURATION_MAX = 600000  # milliseconds


def validate(tsv_path: str, prd_path: str) -> ValidationResult:
    """
    Validate results.tsv for data quality issues.

    Args:
        tsv_path: Path to results.tsv
        prd_path: Path to prd.json

    Returns:
        dict with errors, warnings, passed_checks, total_rows_checked
    """
    errors: list[str] = []
    warnings: list[str] = []
    passed_checks = 0
    total_rows_checked = 0

    # Load prd.json to get canonical story IDs
    prd_story_ids: set[str] = set()
    if os.path.isfile(prd_path):
        try:
            with open(prd_path, encoding="utf-8") as f:
                prd_data = json.load(f)
                for story in prd_data.get("userStories", []):
                    prd_story_ids.add(story.get("id", ""))
        except (json.JSONDecodeError, IOError) as e:
            warnings.append(f"Could not load prd.json: {e}")
            return {
                "errors": errors,
                "warnings": warnings,
                "passed_checks": passed_checks,
                "total_rows_checked": total_rows_checked,
            }
    else:
        warnings.append(f"prd.json not found at {prd_path}")

    # Read results.tsv
    if not os.path.isfile(tsv_path):
        errors.append(f"results.tsv not found at {tsv_path}")
        return {
            "errors": errors,
            "warnings": warnings,
            "passed_checks": passed_checks,
            "total_rows_checked": total_rows_checked,
        }

    rows: list[dict[str, Any]] = []
    try:
        with open(tsv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                errors.append("results.tsv is empty or malformed")
                return {
                    "errors": errors,
                    "warnings": warnings,
                    "passed_checks": passed_checks,
                    "total_rows_checked": total_rows_checked,
                }
            rows = list(reader)
    except IOError as e:
        errors.append(f"Could not read results.tsv: {e}")
        return {
            "errors": errors,
            "warnings": warnings,
            "passed_checks": passed_checks,
            "total_rows_checked": total_rows_checked,
        }

    # Track (story_id, iteration, attempt) tuples for deduplication
    seen_tuples: set[tuple[str, str, str]] = set()

    # Check 1: story_ids in prd.json are present in results.tsv
    for story_id in prd_story_ids:
        found = any(row.get("story_id", "") == story_id for row in rows)
        if not found and story_id:
            errors.append(f"story_id '{story_id}' from prd.json missing from results.tsv")
        else:
            if story_id:
                passed_checks += 1

    # Iterate through rows and perform checks 2-5
    for row in rows:
        total_rows_checked += 1

        story_id = row.get("story_id", "")
        iteration = row.get("iteration", "")
        attempt = row.get("attempt", "")

        # Check 2: Detect duplicate (story_id, iteration, attempt) tuples
        tuple_key = (story_id, iteration, attempt)
        if tuple_key in seen_tuples:
            errors.append(f"Duplicate row: story_id='{story_id}', iteration='{iteration}', attempt='{attempt}'")
        else:
            if story_id and iteration and attempt:
                seen_tuples.add(tuple_key)
                passed_checks += 1

        # Check 3: token_count in [50, 500000]
        token_count_str = row.get("token_count", "")
        if token_count_str:
            try:
                token_count = int(token_count_str)
                if not (TOKEN_COUNT_MIN <= token_count <= TOKEN_COUNT_MAX):
                    errors.append(
                        f"Row {total_rows_checked}: token_count {token_count} "
                        f"outside [{TOKEN_COUNT_MIN}, {TOKEN_COUNT_MAX}]"
                    )
                else:
                    passed_checks += 1
            except ValueError:
                errors.append(f"Row {total_rows_checked}: token_count '{token_count_str}' is not an integer")
        else:
            warnings.append(f"Row {total_rows_checked}: token_count field is empty")

        # Check 4: phase_duration_ms in [100, 600000]
        duration_str = row.get("phase_duration_ms", "")
        if duration_str:
            try:
                duration = int(duration_str)
                if not (DURATION_MIN <= duration <= DURATION_MAX):
                    errors.append(
                        f"Row {total_rows_checked}: phase_duration_ms {duration} "
                        f"outside [{DURATION_MIN}, {DURATION_MAX}]"
                    )
                else:
                    passed_checks += 1
            except ValueError:
                errors.append(f"Row {total_rows_checked}: phase_duration_ms '{duration_str}' is not an integer")
        else:
            warnings.append(f"Row {total_rows_checked}: phase_duration_ms field is empty")

        # Check 5: model in {haiku, sonnet, opus}
        model = row.get("model", "")
        if model:
            if model not in VALID_MODELS:
                errors.append(f"Row {total_rows_checked}: model '{model}' not in {VALID_MODELS}")
            else:
                passed_checks += 1
        else:
            warnings.append(f"Row {total_rows_checked}: model field is empty")

    return {
        "errors": errors,
        "warnings": warnings,
        "passed_checks": passed_checks,
        "total_rows_checked": total_rows_checked,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <tsv_path> <prd_path>")
        sys.exit(1)

    result = validate(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
