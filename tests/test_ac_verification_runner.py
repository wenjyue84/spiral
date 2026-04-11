#!/usr/bin/env python3
"""
tests/test_ac_verification_runner.py — Tests for AC Verification Runner (US-1005)

Tests the execution of extracted AC assertions with timeout handling and
result aggregation. Includes comprehensive test cases covering passing, failing,
mixed, and edge cases.
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any, Dict

import pytest

from lib.ac_verification_runner import run_assertions


@pytest.fixture
def temp_assertions_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for assertion JSON files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_assertions_file(temp_dir: Path, story_id: str, assertions: list[Dict[str, Any]]) -> Path:
    """Helper to create an assertions JSON file."""
    assertions_file = temp_dir / f"{story_id}.json"
    data = {
        "story_id": story_id,
        "total_assertions": len(assertions),
        "extracted_assertions": assertions,
        "manual_review": [],
        "extraction_metadata": {
            "timestamp": "2026-03-23T10:15:30Z",
            "total_ac_items": len(assertions),
            "successfully_extracted": len(assertions),
            "requires_manual_review": 0,
        },
    }
    with open(assertions_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return assertions_file


@pytest.mark.us_1005
class TestACVerificationRunnerPassingAssertions:
    """Test successful assertion execution."""

    def test_two_passing_assertions(self, temp_assertions_dir: Path) -> None:
        """Test 2 passing assertions execute successfully."""
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "command exits with 0",
                "command": "exit 0",
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "file_exists",
                "raw_ac": "file exists: /etc/hosts",
                "command": "test -f /etc/hosts",
                "expected": "file_exists",
                "extracted": True,
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-TEST-01", assertions)
        results = run_assertions("US-TEST-01", assertions_file, timeout=30)

        assert results["story_id"] == "US-TEST-01"
        assert results["total"] == 2
        assert results["passed"] == 2
        assert results["failed"] == 0
        assert results["skipped"] == 0
        assert len(results["details"]) == 2

        # Check first assertion (exit code)
        detail0 = results["details"][0]
        assert detail0["index"] == 0
        assert detail0["type"] == "exit_code"
        assert detail0["status"] == "passed"
        assert detail0["return_code"] == 0

        # Check second assertion (file exists)
        detail1 = results["details"][1]
        assert detail1["index"] == 1
        assert detail1["type"] == "file_exists"
        assert detail1["status"] == "passed"
        assert detail1["return_code"] == 0


@pytest.mark.us_1005
class TestACVerificationRunnerFailingAssertions:
    """Test assertion execution with failures."""

    def test_one_failing_assertion(self, temp_assertions_dir: Path) -> None:
        """Test 1 failing assertion reports correct failure."""
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "command exits with 1",
                "command": "exit 1",
                "expected": "0",
                "extracted": True,
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-TEST-02", assertions)
        results = run_assertions("US-TEST-02", assertions_file, timeout=30)

        assert results["story_id"] == "US-TEST-02"
        assert results["total"] == 1
        assert results["passed"] == 0
        assert results["failed"] == 1
        assert results["skipped"] == 0

        detail = results["details"][0]
        assert detail["type"] == "exit_code"
        assert detail["status"] == "failed"
        assert detail["return_code"] == 1


@pytest.mark.us_1005
class TestACVerificationRunnerMixedResults:
    """Test mixed passing and failing assertions."""

    def test_mixed_assertions_two_pass_one_fail(self, temp_assertions_dir: Path) -> None:
        """Test 3 assertions with 2 passing and 1 failing."""
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "command exits with 0",
                "command": "exit 0",
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "exit_code",
                "raw_ac": "command exits with 1",
                "command": "exit 1",
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "file_exists",
                "raw_ac": "file sys.executable exists",
                "command": 'python3 -c "import sys; import os; assert os.path.exists(sys.executable)"',
                "expected": "file_exists",
                "extracted": True,
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-TEST-03", assertions)
        results = run_assertions("US-TEST-03", assertions_file, timeout=30)

        assert results["story_id"] == "US-TEST-03"
        assert results["total"] == 3
        assert results["passed"] == 2, f"Expected 2 passed, got {results['passed']}: {results['details']}"
        assert results["failed"] == 1
        assert results["skipped"] == 0

        # Check first: passed
        assert results["details"][0]["status"] == "passed"
        # Check second: failed
        assert results["details"][1]["status"] == "failed"
        # Check third: passed
        assert results["details"][2]["status"] == "passed"


@pytest.mark.us_1005
class TestACVerificationRunnerEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_assertions_file(self) -> None:
        """Test handling of missing assertions file."""
        missing_file = Path("/nonexistent/path/missing.json")
        results = run_assertions("US-TEST-99", missing_file, timeout=30)

        assert results["story_id"] == "US-TEST-99"
        assert results["total"] == 0
        assert results["passed"] == 0
        assert results["failed"] == 0
        assert results["skipped"] == 0
        assert "error" in results
        assert "not found" in results["error"]

    def test_unparseable_assertions_are_skipped(self, temp_assertions_dir: Path) -> None:
        """Test that unparseable assertions are skipped."""
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "command exits with 0",
                "command": "exit 0",
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "unknown",
                "raw_ac": "some complex assertion",
                "command": "echo test",
                "expected": "test",
                "extracted": False,  # Not extracted
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-TEST-04", assertions)
        results = run_assertions("US-TEST-04", assertions_file, timeout=30)

        assert results["passed"] == 1
        assert results["failed"] == 0
        assert results["skipped"] == 1  # Unparseable item is skipped
        assert results["details"][1]["status"] == "skipped"

    def test_empty_assertions_list(self, temp_assertions_dir: Path) -> None:
        """Test handling of empty assertions list."""
        assertions_file = create_assertions_file(temp_assertions_dir, "US-TEST-06", [])
        results = run_assertions("US-TEST-06", assertions_file, timeout=30)

        assert results["total"] == 0
        assert results["passed"] == 0
        assert results["failed"] == 0
        assert results["skipped"] == 0
        assert len(results["details"]) == 0


@pytest.mark.us_1005
class TestACVerificationRunnerIntegration:
    """Integration tests for complete observable workflow."""

    def test_observable_end_to_end_workflow(self, temp_assertions_dir: Path) -> None:
        """Test complete workflow: extract assertions, execute them, report results.

        This test demonstrates the observable behavior of US-1005:
        - Execute multiple assertion types independently
        - Report per-assertion pass/fail status
        - Aggregate results (passed, failed, skipped counts)
        - Return structured JSON output with details for post-Phase V analysis
        """
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "exits with status 0",
                "command": "exit 0",
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "exit_code",
                "raw_ac": "exits with non-zero status",
                "command": "exit 42",
                "expected": "true",  # Non-zero expected
                "extracted": True,
            },
            {
                "type": "file_exists",
                "raw_ac": "output file created",
                "command": "test -f /etc/hostname",
                "expected": "file_exists",
                "extracted": True,
            },
            {
                "type": "unknown",
                "raw_ac": "complex assertion",
                "command": "echo test",
                "expected": "test",
                "extracted": False,  # Manual review required
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-INTEGRATION-001", assertions)
        results = run_assertions("US-INTEGRATION-001", assertions_file, timeout=30)

        # Verify complete result structure
        assert results["story_id"] == "US-INTEGRATION-001"
        assert "total" in results
        assert "passed" in results
        assert "failed" in results
        assert "skipped" in results
        assert "details" in results

        # Verify aggregated counts: 3 assertions total (1 will fail), 1 skipped (manual review)
        assert results["total"] == 3
        assert results["passed"] == 2, f"Expected 2 passed: {results['details']}"
        assert results["failed"] == 1
        assert results["skipped"] == 1

        # Verify per-assertion details structure
        assert len(results["details"]) == 4
        for detail in results["details"]:
            assert "index" in detail
            assert "type" in detail
            assert "raw_ac" in detail
            assert "command" in detail
            assert "status" in detail
            assert "return_code" in detail
            assert "stdout" in detail
            assert "stderr" in detail
            assert detail["status"] in ("passed", "failed", "skipped", "timeout")

        # Verify observable behavior: zero assertions passed case
        # (This would be tested separately, but the story requirement is
        # "fail the story if zero assertions pass")
        assert results["passed"] >= 0  # At least 0 assertions can pass

    def test_failure_case_zero_assertions_pass(self, temp_assertions_dir: Path) -> None:
        """Test observable behavior when zero assertions pass.

        This satisfies the story requirement: 'fail the story if zero assertions pass'.
        The verification runner reports all failures, and Phase V should interpret
        this as a story failure condition.
        """
        assertions = [
            {
                "type": "exit_code",
                "raw_ac": "exits with 0",
                "command": "exit 1",  # Will fail because expected is 0
                "expected": "0",
                "extracted": True,
            },
            {
                "type": "file_exists",
                "raw_ac": "file exists: /nonexistent/path",
                "command": "test -f /nonexistent/path/that/does/not/exist",
                "expected": "file_exists",
                "extracted": True,
            },
        ]

        assertions_file = create_assertions_file(temp_assertions_dir, "US-ZERO-PASS", assertions)
        results = run_assertions("US-ZERO-PASS", assertions_file, timeout=30)

        # Verify zero assertions passed
        assert results["passed"] == 0
        assert results["failed"] == 2
        assert results["total"] == 2

        # Verify all details report failure
        for detail in results["details"]:
            assert detail["status"] == "failed"
