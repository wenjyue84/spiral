#!/usr/bin/env python3
"""Validate results.tsv for data integrity.

Backward-compatible superset of two historical APIs:

* ``validate(tsv_path)`` (US-769): duplicate story_id rows + token ranges.
* ``validate(tsv_path, prd_path)`` (US-571): additionally checks prd.json story
  coverage, (story_id, iteration, attempt) duplicates, token_count,
  phase_duration_ms and model values.

Returns a dict with: errors, warnings, passed_checks, total_rows_checked and
check_counts ({"rows", "checks_run"}).  Error messages never echo field values
(only column names / story ids) so secrets and extreme numbers do not leak.
"""

import csv
import json
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
    passed_checks: int
    total_rows_checked: int
    check_counts: CheckCounts


VALID_MODELS = {"haiku", "sonnet", "opus"}
# Generic bounds for any column with "token" in its name.
TOKEN_MIN = 0
TOKEN_MAX = 1000000
# Stricter legacy bounds for the canonical columns.
STRICT_RANGES: dict[str, tuple[int, int]] = {
    "token_count": (50, 500000),
    "phase_duration_ms": (100, 600000),
}


def _result(errors: list[str], warnings: list[str], passed: int, rows: int, checks_run: int) -> ValidationResult:
    return {
        "errors": errors,
        "warnings": warnings,
        "passed_checks": passed,
        "total_rows_checked": rows,
        "check_counts": {"rows": rows, "checks_run": checks_run},
    }


def validate(tsv_path: str, prd_path: str | None = None) -> ValidationResult:
    """Validate results.tsv (and, optionally, story coverage against prd.json)."""
    errors: list[str] = []
    warnings: list[str] = []
    passed = 0
    failed = 0

    # Optional prd.json
    prd_story_ids: set[str] = set()
    if prd_path is not None:
        if os.path.isfile(prd_path):
            try:
                with open(prd_path, encoding="utf-8") as f:
                    prd_data = json.load(f)
                for story in prd_data.get("userStories", []):
                    prd_story_ids.add(story.get("id", ""))
            except (ValueError, OSError, AttributeError) as e:
                warnings.append(f"Could not load prd.json: {type(e).__name__}")
        else:
            warnings.append("prd.json not found")

    if not os.path.isfile(tsv_path):
        errors.append("results.tsv not found")
        return _result(errors, warnings, 0, 0, 1)

    rows: list[dict[str, Any]] = []
    fieldnames: list[str] = []
    try:
        with open(tsv_path, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if not reader.fieldnames:
                errors.append("results.tsv is empty or malformed")
                return _result(errors, warnings, 0, 0, 1)
            fieldnames = list(reader.fieldnames)
            rows = list(reader)
    except (OSError, csv.Error, ValueError):
        errors.append("results.tsv could not be read")
        return _result(errors, warnings, 0, 0, 1)

    def val(row: dict[str, Any], col: str) -> str:
        v = row.get(col)
        return v.strip() if isinstance(v, str) else ""

    # Check: prd story ids present in results.tsv
    present = {val(r, "story_id") for r in rows}
    for sid in sorted(s for s in prd_story_ids if s):
        if sid in present:
            passed += 1
        else:
            failed += 1
            errors.append(f"story_id '{sid}' from prd.json missing from results.tsv")

    # Duplicate key: story_id plus iteration/attempt when those columns exist.
    key_cols = ["story_id"] + [c for c in ("iteration", "attempt") if c in fieldnames]
    token_cols = [c for c in fieldnames if "token" in c.lower()]
    seen: set[tuple[str, ...]] = set()
    total = 0

    for row in rows:
        total += 1
        sid = val(row, "story_id")
        if sid:
            key = tuple(val(row, c) for c in key_cols)
            if key in seen:
                failed += 1
                detail = ", ".join(f"{c}='{val(row, c)}'" for c in key_cols)
                errors.append(f"Duplicate row: {detail}")
            else:
                seen.add(key)
                passed += 1

        # Range checks: strict legacy columns first, generic token columns otherwise.
        range_cols = [c for c in fieldnames if c in STRICT_RANGES or c in token_cols]
        for col in range_cols:
            raw = val(row, col)
            if not raw:
                if col in STRICT_RANGES:
                    warnings.append(f"Row {total}: {col} field is empty")
                continue
            lo, hi = STRICT_RANGES.get(col, (TOKEN_MIN, TOKEN_MAX))
            try:
                num = int(raw)
            except ValueError:
                if col in STRICT_RANGES:
                    failed += 1
                    errors.append(f"Row {total}: {col} is not a valid integer")
                else:
                    warnings.append(f"Row {total}: {col} not an integer")
                continue
            if lo <= num <= hi:
                passed += 1
            else:
                failed += 1
                errors.append(f"Row {total}: {col} outside range [{lo}, {hi}]")

        if "model" in fieldnames:
            model = val(row, "model")
            if not model:
                warnings.append(f"Row {total}: model field is empty")
            elif model in VALID_MODELS:
                passed += 1
            else:
                failed += 1
                errors.append(f"Row {total}: model not in {sorted(VALID_MODELS)}")

    return _result(errors, warnings, passed, total, passed + failed)


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 3):
        print(f"Usage: {sys.argv[0]} <tsv_path> [prd_path]")
        sys.exit(1)

    print(json.dumps(validate(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None), indent=2))
