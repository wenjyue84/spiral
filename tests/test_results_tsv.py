"""Tests for results_tsv.py — ResultsRecord parsing and serialization."""

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from results_tsv import (
    HEADER,
    ResultsRecord,
    get_last_failed_files,
    parse_failed_files_from_stderr,
    parse_results_tsv,
    write_results_tsv,
)


def _make_record(story_id: str, sub_project: str = "", **overrides: Any) -> ResultsRecord:
    """Helper: create a ResultsRecord with sensible defaults."""
    record = ResultsRecord(
        timestamp="2026-03-13T10:00:00Z",
        spiral_iter="1",
        ralph_iter="1",
        story_id=story_id,
        story_title=f"Title for {story_id}",
        status="PASS",
        duration_sec="30",
        model="sonnet",
        retry_num="0",
        commit_sha="abc1234",
        run_id="test-run-id",
        sub_project=sub_project,
    )
    # Apply any overrides
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


class TestResultsRecord:
    """Tests for ResultsRecord dataclass."""

    def test_record_creation_with_sub_project(self) -> None:
        """ResultsRecord can be created with sub_project field."""
        record = _make_record("US-001", sub_project="frontend")
        assert record.sub_project == "frontend"

    def test_record_default_sub_project_empty(self) -> None:
        """ResultsRecord defaults sub_project to empty string."""
        record = _make_record("US-002")
        assert record.sub_project == ""


class TestParseBackwardCompat:
    """Tests for backward-compatible parsing of old TSV files."""

    def test_parse_old_tsv_without_sub_project(self, tmp_path: Path) -> None:
        """Old TSV without sub_project column parses without error."""
        path = str(tmp_path / "old_results.tsv")

        # Create a TSV with old schema (no sub_project)
        old_header = [h for h in HEADER if h != "sub_project"]
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=old_header, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-03-13T10:00:00Z",
                    "spiral_iter": "1",
                    "ralph_iter": "1",
                    "story_id": "US-001",
                    "story_title": "Test Story",
                    "status": "PASS",
                    "duration_sec": "30",
                    "model": "sonnet",
                    "retry_num": "0",
                    "commit_sha": "abc1234",
                    "run_id": "test-run",
                }
            )

        # Parse should succeed with missing sub_project defaulting to ""
        records = parse_results_tsv(path)
        assert len(records) == 1
        assert records[0].story_id == "US-001"
        assert records[0].sub_project == ""  # Default empty string

    def test_parse_missing_file_returns_empty(self) -> None:
        """Parsing nonexistent file returns empty list."""
        records = parse_results_tsv("/nonexistent/path.tsv")
        assert records == []


class TestRoundTrip:
    """Tests for write/read round-trip with sub_project."""

    def test_round_trip_with_sub_project(self, tmp_path: Path) -> None:
        """Write and read back preserves sub_project value."""
        path = str(tmp_path / "results.tsv")

        # Create and write a record with sub_project
        original = _make_record("US-001", sub_project="foo")
        write_results_tsv(path, [original])

        # Read back and verify
        records = parse_results_tsv(path)
        assert len(records) == 1
        assert records[0].story_id == "US-001"
        assert records[0].sub_project == "foo"

    def test_round_trip_empty_sub_project(self, tmp_path: Path) -> None:
        """Write and read back with empty sub_project."""
        path = str(tmp_path / "results.tsv")

        # Create and write a record without sub_project (empty)
        original = _make_record("US-002")
        write_results_tsv(path, [original])

        # Read back and verify sub_project is empty
        records = parse_results_tsv(path)
        assert len(records) == 1
        assert records[0].sub_project == ""

    def test_round_trip_multiple_records_different_sub_projects(self, tmp_path: Path) -> None:
        """Multiple records with different sub_project values survive round-trip."""
        path = str(tmp_path / "results.tsv")

        records = [
            _make_record("US-001", sub_project="frontend"),
            _make_record("US-002", sub_project="backend"),
            _make_record("US-003", sub_project=""),
        ]
        write_results_tsv(path, records)

        # Read back and verify all sub_project values preserved
        parsed = parse_results_tsv(path)
        assert len(parsed) == 3
        assert parsed[0].sub_project == "frontend"
        assert parsed[1].sub_project == "backend"
        assert parsed[2].sub_project == ""


