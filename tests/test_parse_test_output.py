"""Tests for lib/quality/parse_test_output.py"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "quality"))

from parse_test_output import (
    create_report,
    parse_bats_output,
    parse_pytest_output,
    parse_vitest_output,
)


class TestParseTestOutput:
    """Test parsing of different test framework outputs."""

    def test_parse_pytest_passed_and_failed(self) -> None:
        """Test pytest output parsing with passed and failed tests."""
        pytest_output = """
tests/test_example.py::test_one PASSED
tests/test_example.py::test_two FAILED
===== 1 passed, 1 failed in 0.42s =====
        """
        result = parse_pytest_output(pytest_output)
        assert result["passed"] == 1
        assert result["failed"] == 1
        assert result["total"] == 2

    def test_parse_pytest_all_passed(self) -> None:
        """Test pytest output when all tests pass."""
        pytest_output = """
tests/test_example.py::test_one PASSED
tests/test_example.py::test_two PASSED
===== 2 passed in 0.42s =====
        """
        result = parse_pytest_output(pytest_output)
        assert result["passed"] == 2
        assert result["failed"] == 0
        assert result["errored"] == 0

    def test_parse_pytest_with_errors(self) -> None:
        """Test pytest output parsing with errors."""
        pytest_output = """
tests/test_example.py::test_one PASSED
tests/test_example.py::test_two ERROR
tests/test_example.py::test_three FAILED
===== 1 passed, 1 failed, 1 error in 0.42s =====
        """
        result = parse_pytest_output(pytest_output)
        assert result["passed"] == 1
        assert result["failed"] == 1
        assert result["errored"] == 1

    def test_parse_bats_output(self) -> None:
        """Test bats (bash automated test suite) output parsing."""
        bats_output = """
1..5
ok 1 - test one
ok 2 - test two
not ok 3 - test three
ok 4 - test four
not ok 5 - test five
        """
        result = parse_bats_output(bats_output)
        assert result["passed"] == 3
        assert result["failed"] == 2
        assert result["total"] == 5

    def test_parse_vitest_output(self) -> None:
        """Test vitest output parsing."""
        vitest_output = """
PASS  [0.542s] 2 test files, 5 passed, 1 failed
        """
        result = parse_vitest_output(vitest_output)
        assert result["passed"] == 5
        assert result["failed"] == 1

    def test_create_report_writes_json(self) -> None:
        """Test that create_report writes a valid JSON report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_counts = {
                "passed": 10,
                "failed": 2,
                "errored": 0,
                "skipped": 1,
                "total": 12,
            }
            report = create_report(test_counts, 1, tmpdir)

            # Verify report structure
            assert "timestamp" in report
            assert "exit_code" in report
            assert "summary" in report
            assert report["exit_code"] == 1
            assert report["summary"]["passed"] == 10
            assert report["summary"]["failed"] == 2

            # Verify file was written
            report_dir = Path(tmpdir)
            report_files = list(report_dir.glob("*/report.json"))
            assert len(report_files) == 1

            # Verify JSON is valid
            with open(report_files[0], encoding="utf-8") as f:
                loaded = json.load(f)
                assert loaded["summary"]["passed"] == 10

    def test_parse_pytest_empty_output(self) -> None:
        """Test parsing empty pytest output."""
        result = parse_pytest_output("")
        assert result["passed"] == 0
        assert result["failed"] == 0
        assert result["total"] == 0

    def test_parse_pytest_no_summary(self) -> None:
        """Test parsing pytest output without explicit summary."""
        pytest_output = """
tests/test_example.py::test_one PASSED
        """
        result = parse_pytest_output(pytest_output)
        # Without a summary line, counts should be 0
        assert result["total"] == 0
