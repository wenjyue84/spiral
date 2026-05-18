"""
tests/test_error_classifier.py — Unit tests for lib/spiral/impl/error_classifier.py

Tests verify:
- classify_error() returns correct ErrorCategory for each error type
- ErrorCategory enum has all 8 values
- scan_results_tsv() produces well-formed JSONL output
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.spiral.impl.error_classifier import ErrorCategory, classify_error, scan_results_tsv


@pytest.mark.us_1428
class TestClassifyError:
    """Test classify_error() for all 8 categories."""

    def test_classify_timeout(self) -> None:
        """Timeout messages should classify as ErrorCategory.TIMEOUT."""
        assert classify_error("Execution timed out after 300 seconds") == ErrorCategory.TIMEOUT
        assert classify_error("ERROR: timeout waiting for claude response") == ErrorCategory.TIMEOUT
        assert classify_error("deadline exceeded for story US-999") == ErrorCategory.TIMEOUT

    def test_classify_oom(self) -> None:
        """OOM messages should classify as ErrorCategory.OOM."""
        assert classify_error("MemoryError: Out of memory") == ErrorCategory.OOM
        assert classify_error("V8 heap out of memory allocated 4GB") == ErrorCategory.OOM
        assert classify_error("heap overflow detected in worker") == ErrorCategory.OOM

    def test_classify_syntax(self) -> None:
        """Syntax errors should classify as ErrorCategory.SYNTAX."""
        result = classify_error("SyntaxError: invalid syntax at line 10")
        assert result == ErrorCategory.SYNTAX

    def test_classify_import(self) -> None:
        """Import errors should classify as ErrorCategory.IMPORT."""
        result = classify_error("ModuleNotFoundError: No module named 'nonexistent'")
        assert result == ErrorCategory.IMPORT

    def test_classify_assertion(self) -> None:
        """Test assertion failures should classify as ErrorCategory.ASSERTION."""
        result = classify_error("AssertionError: expected 5 got 3 in pytest")
        assert result == ErrorCategory.ASSERTION

    def test_classify_network(self) -> None:
        """Network errors should classify as ErrorCategory.NETWORK."""
        result = classify_error("connection refused: localhost:5299")
        assert result == ErrorCategory.NETWORK

    def test_classify_auth(self) -> None:
        """Auth errors should classify as ErrorCategory.AUTH."""
        result = classify_error("401 Unauthorized: invalid api key")
        assert result == ErrorCategory.AUTH

    def test_classify_unknown(self) -> None:
        """Unrecognized messages should classify as ErrorCategory.UNKNOWN."""
        result = classify_error("some totally unrelated message")
        assert result == ErrorCategory.UNKNOWN

    def test_empty_string(self) -> None:
        """Empty string should return UNKNOWN."""
        assert classify_error("") == ErrorCategory.UNKNOWN

    def test_timeout_wins_over_assertion(self) -> None:
        """Timeout keyword takes priority over assertion keyword."""
        result = classify_error("test failed because it timed out")
        assert result == ErrorCategory.TIMEOUT


@pytest.mark.us_1428
class TestErrorCategoryEnum:
    """Test ErrorCategory enum completeness."""

    def test_all_8_categories_present(self) -> None:
        """ErrorCategory enum must have exactly the 8 specified values."""
        expected = {"timeout", "oom", "syntax", "import", "assertion", "network", "auth", "unknown"}
        actual = {e.value for e in ErrorCategory}
        assert actual == expected

    def test_is_string_enum(self) -> None:
        """ErrorCategory members should be usable as strings."""
        assert ErrorCategory.TIMEOUT == "timeout"
        assert ErrorCategory.OOM == "oom"


@pytest.mark.us_1428
class TestScanResultsTsv:
    """Test scan_results_tsv() produces valid JSONL output."""

    def test_scan_produces_jsonl(self, tmp_path: Path) -> None:
        """scan_results_tsv() should write valid JSON lines to output file."""
        tsv = tmp_path / "results.tsv"
        tsv.write_text(
            "timestamp\tstory_id\tstory_title\tstatus\tmodel\n"
            "2026-01-01\tUS-1\tExecution timed out\treject\tsonnet\n"
            "2026-01-02\tUS-2\tModuleNotFoundError pandas\treject\thaiku\n"
            "2026-01-03\tUS-3\tpassed fine\tpass\tsonnet\n",
            encoding="utf-8",
        )
        out = tmp_path / "lib" / "error_patterns.jsonl"
        result = scan_results_tsv(str(tsv), str(out))

        assert out.exists()
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        parsed = [json.loads(line) for line in lines if line]
        keys = {entry["error_type"] for entry in parsed}
        assert "timeout" in keys
        assert "import" in keys
        # pass row should not appear
        assert all(entry["frequency"] >= 1 for entry in parsed)
        assert result  # non-empty dict returned

    def test_scan_missing_tsv(self, tmp_path: Path) -> None:
        """Missing results.tsv should return empty dict without error."""
        out = tmp_path / "patterns.jsonl"
        result = scan_results_tsv(str(tmp_path / "nonexistent.tsv"), str(out))
        assert result == {}
        assert not out.exists()

    def test_entry_has_required_fields(self, tmp_path: Path) -> None:
        """Each JSONL entry must have error_type, frequency, examples, suggestion."""
        tsv = tmp_path / "results.tsv"
        tsv.write_text(
            "timestamp\tstory_id\tstory_title\tstatus\tmodel\n2026-01-01\tUS-1\tout of memory error\treject\topus\n",
            encoding="utf-8",
        )
        out = tmp_path / "patterns.jsonl"
        scan_results_tsv(str(tsv), str(out))
        entry = json.loads(out.read_text(encoding="utf-8").strip())
        assert "error_type" in entry
        assert "frequency" in entry
        assert "examples" in entry
        assert "suggestion" in entry
        assert isinstance(entry["examples"], list)
