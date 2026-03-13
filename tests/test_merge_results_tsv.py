"""Tests for merge_results_tsv.py — parallel worker results.tsv merging."""
import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_results_tsv import merge, read_tsv, dedup_key, HEADER


def _write_tsv(path: str, rows: list[dict]) -> None:
    """Helper: write a results.tsv file with header + rows."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER, delimiter="\t",
                                extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _make_row(story_id: str, timestamp: str, status: str = "PASS",
              **overrides) -> dict:
    """Helper: create a results row with sensible defaults."""
    row = {
        "timestamp": timestamp,
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Title for {story_id}",
        "status": status,
        "duration_sec": "30",
        "model": "sonnet",
        "retry_num": "0",
        "commit_sha": "abc1234",
        "run_id": "test-run-id",
    }
    row.update(overrides)
    return row


class TestReadTsv:
    def test_read_missing_file(self):
        assert read_tsv("/nonexistent/path.tsv") == []

    def test_read_valid_file(self, tmp_path):
        path = str(tmp_path / "results.tsv")
        rows = [_make_row("US-001", "2026-03-13T10:00:00Z")]
        _write_tsv(path, rows)
        result = read_tsv(path)
        assert len(result) == 1
        assert result[0]["story_id"] == "US-001"


class TestDedupKey:
    def test_composite_key(self):
        row = _make_row("US-005", "2026-03-13T12:00:00Z")
        assert dedup_key(row) == ("US-005", "2026-03-13T12:00:00Z")

    def test_missing_fields_default_empty(self):
        assert dedup_key({}) == ("", "")


class TestMerge:
    def test_single_worker_no_existing_main(self, tmp_path):
        """Worker results create main results.tsv from scratch."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        _write_tsv(w1, [
            _make_row("US-001", "2026-03-13T10:00:00Z"),
            _make_row("US-002", "2026-03-13T10:05:00Z"),
        ])
        rc = merge(main_path, [w1])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 2
        assert result[0]["story_id"] == "US-001"
        assert result[1]["story_id"] == "US-002"

    def test_two_workers_merged(self, tmp_path):
        """Two workers' rows are combined into main."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        w2 = str(tmp_path / "w2.tsv")
        _write_tsv(w1, [_make_row("US-001", "2026-03-13T10:00:00Z")])
        _write_tsv(w2, [_make_row("US-002", "2026-03-13T10:01:00Z")])
        rc = merge(main_path, [w1, w2])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 2

    def test_existing_main_preserved(self, tmp_path):
        """Existing main rows are kept when merging worker rows."""
        main_path = str(tmp_path / "results.tsv")
        _write_tsv(main_path, [_make_row("US-099", "2026-03-12T08:00:00Z")])
        w1 = str(tmp_path / "w1.tsv")
        _write_tsv(w1, [_make_row("US-001", "2026-03-13T10:00:00Z")])
        rc = merge(main_path, [w1])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 2
        ids = {r["story_id"] for r in result}
        assert ids == {"US-099", "US-001"}

    def test_duplicate_rows_deduplicated(self, tmp_path):
        """Same story_id + timestamp appearing in multiple workers is inserted once."""
        main_path = str(tmp_path / "results.tsv")
        dup_row = _make_row("US-001", "2026-03-13T10:00:00Z")
        w1 = str(tmp_path / "w1.tsv")
        w2 = str(tmp_path / "w2.tsv")
        _write_tsv(w1, [dup_row])
        _write_tsv(w2, [dup_row])
        rc = merge(main_path, [w1, w2])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 1

    def test_duplicate_with_existing_main(self, tmp_path):
        """Rows already in main are not duplicated from workers."""
        main_path = str(tmp_path / "results.tsv")
        row = _make_row("US-001", "2026-03-13T10:00:00Z")
        _write_tsv(main_path, [row])
        w1 = str(tmp_path / "w1.tsv")
        _write_tsv(w1, [row])
        rc = merge(main_path, [w1])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 1

    def test_sorted_by_timestamp(self, tmp_path):
        """Merged rows are sorted chronologically by timestamp."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        w2 = str(tmp_path / "w2.tsv")
        _write_tsv(w1, [_make_row("US-003", "2026-03-13T12:00:00Z")])
        _write_tsv(w2, [_make_row("US-001", "2026-03-13T08:00:00Z")])
        _write_tsv(main_path, [_make_row("US-002", "2026-03-13T10:00:00Z")])
        rc = merge(main_path, [w1, w2])
        assert rc == 0
        result = read_tsv(main_path)
        timestamps = [r["timestamp"] for r in result]
        assert timestamps == sorted(timestamps)
        assert result[0]["story_id"] == "US-001"
        assert result[1]["story_id"] == "US-002"
        assert result[2]["story_id"] == "US-003"

    def test_missing_worker_file_skipped(self, tmp_path):
        """Missing worker file is skipped with warning, others still processed."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        _write_tsv(w1, [_make_row("US-001", "2026-03-13T10:00:00Z")])
        rc = merge(main_path, [w1, str(tmp_path / "nonexistent.tsv")])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 1

    def test_header_written_once(self, tmp_path):
        """Output file has exactly one header row."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        w2 = str(tmp_path / "w2.tsv")
        _write_tsv(w1, [_make_row("US-001", "2026-03-13T10:00:00Z")])
        _write_tsv(w2, [_make_row("US-002", "2026-03-13T10:01:00Z")])
        merge(main_path, [w1, w2])
        with open(main_path, encoding="utf-8") as f:
            lines = f.readlines()
        # First line is header, remaining are data
        assert lines[0].strip().startswith("timestamp")
        header_count = sum(1 for line in lines if line.startswith("timestamp\t"))
        assert header_count == 1

    def test_no_worker_results(self, tmp_path):
        """When no worker has results, main is unchanged or empty."""
        main_path = str(tmp_path / "results.tsv")
        rc = merge(main_path, [str(tmp_path / "nope.tsv")])
        assert rc == 0

    def test_same_story_different_timestamps(self, tmp_path):
        """Same story_id with different timestamps are both kept (different attempts)."""
        main_path = str(tmp_path / "results.tsv")
        w1 = str(tmp_path / "w1.tsv")
        _write_tsv(w1, [
            _make_row("US-001", "2026-03-13T10:00:00Z", status="FAIL"),
            _make_row("US-001", "2026-03-13T10:05:00Z", status="PASS"),
        ])
        rc = merge(main_path, [w1])
        assert rc == 0
        result = read_tsv(main_path)
        assert len(result) == 2
