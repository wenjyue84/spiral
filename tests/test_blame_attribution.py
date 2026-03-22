"""
Tests for lib/test_blame.py — Phase V test blame attribution.

Tests the core attribution logic that matches failing tests to changed source files.
"""

import json
import tempfile
from pathlib import Path

import pytest

# Import the blame attribution functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from test_blame import (
    attribute_test_to_file,
    blame_tests,
    extract_source_file,
    extract_test_file,
    find_newly_failed_tests,
    parse_test_results,
)


class TestExtractTestFile:
    """Tests for extract_test_file()."""

    def test_simple_pytest_nodeid(self) -> None:
        """Extract test file name from pytest node ID, stripping test_ prefix."""
        assert extract_test_file("tests/test_foo.py::test_bar") == "foo"

    def test_nested_test_class(self) -> None:
        """Extract from nested test class, stripping test_ prefix."""
        assert extract_test_file("tests/test_merge.py::TestClass::test_method") == "merge"

    def test_test_file_only(self) -> None:
        """Handle test file path without node ID, stripping test_ prefix."""
        assert extract_test_file("tests/test_blame.py") == "blame"

    def test_test_file_with_path(self) -> None:
        """Handle test file with directory path, stripping test_ prefix."""
        assert extract_test_file("tests/unit/test_parser.py::test_parse") == "parser"


class TestExtractSourceFile:
    """Tests for extract_source_file()."""

    def test_simple_source_file(self) -> None:
        """Extract source file name."""
        assert extract_source_file("lib/foo.py") == "foo"

    def test_nested_source_file(self) -> None:
        """Extract from nested source file."""
        assert extract_source_file("lib/subdir/bar.py") == "bar"

    def test_source_without_extension(self) -> None:
        """Handle source file without .py extension."""
        assert extract_source_file("lib/baz") == "baz"


class TestParseTestResults:
    """Tests for parse_test_results()."""

    def test_pytest_report_format(self) -> None:
        """Parse pytest report.json format."""
        report = {
            "tests": [
                {"nodeid": "tests/test_foo.py::test_bar", "outcome": "passed"},
                {"nodeid": "tests/test_foo.py::test_baz", "outcome": "failed"},
                {"nodeid": "tests/test_other.py::test_x", "outcome": "skipped"},
            ]
        }
        result = parse_test_results(report)
        assert result["tests/test_foo.py::test_bar"] == "passed"
        assert result["tests/test_foo.py::test_baz"] == "failed"
        assert result["tests/test_other.py::test_x"] == "skipped"

    def test_flat_dict_format(self) -> None:
        """Parse flat dictionary format."""
        results = {
            "tests/test_foo.py::test_bar": "passed",
            "tests/test_foo.py::test_baz": "failed",
        }
        result = parse_test_results(results)
        assert result["tests/test_foo.py::test_bar"] == "passed"
        assert result["tests/test_foo.py::test_baz"] == "failed"

    def test_empty_results(self) -> None:
        """Handle empty test results."""
        result = parse_test_results({"tests": []})
        assert result == {}


class TestFindNewlyFailedTests:
    """Tests for find_newly_failed_tests()."""

    def test_newly_failed(self) -> None:
        """Identify tests that passed before but failed now."""
        baseline = {"test_a": "passed", "test_b": "passed"}
        current = {"test_a": "passed", "test_b": "failed"}
        result = find_newly_failed_tests(baseline, current)
        assert result == ["test_b"]

    def test_missing_in_baseline(self) -> None:
        """Treat missing baseline tests as newly failed if they fail now."""
        baseline = {"test_a": "passed"}
        current = {"test_a": "passed", "test_b": "failed"}
        result = find_newly_failed_tests(baseline, current)
        assert result == ["test_b"]

    def test_no_new_failures(self) -> None:
        """Return empty list when no tests newly failed."""
        baseline = {"test_a": "passed", "test_b": "failed"}
        current = {"test_a": "passed", "test_b": "failed"}
        result = find_newly_failed_tests(baseline, current)
        assert result == []

    def test_fixed_test_ignored(self) -> None:
        """Ignore tests that were failing and are now passing."""
        baseline = {"test_a": "failed"}
        current = {"test_a": "passed"}
        result = find_newly_failed_tests(baseline, current)
        assert result == []


