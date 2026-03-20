"""Tests for results_tsv.py — ResultsRecord parsing and serialization."""

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from results_tsv import HEADER, ResultsRecord, parse_results_tsv, write_results_tsv


def _make_record(story_id: str, sub_project: str = "", **overrides) -> ResultsRecord:
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

    def test_record_creation_with_sub_project(self):
        """ResultsRecord can be created with sub_project field."""
        record = _make_record("US-001", sub_project="frontend")
        assert record.sub_project == "frontend"

    def test_record_default_sub_project_empty(self):
        """ResultsRecord defaults sub_project to empty string."""
        record = _make_record("US-002")
        assert record.sub_project == ""


class TestParseBackwardCompat:
    """Tests for backward-compatible parsing of old TSV files."""

    def test_parse_old_tsv_without_sub_project(self, tmp_path):
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

    def test_parse_missing_file_returns_empty(self):
        """Parsing nonexistent file returns empty list."""
        records = parse_results_tsv("/nonexistent/path.tsv")
        assert records == []


class TestRoundTrip:
    """Tests for write/read round-trip with sub_project."""

    def test_round_trip_with_sub_project(self, tmp_path):
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

    def test_round_trip_empty_sub_project(self, tmp_path):
        """Write and read back with empty sub_project."""
        path = str(tmp_path / "results.tsv")

        # Create and write a record without sub_project (empty)
        original = _make_record("US-002")
        write_results_tsv(path, [original])

        # Read back and verify sub_project is empty
        records = parse_results_tsv(path)
        assert len(records) == 1
        assert records[0].sub_project == ""

    def test_round_trip_multiple_records_different_sub_projects(self, tmp_path):
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
