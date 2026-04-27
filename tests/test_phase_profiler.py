"""Tests for lib/phase_profiler.py"""

import json
import tempfile
from pathlib import Path

import pytest

from lib.phase_profiler import format_profile_table, parse_timings


def test_parse_timings_basic():
    """Test parsing valid JSONL timing records."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write('{"phase": "R", "start_ms": 1000, "end_ms": 2000}\n')
        f.write('{"phase": "T", "start_ms": 2000, "end_ms": 3500}\n')
        f.flush()

        records = parse_timings(f.name)

        assert len(records) == 2
        assert records[0]["phase"] == "R"
        assert records[0]["duration_ms"] == 1000
        assert records[1]["phase"] == "T"
        assert records[1]["duration_ms"] == 1500

        Path(f.name).unlink()


def test_parse_timings_with_malformed_lines():
    """Test that malformed lines are skipped gracefully."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write('{"phase": "R", "start_ms": 1000, "end_ms": 2000}\n')
        f.write("this is not valid json\n")
        f.write('{"phase": "T", "start_ms": 2000, "end_ms": 3500}\n')
        f.flush()

        records = parse_timings(f.name)

        # Should skip the malformed line
        assert len(records) == 2
        assert records[0]["phase"] == "R"
        assert records[1]["phase"] == "T"

        Path(f.name).unlink()


def test_parse_timings_file_not_found():
    """Test that FileNotFoundError is raised for missing file."""
    with pytest.raises(FileNotFoundError):
        parse_timings("/nonexistent/path/timings.jsonl")


def test_parse_timings_empty_file():
    """Test parsing an empty JSONL file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.flush()
        records = parse_timings(f.name)
        assert records == []
        Path(f.name).unlink()


def test_parse_timings_negative_duration():
    """Test that negative durations are normalized to 0."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write('{"phase": "R", "start_ms": 2000, "end_ms": 1000}\n')
        f.flush()

        records = parse_timings(f.name)

        assert len(records) == 1
        assert records[0]["duration_ms"] == 0  # max(0, -1000) = 0

        Path(f.name).unlink()


def test_format_profile_table_sorted_by_duration():
    """Test that output table is sorted by duration descending."""
    records = [
        {"phase": "R", "start_ms": 1000, "end_ms": 2000, "duration_ms": 1000},
        {"phase": "I", "start_ms": 2000, "end_ms": 7000, "duration_ms": 5000},
        {"phase": "T", "start_ms": 7000, "end_ms": 8500, "duration_ms": 1500},
    ]

    output = format_profile_table(records)

    # Check that output contains phases in correct order
    assert "Phase I" in output or "I" in output
    assert "Phase T" in output or "T" in output
    assert "Phase R" in output or "R" in output

    # Check that I (5000ms) appears before T (1500ms) which appears before R (1000ms)
    i_pos = output.find("I")
    t_pos = output.find("T")
    r_pos = output.find("R")
    assert i_pos < t_pos < r_pos


def test_format_profile_table_percentage_calculation():
    """Test that percentages are calculated correctly."""
    records = [
        {"phase": "R", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000},  # 50%
        {"phase": "T", "start_ms": 1000, "end_ms": 3000, "duration_ms": 2000},  # 100% (should be 50%)
    ]

    output = format_profile_table(records)

    # Total should be 3000ms
    # T: 2000/3000 = 66.7%
    # R: 1000/3000 = 33.3%
    assert "66.7" in output or "66.6" in output  # T's percentage
    assert "33.3" in output or "33.3" in output  # R's percentage


def test_format_profile_table_high_impact_detection():
    """Test that phases >30% of total are flagged."""
    records = [
        {"phase": "I", "start_ms": 0, "end_ms": 4000, "duration_ms": 4000},  # 80% of total
        {"phase": "V", "start_ms": 4000, "end_ms": 5000, "duration_ms": 1000},  # 20% of total
    ]

    output = format_profile_table(records)

    # Phase I is 80%, should trigger high-impact warning
    assert "High-impact" in output
    assert "Phase I" in output or "I:" in output


def test_format_profile_table_no_high_impact():
    """Test when no phases exceed 30% threshold."""
    records = [
        {"phase": "R", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000},
        {"phase": "T", "start_ms": 1000, "end_ms": 2000, "duration_ms": 1000},
        {"phase": "M", "start_ms": 2000, "end_ms": 3000, "duration_ms": 1000},
        {"phase": "I", "start_ms": 3000, "end_ms": 4000, "duration_ms": 1000},
    ]

    output = format_profile_table(records)

    # Each phase is 25%, none exceed 30%
    assert "High-impact" not in output


def test_format_profile_table_empty_records():
    """Test formatting empty records list."""
    output = format_profile_table([])
    assert "No phase timings recorded" in output


def test_format_profile_table_includes_summary():
    """Test that summary statistics are included in output."""
    records = [
        {"phase": "R", "start_ms": 0, "end_ms": 1000, "duration_ms": 1000},
        {"phase": "T", "start_ms": 1000, "end_ms": 3000, "duration_ms": 2000},
    ]

    output = format_profile_table(records)

    # Should include slowest phase
    assert "Slowest phase" in output
    assert "T" in output  # T is slowest (2000ms)


def test_format_profile_table_incomplete_status():
    """Test that incomplete phases are marked correctly."""
    records = [
        {"phase": "R", "duration_ms": 1000},  # Missing start_ms/end_ms
        {"phase": "T", "start_ms": 1000, "end_ms": 2000, "duration_ms": 1000},
    ]

    output = format_profile_table(records)

    # Should indicate which phases are incomplete
    assert "incomplete" in output or "⚠" in output
