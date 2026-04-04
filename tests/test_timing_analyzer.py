"""Tests for lib/observability/timing_analyzer.py (US-1097)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from observability.timing_analyzer import (
    compute_stats,
    format_timing_grid,
    format_timing_json,
    identify_outliers,
    parse_events,
)


@pytest.fixture
def temp_events_file() -> str:
    """Create a temporary spiral_events.jsonl file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fh:
        return fh.name


def test_parse_events_with_duration_field(temp_events_file: str) -> None:
    """Test parsing events with explicit duration_s field."""
    events = [
        {"event": "phase_start", "phase": "A", "iteration": 1, "ts": "2026-04-05T10:00:00Z"},
        {"event": "phase_end", "phase": "A", "iteration": 1, "duration_s": 5, "ts": "2026-04-05T10:00:05Z"},
        {"event": "phase_start", "phase": "R", "iteration": 1, "ts": "2026-04-05T10:00:05Z"},
        {"event": "phase_end", "phase": "R", "iteration": 1, "duration_s": 10, "ts": "2026-04-05T10:00:15Z"},
    ]

    with open(temp_events_file, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")

    durations = parse_events(temp_events_file)

    assert durations[(1, "A")] == 5.0
    assert durations[(1, "R")] == 10.0


def test_parse_events_with_timestamp_computation(temp_events_file: str) -> None:
    """Test parsing events and computing duration from start/end timestamps."""
    events = [
        {"event": "phase_start", "phase": "A", "iteration": 1, "ts": "2026-04-05T10:00:00Z"},
        {"event": "phase_end", "phase": "A", "iteration": 1, "ts": "2026-04-05T10:00:03.5Z"},
    ]

    with open(temp_events_file, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")

    durations = parse_events(temp_events_file)

    # Duration should be ~3.5 seconds (allowing for rounding)
    assert (1, "A") in durations
    assert 3.4 < durations[(1, "A")] < 3.6


def test_parse_events_multiple_iterations(temp_events_file: str) -> None:
    """Test parsing events across multiple iterations."""
    events = [
        {"event": "phase_end", "phase": "A", "iteration": 1, "duration_s": 5},
        {"event": "phase_end", "phase": "A", "iteration": 2, "duration_s": 7},
        {"event": "phase_end", "phase": "A", "iteration": 3, "duration_s": 6},
        {"event": "phase_end", "phase": "R", "iteration": 1, "duration_s": 10},
        {"event": "phase_end", "phase": "R", "iteration": 2, "duration_s": 12},
    ]

    with open(temp_events_file, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")

    durations = parse_events(temp_events_file)

    assert durations[(1, "A")] == 5.0
    assert durations[(2, "A")] == 7.0
    assert durations[(3, "A")] == 6.0
    assert durations[(1, "R")] == 10.0
    assert durations[(2, "R")] == 12.0


def test_compute_stats_outlier_detection() -> None:
    """Test outlier detection (>mean+2sigma)."""
    # Durations: A=[10,10,10,10,10,10,10,10,10,200], R=[10,10,10,10,10]
    # Phase A: mean=29, sigma≈60.1, threshold≈149.2 → 200 IS outlier!
    durations = {
        (1, "A"): 10.0,
        (2, "A"): 10.0,
        (3, "A"): 10.0,
        (4, "A"): 10.0,
        (5, "A"): 10.0,
        (6, "A"): 10.0,
        (7, "A"): 10.0,
        (8, "A"): 10.0,
        (9, "A"): 10.0,
        (10, "A"): 200.0,  # Clear outlier
        (1, "R"): 10.0,
        (2, "R"): 10.0,
        (3, "R"): 10.0,
    }

    stats = compute_stats(durations)

    # Phase A should have iteration 10 as outlier
    assert "A" in stats
    assert 10 in stats["A"]["outliers"], f"Expected 10 in outliers, got {stats['A']['outliers']}"
    assert stats["A"]["mean"] == 29.0

    # Phase R should have no outliers
    assert "R" in stats
    assert len(stats["R"]["outliers"]) == 0


def test_identify_outliers() -> None:
    """Test outlier map generation."""
    stats = {
        "A": {
            "mean": 10.0,
            "sigma": 5.0,
            "threshold": 20.0,
            "outliers": {2, 5},
        },
        "R": {
            "mean": 10.0,
            "sigma": 2.0,
            "threshold": 14.0,
            "outliers": set(),
        },
    }

    outlier_map = identify_outliers(stats)

    assert outlier_map[(2, "A")] is True
    assert outlier_map[(5, "A")] is True
    assert (1, "A") not in outlier_map
    assert (1, "R") not in outlier_map


def test_format_timing_grid() -> None:
    """Test grid formatting output."""
    durations = {
        (1, "A"): 5.0,
        (1, "R"): 10.0,
        (2, "A"): 7.0,
        (2, "R"): 30.0,  # Outlier
    }

    stats = {
        "A": {"mean": 6.0, "sigma": 1.0, "threshold": 8.0, "outliers": set()},
        "R": {"mean": 20.0, "sigma": 10.0, "threshold": 40.0, "outliers": set()},
    }

    outlier_map = {(2, "R"): True}

    output = format_timing_grid(durations, stats, outlier_map)

    # Verify structure
    assert "Iteration" in output
    assert "A" in output
    assert "R" in output
    assert "***" in output  # Outlier marker
    assert "5.0" in output or "5.0s" in output  # Duration format


def test_format_timing_json() -> None:
    """Test JSON formatting output."""
    durations = {
        (1, "A"): 5.0,
        (2, "A"): 7.0,
    }

    stats = {
        "A": {"mean": 6.0, "sigma": 1.0, "threshold": 8.0, "outliers": set()},
    }

    outlier_map = {}

    output = format_timing_json(durations, stats, outlier_map)

    # Parse JSON
    result = json.loads(output)

    assert "grid" in result
    assert "stats" in result
    assert "1" in result["grid"]  # Iteration as string key
    assert "A" in result["grid"]["1"]
    assert result["grid"]["1"]["A"]["duration_s"] == 5.0
    assert result["grid"]["1"]["A"]["is_outlier"] is False


def test_parse_events_empty_file(temp_events_file: str) -> None:
    """Test parsing empty events file."""
    # File exists but is empty
    Path(temp_events_file).touch()

    durations = parse_events(temp_events_file)

    assert durations == {}


def test_parse_events_missing_file() -> None:
    """Test parsing non-existent file."""
    durations = parse_events("/nonexistent/path/spiral_events.jsonl")

    assert durations == {}


def test_compute_stats_single_phase() -> None:
    """Test stats computation with single phase."""
    durations = {
        (1, "A"): 5.0,
        (2, "A"): 5.0,
        (3, "A"): 5.0,
    }

    stats = compute_stats(durations)

    assert "A" in stats
    assert stats["A"]["mean"] == 5.0
    assert stats["A"]["sigma"] == 0.0
    assert len(stats["A"]["outliers"]) == 0
