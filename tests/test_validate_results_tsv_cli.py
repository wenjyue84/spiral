#!/usr/bin/env python3
"""Integration tests for validate-results-tsv CLI command (US-571)."""

import json
import subprocess
import sys
from pathlib import Path


def test_cli_clean_data_exits_zero(tmp_path: Path) -> None:
    """Test that CLI exits 0 on clean data and outputs valid JSON."""
    # Create a clean TSV with valid data
    tsv_file = tmp_path / "results.tsv"
    tsv_file.write_text(
        "story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n"
        "US-001\t1\t1\t5000\t30000\thaiku\n"
        "US-002\t1\t1\t8000\t45000\tsonnet\n"
    )

    # Create a minimal PRD with matching story IDs
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(
        json.dumps(
            {
                "userStories": [
                    {"id": "US-001"},
                    {"id": "US-002"},
                ]
            }
        )
    )

    # Invoke CLI
    result = subprocess.run(
        [sys.executable, "main.py", "validate-results-tsv", "--tsv", str(tsv_file), "--prd", str(prd_file)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    # Verify exit code is 0
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\nstderr: {result.stderr}"

    # Parse JSON from stdout
    report = json.loads(result.stdout)

    # Verify report structure
    assert "errors" in report
    assert "warnings" in report
    assert "passed_checks" in report
    assert "total_rows_checked" in report
    assert isinstance(report["errors"], list)
    assert isinstance(report["warnings"], list)
    assert isinstance(report["passed_checks"], int)
    assert isinstance(report["total_rows_checked"], int)

    # Clean data should have no errors
    assert len(report["errors"]) == 0


def test_cli_detects_duplicate_and_anomaly(tmp_path: Path) -> None:
    """Test that CLI detects duplicates and token anomalies, exits 1, and reports errors."""
    # Create a corrupted TSV with:
    # - Duplicate (story_id, iteration, attempt) tuple
    # - token_count outside range [50, 500000]
    # - Invalid model name
    tsv_file = tmp_path / "results.tsv"
    tsv_file.write_text(
        "story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\n"
        "US-001\t1\t1\t5000\t30000\thaiku\n"
        "US-001\t1\t1\t6000\t35000\tsonnet\n"  # Duplicate (story_id, iteration, attempt)
        "US-002\t1\t1\t10\t40000\topus\n"  # token_count too low (10 < 50)
        "US-003\t1\t1\t600000\t50000\tgpt4\n",  # token_count too high, invalid model
    )

    # Create PRD with matching story IDs
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(
        json.dumps(
            {
                "userStories": [
                    {"id": "US-001"},
                    {"id": "US-002"},
                    {"id": "US-003"},
                ]
            }
        )
    )

    # Invoke CLI
    result = subprocess.run(
        [sys.executable, "main.py", "validate-results-tsv", "--tsv", str(tsv_file), "--prd", str(prd_file)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    # Verify exit code is 1
    assert result.returncode == 1, f"Expected exit code 1, got {result.returncode}\nstderr: {result.stderr}"

    # Parse JSON from stdout
    report = json.loads(result.stdout)

    # Verify report structure
    assert "errors" in report
    assert isinstance(report["errors"], list)

    # Errors list should be non-empty
    assert len(report["errors"]) > 0, "Expected non-empty errors list for corrupted TSV"

    # Verify error messages contain expected issues
    error_text = " ".join(report["errors"])
    assert "Duplicate" in error_text or "duplicate" in error_text, "Expected duplicate detection"


def test_cli_output_file_written(tmp_path: Path) -> None:
    """Test that CLI writes report.json when --output is specified."""
    # Create a clean TSV
    tsv_file = tmp_path / "results.tsv"
    tsv_file.write_text(
        "story_id\titeration\tattempt\ttoken_count\tphase_duration_ms\tmodel\nUS-001\t1\t1\t5000\t30000\thaiku\n",
    )

    # Create PRD
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps({"userStories": [{"id": "US-001"}]}))

    # Output file
    report_file = tmp_path / "report.json"

    # Invoke CLI with --output
    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "validate-results-tsv",
            "--tsv",
            str(tsv_file),
            "--prd",
            str(prd_file),
            "--output",
            str(report_file),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    # Verify exit code is 0
    assert result.returncode == 0

    # Verify output file was created and contains valid JSON
    assert report_file.exists(), f"Expected {report_file} to be created"
    file_report = json.loads(report_file.read_text())
    assert "errors" in file_report
    assert "warnings" in file_report
    assert "passed_checks" in file_report
    assert "total_rows_checked" in file_report


def test_cli_missing_tsv_file_exits_1(tmp_path: Path) -> None:
    """Test that CLI exits 1 when results.tsv is missing."""
    # Create PRD
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps({"userStories": []}))

    # Invoke CLI with non-existent TSV
    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "validate-results-tsv",
            "--tsv",
            str(tmp_path / "nonexistent.tsv"),
            "--prd",
            str(prd_file),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    # Verify exit code is 1
    assert result.returncode == 1

    # Parse JSON and verify error
    report = json.loads(result.stdout)
    assert len(report["errors"]) > 0
    assert "not found" in report["errors"][0].lower()
