#!/usr/bin/env python3
"""
Test validate_results_tsv module.

Verifies that the validator detects all 5 error types:
  1. Missing story_ids from prd.json
  2. Duplicate (story_id, iteration, attempt) tuples
  3. token_count outside [50, 500000]
  4. phase_duration_ms outside [100, 600000]
  5. model not in {haiku, sonnet, opus}
"""

import json
import os
import tempfile

import pytest

from lib.spiral.validate_results_tsv import validate


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_validate_detects_all_anomalies(temp_dir: str):
    """Test that validator detects all 5 error types in a corrupted TSV."""
    # Create prd.json with known story IDs
    prd_data = {
        "userStories": [
            {"id": "US-001"},
            {"id": "US-002"},
            {"id": "US-003"},
        ]
    }
    prd_path = os.path.join(temp_dir, "prd.json")
    with open(prd_path, "w") as f:
        json.dump(prd_data, f)

    # Create results.tsv with violations of all 5 checks
    tsv_header = "story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel"
    tsv_rows = [
        # Error 1: US-002 is missing from TSV (but in prd.json)
        # Error 2: Duplicate (US-001, 1, 1)
        "US-001\t1\t1\t100\t5000\tsonnet",  # First occurrence (valid)
        "US-001\t1\t1\t150\t5000\thaiku",  # Duplicate tuple
        # Error 3: token_count outside [50, 500000]
        "US-001\t2\t1\t10\t5000\tsonnet",  # token_count=10 too low
        "US-001\t3\t1\t600000\t5000\topus",  # token_count=600000 too high
        # Error 4: phase_duration_ms outside [100, 600000]
        "US-001\t4\t1\t100\t50\thaiku",  # phase_duration_ms=50 too low
        "US-001\t5\t1\t100\t700000\tsonnet",  # phase_duration_ms=700000 too high
        # Error 5: model not in {haiku, sonnet, opus}
        "US-001\t6\t1\t100\t5000\tunknown_model",  # invalid model
        # Valid row for US-003
        "US-003\t1\t1\t200\t5000\topus",
    ]

    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write(tsv_header + "\n")
        f.write("\n".join(tsv_rows) + "\n")

    # Run validator
    result = validate(tsv_path, prd_path)

    # Verify all error types are detected
    assert isinstance(result["errors"], list)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["passed_checks"], int)
    assert isinstance(result["total_rows_checked"], int)

    errors_text = "\n".join(result["errors"])

    # Check 1: Missing story_id US-002
    assert "US-002" in errors_text, f"Expected US-002 missing error. Got: {errors_text}"

    # Check 2: Duplicate (US-001, 1, 1)
    assert "Duplicate" in errors_text, f"Expected duplicate detection. Got: {errors_text}"

    # Check 3: token_count violations
    assert ("10" in errors_text or "outside" in errors_text), f"Expected token_count error. Got: {errors_text}"
    assert ("600000" in errors_text or "outside" in errors_text), f"Expected token_count error. Got: {errors_text}"

    # Check 4: phase_duration_ms violations
    assert ("50" in errors_text or "outside" in errors_text), (
        f"Expected phase_duration_ms error. Got: {errors_text}"
    )
    assert ("700000" in errors_text or "outside" in errors_text), (
        f"Expected phase_duration_ms error. Got: {errors_text}"
    )

    # Check 5: model not in {haiku, sonnet, opus}
    assert ("unknown_model" in errors_text or "not in" in errors_text), f"Expected model error. Got: {errors_text}"

    # Verify counts
    assert result["total_rows_checked"] == 8
    assert result["passed_checks"] > 0


def test_validate_empty_tsv(temp_dir: str):
    """Test validator handles empty TSV gracefully."""
    prd_data = {"userStories": [{"id": "US-001"}]}
    prd_path = os.path.join(temp_dir, "prd.json")
    with open(prd_path, "w") as f:
        json.dump(prd_data, f)

    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write("story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n")

    result = validate(tsv_path, prd_path)

    assert "US-001" in "\n".join(result["errors"]), "Missing story should be detected in empty TSV"
    assert result["total_rows_checked"] == 0


def test_validate_missing_files(temp_dir: str):
    """Test validator handles missing files gracefully."""
    prd_path = os.path.join(temp_dir, "nonexistent_prd.json")
    tsv_path = os.path.join(temp_dir, "nonexistent_results.tsv")

    result = validate(tsv_path, prd_path)

    assert len(result["errors"]) > 0
    assert "not found" in "\n".join(result["errors"]).lower()


def test_validate_malformed_prd(temp_dir: str):
    """Test validator handles malformed prd.json gracefully."""
    prd_path = os.path.join(temp_dir, "bad_prd.json")
    with open(prd_path, "w") as f:
        f.write("{invalid json")

    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write("story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n")

    result = validate(tsv_path, prd_path)

    assert len(result["warnings"]) > 0
    assert "Could not load prd.json" in "\n".join(result["warnings"])


def test_validate_valid_tsv(temp_dir: str):
    """Test validator passes for a valid TSV."""
    prd_data = {
        "userStories": [
            {"id": "US-001"},
            {"id": "US-002"},
        ]
    }
    prd_path = os.path.join(temp_dir, "prd.json")
    with open(prd_path, "w") as f:
        json.dump(prd_data, f)

    tsv_header = "story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel"
    tsv_rows = [
        "US-001\t1\t1\t100\t5000\tsonnet",
        "US-002\t1\t1\t200\t5000\topus",
    ]

    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write(tsv_header + "\n")
        f.write("\n".join(tsv_rows) + "\n")

    result = validate(tsv_path, prd_path)

    # Should have no errors for valid data
    assert result["total_rows_checked"] == 2
    assert result["passed_checks"] > 0
