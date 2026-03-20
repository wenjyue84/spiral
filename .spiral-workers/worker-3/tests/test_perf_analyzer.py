"""tests/test_perf_analyzer.py — Tests for US-546: Phase Timing Report & SLA Breach Analysis."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from perf_analyzer import (
    _median,
    _percentile,
    analyze_phase_timings,
)

# ── Helper to write a temp results.tsv ────────────────────────────────────────


def _write_tsv(rows: list[dict[str, Any]], path: str) -> None:
    """Write rows as a tab-separated file with results.tsv headers."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ── Unit tests: _percentile ───────────────────────────────────────────────────


def test_percentile_empty() -> None:
    assert _percentile([], 95) == 0.0


def test_percentile_single() -> None:
    assert _percentile([42.0], 95) == 42.0


def test_percentile_p50() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = _percentile(vals, 50)
    assert result == 3.0


def test_percentile_p95_100_values() -> None:
    """AC3: given 100 values [1..100], p95 should be 95."""
    vals = [float(i) for i in range(1, 101)]
    result = _percentile(vals, 95)
    assert result == 95.0


# ── Unit tests: _median ──────────────────────────────────────────────────────


def test_median_empty() -> None:
    assert _median([]) == 0.0


def test_median_odd() -> None:
    assert _median([1.0, 3.0, 5.0]) == 3.0


def test_median_even() -> None:
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


# ── Integration test: AC3 — 100 Phase R runs ─────────────────────────────────


def test_p95_100_phase_r_runs() -> None:
    """AC3: given 100 Phase R runs with durations [1..100], p95 is correctly computed as 95th percentile."""
    rows = [
        {
            "timestamp": f"2026-01-01T00:{i:02d}:00Z",
            "spiral_iter": str(i),
            "ralph_iter": "1",
            "story_id": f"US-{i:03d}",
            "story_title": f"Story {i}",
            "status": "accept",
            "duration_sec": str(i),
            "model": "haiku",
            "retry_num": "0",
            "commit_sha": "abc",
            "phase_name": "R",
        }
        for i in range(1, 101)
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = analyze_phase_timings(tmp_path)

        # Find the Phase R entry
        phase_r = next((e for e in result if e["phase"] == "R"), None)
        assert phase_r is not None, "Expected phase R entry in report"
        assert phase_r["p95_duration_sec"] == 95.0, f"Expected p95=95.0, got {phase_r['p95_duration_sec']}"
        assert phase_r["median_duration_sec"] == 50.5, f"Expected median=50.5, got {phase_r['median_duration_sec']}"
    finally:
        os.unlink(tmp_path)


# ── Integration test: AC1 — output structure ──────────────────────────────────


def test_output_structure() -> None:
    """AC1: output is array of {phase, median_duration_sec, p95_duration_sec, sla_threshold_sec, breach_count}."""
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "spiral_iter": "1",
            "story_id": "US-001",
            "status": "accept",
            "duration_sec": "100",
            "model": "haiku",
            "phase_name": "I",
        },
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "spiral_iter": "2",
            "story_id": "US-002",
            "status": "accept",
            "duration_sec": "200",
            "model": "haiku",
            "phase_name": "I",
        },
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = analyze_phase_timings(tmp_path)

        assert isinstance(result, list)
        for entry in result:
            assert "phase" in entry
            assert "median_duration_sec" in entry
            assert "p95_duration_sec" in entry
            assert "sla_threshold_sec" in entry
            assert "breach_count" in entry
    finally:
        os.unlink(tmp_path)


# ── SLA breach counting ──────────────────────────────────────────────────────


def test_sla_breach_counting() -> None:
    """breach_count reflects number of entries exceeding the SLA threshold."""
    rows = [
        {
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "spiral_iter": str(i),
            "story_id": f"US-{i:03d}",
            "status": "accept",
            "duration_sec": str(dur),
            "model": "haiku",
            "phase_name": "I",
        }
        for i, dur in enumerate([50, 100, 200, 400, 500])
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        # SLA of 150 sec → 3 breaches (200, 400, 500)
        result = analyze_phase_timings(tmp_path, sla_threshold_sec=150.0)
        phase_i = next((e for e in result if e["phase"] == "I"), None)
        assert phase_i is not None
        assert phase_i["breach_count"] == 3
    finally:
        os.unlink(tmp_path)


# ── Sub-phase column grouping ────────────────────────────────────────────────


def test_sub_phase_grouping() -> None:
    """When no phase_name column, groups by decompose_secs/impl_secs/verify_secs."""
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "spiral_iter": "1",
            "story_id": "US-001",
            "status": "accept",
            "duration_sec": "300",
            "model": "haiku",
            "decompose_secs": "10",
            "impl_secs": "250",
            "verify_secs": "40",
        },
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "spiral_iter": "2",
            "story_id": "US-002",
            "status": "accept",
            "duration_sec": "200",
            "model": "haiku",
            "decompose_secs": "20",
            "impl_secs": "150",
            "verify_secs": "30",
        },
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = analyze_phase_timings(tmp_path)

        phases = {e["phase"] for e in result}
        assert "decompose" in phases
        assert "impl" in phases
        assert "verify" in phases
        assert "total" in phases
    finally:
        os.unlink(tmp_path)


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_missing_tsv_returns_empty() -> None:
    """Returns empty list when TSV file does not exist."""
    result = analyze_phase_timings("/nonexistent/path/results.tsv")
    assert result == []


def test_empty_tsv_returns_empty() -> None:
    """Returns empty list when TSV has no data rows."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
        tmp_path = f.name
        f.write("timestamp\tstory_id\tduration_sec\tphase_name\n")
    try:
        result = analyze_phase_timings(tmp_path)
        assert result == []
    finally:
        os.unlink(tmp_path)
