#!/usr/bin/env python3
"""Tests for lib/results_exporter.py"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib.results_exporter import (
    export_csv,
    export_json,
    filter_rows,
    parse_results_tsv,
)


@pytest.fixture
def sample_results_tsv(tmp_path: Path) -> Path:
    """Create a temporary results.tsv with 5 test stories."""
    results_file = tmp_path / "results.tsv"

    now = datetime.now(timezone.utc)
    timestamps = [
        (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    ]

    rows = [
        {
            "timestamp": timestamps[0],
            "spiral_iter": "1",
            "ralph_iter": "1",
            "story_id": "US-001",
            "story_title": "Test Story 1",
            "status": "pass",
            "duration_sec": "120",
            "model": "haiku",
            "retry_num": "0",
            "commit_sha": "abc123",
            "run_id": "run1",
            "cache_hit": "true",
            "cache_read_tokens": "1000",
            "cache_creation_tokens": "500",
            "review_tokens": "1500",
        },
        {
            "timestamp": timestamps[1],
            "spiral_iter": "1",
            "ralph_iter": "2",
            "story_id": "US-002",
            "story_title": "Test Story 2",
            "status": "fail",
            "duration_sec": "240",
            "model": "sonnet",
            "retry_num": "1",
            "commit_sha": "def456",
            "run_id": "run1",
            "cache_hit": "false",
            "cache_read_tokens": "2000",
            "cache_creation_tokens": "1000",
            "review_tokens": "3000",
        },
        {
            "timestamp": timestamps[2],
            "spiral_iter": "2",
            "ralph_iter": "3",
            "story_id": "US-003",
            "story_title": "Test Story 3",
            "status": "pass",
            "duration_sec": "180",
            "model": "opus",
            "retry_num": "0",
            "commit_sha": "ghi789",
            "run_id": "run2",
            "cache_hit": "true",
            "cache_read_tokens": "1500",
            "cache_creation_tokens": "750",
            "review_tokens": "2250",
        },
        {
            "timestamp": timestamps[3],
            "spiral_iter": "2",
            "ralph_iter": "4",
            "story_id": "US-004",
            "story_title": "Test Story 4",
            "status": "timeout",
            "duration_sec": "300",
            "model": "haiku",
            "retry_num": "2",
            "commit_sha": "jkl012",
            "run_id": "run2",
            "cache_hit": "false",
            "cache_read_tokens": "2500",
            "cache_creation_tokens": "1500",
            "review_tokens": "4000",
        },
        {
            "timestamp": timestamps[4],
            "spiral_iter": "3",
            "ralph_iter": "5",
            "story_id": "US-005",
            "story_title": "Test Story 5",
            "status": "pass",
            "duration_sec": "90",
            "model": "sonnet",
            "retry_num": "0",
            "commit_sha": "mno345",
            "run_id": "run3",
            "cache_hit": "true",
            "cache_read_tokens": "500",
            "cache_creation_tokens": "250",
            "review_tokens": "750",
        },
    ]

    # Write TSV
    with open(results_file, "w", newline="", encoding="utf-8") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    return results_file


def test_parse_results_tsv(sample_results_tsv: Path) -> None:
    """Test parsing results.tsv with derived field calculation."""
    rows = parse_results_tsv(sample_results_tsv)

    assert len(rows) == 5
    assert rows[0]["story_id"] == "US-001"
    assert rows[0]["model"] == "haiku"
    assert rows[0]["status"] == "pass"
    assert rows[0]["tokens_input"] > 0
    assert rows[0]["tokens_output"] > 0
    assert rows[0]["cost_usd"] > 0
    assert rows[0]["phase"] in ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C"]


def test_export_csv_escaping(sample_results_tsv: Path) -> None:
    """Test CSV export with proper escaping."""
    rows = parse_results_tsv(sample_results_tsv)
    csv_output = export_csv(rows)

    assert csv_output is not None
    assert "US-001" in csv_output
    assert "US-002" in csv_output
    # Check CSV format (no headers, proper columns)
    lines = csv_output.strip().split("\n")
    assert len(lines) == 5  # 5 data rows, no header

    # Verify column order
    first_line = lines[0]
    parts = first_line.split(",")
    assert parts[0] == "1"  # iteration
    assert "US-001" in parts[1]  # story_id


def test_export_csv_to_file(sample_results_tsv: Path, tmp_path: Path) -> None:
    """Test CSV export to file."""
    rows = parse_results_tsv(sample_results_tsv)
    output_file = tmp_path / "export.csv"

    export_csv(rows, output=output_file)

    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    assert "US-001" in content
    assert len(content.strip().split("\n")) == 5


def test_export_json_valid_schema(sample_results_tsv: Path) -> None:
    """Test JSON export with metadata and phase_times fields."""
    rows = parse_results_tsv(sample_results_tsv)
    json_output = export_json(rows)

    assert json_output is not None
    lines = json_output.strip().split("\n")
    assert len(lines) == 6  # metadata + 5 stories

    # Parse metadata (first line)
    metadata = json.loads(lines[0])
    assert metadata["type"] == "metadata"
    assert "timestamp" in metadata
    assert metadata["iteration_count"] > 0
    assert metadata["total_cost_usd"] > 0
    assert metadata["story_count"] == 5

    # Parse first story row
    story = json.loads(lines[1])
    assert "story_id" in story
    assert "phase_times" in story
    assert isinstance(story["phase_times"], dict)
    assert len(story["phase_times"]) > 0


def test_filter_rows_by_status(sample_results_tsv: Path) -> None:
    """Test filtering by status."""
    rows = parse_results_tsv(sample_results_tsv)

    pass_rows = filter_rows(rows, status="pass")
    assert len(pass_rows) == 3  # US-001, US-003, US-005

    fail_rows = filter_rows(rows, status="fail")
    assert len(fail_rows) == 1  # US-002

    timeout_rows = filter_rows(rows, status="timeout")
    assert len(timeout_rows) == 1  # US-004


def test_filter_rows_by_since(sample_results_tsv: Path) -> None:
    """Test filtering by timestamp."""
    rows = parse_results_tsv(sample_results_tsv)

    # Filter by a timestamp that excludes the first 2 rows
    since_time = rows[1]["timestamp"]
    filtered = filter_rows(rows, since=since_time)

    assert len(filtered) == 3  # Rows 2, 3, 4 (after the since timestamp)


def test_filter_rows_combined(sample_results_tsv: Path) -> None:
    """Test filtering by both status and timestamp."""
    rows = parse_results_tsv(sample_results_tsv)

    since_time = rows[1]["timestamp"]
    filtered = filter_rows(rows, since=since_time, status="pass")

    # Should only include US-003 and US-005 (both pass, after since_time)
    assert len(filtered) == 2
    assert all(r["status"] == "pass" for r in filtered)


def test_export_empty_results() -> None:
    """Test export with empty results."""
    rows: list[dict] = []

    csv_output = export_csv(rows)
    assert csv_output is not None
    assert csv_output.strip() == ""

    json_output = export_json(rows)
    assert json_output is not None
    lines = json_output.strip().split("\n")
    assert len(lines) == 1  # Only metadata
    metadata = json.loads(lines[0])
    assert metadata["story_count"] == 0
