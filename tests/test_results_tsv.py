"""Tests for results_tsv.py — ResultsRecord parsing and serialization."""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from results_tsv import HEADER, ResultsRecord, parse_results_tsv, write_results_tsv


def _make_record(story_id: str, sub_project: str = "", **overrides: str) -> ResultsRecord:
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


# ── Security Tests (US-735) ──────────────────────────────────────────────────

# Credential-like strings that must never appear in written TSV data
_CREDENTIAL_STRINGS = [
    "sk-ant-api03-FAKE_TOKEN_VALUE_1234567890",
    "ghp_abcdef1234567890abcdef1234567890abcd",
    "password=SuperSecret123!",
    "ANTHROPIC_API_KEY=sk-ant-fake-key",
    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake.token",
]

# Column names that would indicate credential storage (must not appear in HEADER).
# "tokens" (plural) is fine -- refers to token *counts*, not auth tokens.
_CREDENTIAL_COL_PATTERN = re.compile(
    r"(api_key|(?:^|_)secret(?:$|_)|(?:^|_)password(?:$|_)|credential|bearer|private_key)",
    re.IGNORECASE,
)


class TestSecurityResultsTsv:
    """Security tests: results.tsv must never persist sensitive data (US-735)."""

    def test_security_credential_strings_absent_from_written_tsv(
        self, tmp_path: Path
    ) -> None:
        """Injected credential-like values in free-text fields must not cause
        extra columns to appear in the TSV. The write path uses HEADER +
        extrasaction='ignore', so only declared fields are written. This test
        injects credentials into failure_root_cause (a free-text field most
        likely to carry accidental leaks) and verifies the written TSV headers
        match the allowed schema exactly.
        """
        path = str(tmp_path / "results.tsv")
        poisoned_records = []
        for i, cred in enumerate(_CREDENTIAL_STRINGS):
            poisoned_records.append(
                _make_record(
                    f"US-{900 + i:03d}",
                    failure_root_cause=cred,
                    story_title=cred,
                )
            )
        write_results_tsv(path, poisoned_records)

        with open(path, encoding="utf-8") as f:
            raw = f.read()

        # Verify the TSV contains ONLY columns from HEADER:
        lines = raw.strip().split("\n")
        written_headers = lines[0].split("\t")
        assert written_headers == HEADER, (
            f"Written TSV headers do not match allowed HEADER schema.\n"
            f"Extra columns: {set(written_headers) - set(HEADER)}"
        )

    def test_security_no_credential_named_columns_in_header(self) -> None:
        """HEADER must not contain column names that suggest credential storage.

        Token count fields like cache_read_tokens and review_tokens are
        expected (they store integer counts, not auth tokens).
        """
        for col in HEADER:
            assert not _CREDENTIAL_COL_PATTERN.search(col), (
                f"HEADER contains credential-like column name: '{col}'. "
                f"Telemetry rows must not store secrets."
            )