class TestSecurityResultsTsv:
    """Security tests: no sensitive data in telemetry schema or written rows."""

    # Exact column names that would indicate credential storage
    _FORBIDDEN_COLS = frozenset(
        ["password", "secret", "api_key", "auth_token", "token", "credential", "private_key", "access_key"]
    )

    def test_security_no_credential_columns_in_header(self) -> None:
        """HEADER must not contain any credential-named columns."""
        for col in HEADER:
            assert col not in self._FORBIDDEN_COLS, f"Credential-named column found in HEADER: {col}"

    def test_security_credential_values_absent_from_written_tsv(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Extra credential-keyed dict entries are excluded by extrasaction='ignore'."""
        path = str(tmp_path / "results.tsv")
        row = {col: "safe" for col in HEADER}
        row["story_id"] = "US-SEC-001"
        # Inject credential-like keys outside the schema
        row["api_key"] = "sk-SHOULDNOTAPPEAR"
        row["password"] = "hunter2-NOSECRET"
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER, delimiter="\t", extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)
        content = open(path, encoding="utf-8").read()
        assert "SHOULDNOTAPPEAR" not in content
        assert "NOSECRET" not in content


class TestFileLevelFailureData:
    """Tests for file-level failure data (US-597 integration)."""

    def test_write_failed_story_with_file_level_data(self, tmp_path: Path) -> None:
        """Write a failed-story row with file-level data and verify columns present."""
        path = str(tmp_path / "results.tsv")

        # Create a record with failed_files JSON array
        failed_files_list = ["src/main.py", "lib/utils.py"]
        record = _make_record(
            "US-100",
            status="FAIL",
            failed_files=json.dumps(failed_files_list),
        )
        write_results_tsv(path, [record])

        # Verify the file exists and has the expected columns
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 2  # header + 1 data row
            header = lines[0].strip().split("\t")
            assert "failed_files" in header

        # Verify data row contains the JSON
        parsed = parse_results_tsv(path)
        assert len(parsed) == 1
        assert parsed[0].story_id == "US-100"
        assert parsed[0].status == "FAIL"
        assert parsed[0].failed_files == json.dumps(failed_files_list)

    def test_read_back_failed_files_json(self, tmp_path: Path) -> None:
        """Read back file-level failure data and verify JSON parsing."""
        path = str(tmp_path / "results.tsv")

        # Write multiple records with various failed_files states
        records = [
            _make_record("US-101", status="PASS", failed_files=""),  # empty
            _make_record("US-102", status="FAIL", failed_files=json.dumps(["a.py", "b.py"])),
            _make_record("US-103", status="FAIL", failed_files=json.dumps(["c.py"])),
        ]
        write_results_tsv(path, records)

        # Parse back and verify data integrity
        parsed = parse_results_tsv(path)
        assert len(parsed) == 3

        # Check first record (PASS, empty failed_files)
        assert parsed[0].story_id == "US-101"
        assert parsed[0].status == "PASS"
        assert parsed[0].failed_files == ""

        # Check second record (FAIL with 2 files)
        assert parsed[1].story_id == "US-102"
        assert parsed[1].status == "FAIL"
        files_data = json.loads(parsed[1].failed_files)
        assert files_data == ["a.py", "b.py"]

        # Check third record (FAIL with 1 file)
        assert parsed[2].story_id == "US-103"
        assert parsed[2].status == "FAIL"
        files_data = json.loads(parsed[2].failed_files)
        assert files_data == ["c.py"]

    def test_get_last_failed_files_happy_path(self, tmp_path: Path) -> None:
        """get_last_failed_files() returns the most recent failed_files for a story."""
        path = str(tmp_path / "results.tsv")

        # Write sequence of records for same story
        records = [
            _make_record("US-104", status="PASS", failed_files=""),
            _make_record("US-104", status="FAIL", failed_files=json.dumps(["old.py"])),
            _make_record("US-104", status="FAIL", failed_files=json.dumps(["new1.py", "new2.py"])),
            _make_record("US-105", status="FAIL", failed_files=json.dumps(["other.py"])),
        ]
        write_results_tsv(path, records)

        # Get last failed files for US-104
        result = get_last_failed_files(path, "US-104")
        assert result == ["new1.py", "new2.py"]

        # Get last failed files for US-105
        result = get_last_failed_files(path, "US-105")
        assert result == ["other.py"]

    def test_get_last_failed_files_no_matching_story(self, tmp_path: Path) -> None:
        """get_last_failed_files() returns empty list if story not found."""
        path = str(tmp_path / "results.tsv")

        records = [
            _make_record("US-110", status="FAIL", failed_files=json.dumps(["a.py"])),
        ]
        write_results_tsv(path, records)

        # Query for non-existent story
        result = get_last_failed_files(path, "US-999")
        assert result == []

    def test_get_last_failed_files_all_pass_records(self, tmp_path: Path) -> None:
        """get_last_failed_files() returns empty list if all records are PASS."""
        path = str(tmp_path / "results.tsv")

        records = [
            _make_record("US-111", status="PASS", failed_files=""),
            _make_record("US-111", status="PASS", failed_files=""),
        ]
        write_results_tsv(path, records)

        result = get_last_failed_files(path, "US-111")
        assert result == []

    def test_get_last_failed_files_invalid_json(self, tmp_path: Path) -> None:
        """get_last_failed_files() handles invalid JSON gracefully."""
        path = str(tmp_path / "results.tsv")

        records = [
            _make_record("US-112", status="FAIL", failed_files="not valid json"),
            _make_record("US-112", status="FAIL", failed_files=json.dumps(["valid.py"])),
        ]
        write_results_tsv(path, records)

        # Should return the valid one (most recent)
        result = get_last_failed_files(path, "US-112")
        assert result == ["valid.py"]

    def test_parse_failed_files_from_stderr_error_processing(self) -> None:
        """parse_failed_files_from_stderr() extracts 'Error processing file:' lines."""
        stderr = """
Some output
Error processing file: src/main.py
More output
Error processing file: lib/utils.py
"""
        result = parse_failed_files_from_stderr(stderr)
        assert "src/main.py" in result
        assert "lib/utils.py" in result

    def test_parse_failed_files_from_stderr_failed_to_implement(self) -> None:
        """parse_failed_files_from_stderr() extracts 'Failed to implement:' lines."""
        stderr = """
Building...
Failed to implement: app/routes.ts
Debugging...
Failed to implement: components/Modal.tsx
"""
        result = parse_failed_files_from_stderr(stderr)
        assert "app/routes.ts" in result
        assert "components/Modal.tsx" in result

    def test_parse_failed_files_from_stderr_error_prefix(self) -> None:
        """parse_failed_files_from_stderr() extracts 'ERROR: file' pattern."""
        stderr = """
ERROR: src/api/handler.py — invalid syntax
ERROR: tests/test_utils.py — import error
"""
        result = parse_failed_files_from_stderr(stderr)
        assert "src/api/handler.py" in result
        assert "tests/test_utils.py" in result

    def test_parse_failed_files_from_stderr_failed_prefix(self) -> None:
        """parse_failed_files_from_stderr() extracts 'FAILED: file' pattern."""
        stderr = """
FAILED: lib/core.py
FAILED: lib/helpers.sh
"""
        result = parse_failed_files_from_stderr(stderr)
        assert "lib/core.py" in result
        assert "lib/helpers.sh" in result

    def test_parse_failed_files_from_stderr_deduplication(self) -> None:
        """parse_failed_files_from_stderr() deduplicates and sorts results."""
        stderr = """
Error processing file: src/a.py
Error processing file: src/b.py
Error processing file: src/a.py
Error processing file: src/c.py
"""
        result = parse_failed_files_from_stderr(stderr)
        # Should be deduplicated and sorted
        assert result == ["src/a.py", "src/b.py", "src/c.py"]

    def test_parse_failed_files_from_stderr_empty(self) -> None:
        """parse_failed_files_from_stderr() returns empty list for stderr with no matches."""
        stderr = "Some normal output\nNo errors here\n"
        result = parse_failed_files_from_stderr(stderr)
        assert result == []

    def test_failed_files_column_in_header(self) -> None:
        """failed_files column is present in HEADER."""
        assert "failed_files" in HEADER

    def test_scope_tag_column_in_header(self) -> None:
        """scope_tag column is present in HEADER (US-744)."""
        assert "scope_tag" in HEADER