class TestAttributeTestToFile:
    """Tests for attribute_test_to_file()."""

    def test_exact_match(self) -> None:
        """Match test to source file by naming convention."""
        changed_files = ["lib/foo.py", "lib/bar.py"]
        matched, confidence = attribute_test_to_file("tests/test_foo.py::test_bar", changed_files)
        assert matched == "lib/foo.py"
        assert confidence == "high"

    def test_no_match(self) -> None:
        """Return None when no match found with multiple files."""
        changed_files = ["lib/baz.py", "lib/qux.py"]  # Multiple files - no fallback
        matched, confidence = attribute_test_to_file("tests/test_foo.py::test_bar", changed_files)
        assert matched is None
        assert confidence == "low"

    def test_single_changed_file(self) -> None:
        """Use single changed file as fallback match."""
        changed_files = ["lib/foo.py"]
        matched, confidence = attribute_test_to_file("tests/test_unknown.py::test_bar", changed_files)
        assert matched == "lib/foo.py"
        assert confidence == "medium"

    def test_multiple_changed_files_no_match(self) -> None:
        """Don't match when multiple files changed and no exact match."""
        changed_files = ["lib/foo.py", "lib/bar.py"]
        matched, confidence = attribute_test_to_file("tests/test_unknown.py::test_x", changed_files)
        assert matched is None
        assert confidence == "low"


class TestBlameTests:
    """Tests for the main blame_tests() function."""

    def test_full_attribution_workflow(self) -> None:
        """Test complete blame attribution with realistic data."""
        baseline = {
            "tests": {
                "tests/test_foo.py::test_works": "passed",
                "tests/test_foo.py::test_also_works": "passed",
            }
        }
        new_results = {
            "tests": {
                "tests/test_foo.py::test_works": "passed",
                "tests/test_foo.py::test_also_works": "failed",
                "tests/test_foo.py::test_new": "failed",
            }
        }
        changed_files = ["lib/foo.py", "lib/helper.py"]

        result = blame_tests(baseline, new_results, changed_files, "US-782")

        assert result["story_id"] == "US-782"
        assert "tests/test_foo.py::test_also_works" in result["newly_failed_tests"]
        assert "tests/test_foo.py::test_new" in result["newly_failed_tests"]
        assert len(result["attribution"]) == 2

        # Check attribution details
        attr_map = {a["test"]: a for a in result["attribution"]}
        assert attr_map["tests/test_foo.py::test_also_works"]["likely_source"] == "lib/foo.py"
        assert attr_map["tests/test_foo.py::test_also_works"]["confidence"] == "high"

    def test_no_failures_returns_empty_attribution(self) -> None:
        """Return empty attribution when no tests fail."""
        baseline = {"tests": {"test_a": "passed"}}
        new_results = {"tests": {"test_a": "passed"}}
        changed_files = ["lib/foo.py"]

        result = blame_tests(baseline, new_results, changed_files, "US-123")

        assert result["newly_failed_tests"] == []
        assert result["attribution"] == []


class TestIntegration:
    """Integration tests with file I/O."""

    def test_end_to_end_blame_with_files(self) -> None:
        """Test complete workflow with temporary files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create baseline file
            baseline_data = {
                "baseline_timestamp": "2026-03-23T00:00:00Z",
                "tests": {
                    "tests/test_merge.py::test_dedup": "passed",
                    "tests/test_merge.py::test_priority": "passed",
                }
            }
            baseline_file = tmppath / "baseline.json"
            baseline_file.write_text(json.dumps(baseline_data))

            # Create new results file
            new_data = {
                "tests": {
                    "tests/test_merge.py::test_dedup": "passed",
                    "tests/test_merge.py::test_priority": "failed",  # newly failed
                }
            }
            new_file = tmppath / "new_results.json"
            new_file.write_text(json.dumps(new_data))

            # Create changed files list
            changed_files_file = tmppath / "changed_files.txt"
            changed_files_file.write_text("lib/merge.py\nlib/prio.py\n")

            # Run attribution
            result = blame_tests(
                baseline_data,
                new_data,
                ["lib/merge.py", "lib/prio.py"],
                "US-123"
            )

            assert result["story_id"] == "US-123"
            assert "tests/test_merge.py::test_priority" in result["newly_failed_tests"]
            # Should match test_priority to lib/prio.py or at least one of the files
            assert len(result["attribution"]) == 1
