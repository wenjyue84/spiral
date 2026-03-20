"""tests/test_cost_anomaly_detector.py — Tests for US-544: Cost Anomaly Detector."""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys_path_parent = Path(__file__).parent.parent / "lib"

import sys

sys.path.insert(0, str(sys_path_parent))

from cost_anomaly_detector import (
    _median,
    _stddev,
    _tokens_from_row,
    detect_anomalies,
    load_results,
)


# ── Helper to write a temp results.tsv ────────────────────────────────────────


def _write_tsv(rows: list[dict[str, Any]], path: str) -> None:
    """Write rows as a tab-separated file with standard results.tsv headers."""
    fieldnames = [
        "timestamp",
        "spiral_iter",
        "ralph_iter",
        "story_id",
        "story_title",
        "status",
        "duration_sec",
        "model",
        "retry_num",
        "commit_sha",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ── Unit tests: _median ────────────────────────────────────────────────────────


def test_median_empty() -> None:
    assert _median([]) == 0.0


def test_median_single() -> None:
    assert _median([42.0]) == 42.0


def test_median_odd() -> None:
    assert _median([1.0, 3.0, 5.0]) == 3.0


def test_median_even() -> None:
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


# ── Unit tests: _stddev ────────────────────────────────────────────────────────


def test_stddev_empty() -> None:
    assert _stddev([]) == 0.0


def test_stddev_single() -> None:
    assert _stddev([99.0]) == 0.0


def test_stddev_known() -> None:
    # population stddev of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
    result = _stddev([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert abs(result - 2.0) < 1e-9


# ── Unit tests: _tokens_from_row ───────────────────────────────────────────────


def test_tokens_from_row_uses_token_columns() -> None:
    row = {"tokens_in": "5000", "tokens_out": "3000", "duration_sec": "100"}
    assert _tokens_from_row(row) == 8000.0


def test_tokens_from_row_falls_back_to_duration() -> None:
    row = {"tokens_in": "0", "tokens_out": "", "duration_sec": "250"}
    result = _tokens_from_row(row)
    assert result == 250 * 40.0


def test_tokens_from_row_zero_row() -> None:
    row: dict[str, Any] = {}
    assert _tokens_from_row(row) == 0.0


# ── Integration test: AC3 — costs [10000, 11000, 9000, 50000] ─────────────────


def test_anomaly_detection_flags_outlier() -> None:
    """AC3: story with costs [10000, 11000, 9000, 50000] → flag 50000 as anomaly with zscore >= 2.0."""
    # duration_sec = cost / _TOKENS_PER_SEC (40) to produce desired token counts
    costs = [10000.0, 11000.0, 9000.0, 50000.0]
    rows = [
        {
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "spiral_iter": str(i),
            "ralph_iter": "1",
            "story_id": "US-001",
            "story_title": "Test story",
            "status": "accept",
            "duration_sec": str(cost / 40.0),
            "model": "haiku",
            "retry_num": "0",
            "commit_sha": "abc",
        }
        for i, cost in enumerate(costs)
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name

    try:
        _write_tsv(rows, tmp_path)
        result = detect_anomalies(tmp_path)

        anomalies = result["anomalies"]
        assert len(anomalies) >= 1, "Expected at least one anomaly"

        flagged_costs = [a["cost"] for a in anomalies]
        assert 50000.0 in flagged_costs, f"Expected 50000 flagged, got {flagged_costs}"

        flagged = next(a for a in anomalies if a["cost"] == 50000.0)
        assert flagged["zscore"] >= 2.0, f"z-score should be >= 2.0, got {flagged['zscore']}"
        assert flagged["storyId"] == "US-001"
    finally:
        os.unlink(tmp_path)


# ── Integration test: AC1 — output structure ──────────────────────────────────


def test_detect_anomalies_output_structure() -> None:
    """AC1: output JSON has anomalies list and summary dict with required fields."""
    rows = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "spiral_iter": "1",
            "ralph_iter": "1",
            "story_id": "US-100",
            "story_title": "Story A",
            "status": "accept",
            "duration_sec": "100",
            "model": "haiku",
            "retry_num": "0",
            "commit_sha": "abc",
        },
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "spiral_iter": "2",
            "ralph_iter": "2",
            "story_id": "US-100",
            "story_title": "Story A",
            "status": "accept",
            "duration_sec": "110",
            "model": "haiku",
            "retry_num": "1",
            "commit_sha": "def",
        },
        {
            "timestamp": "2026-01-01T00:02:00Z",
            "spiral_iter": "3",
            "ralph_iter": "3",
            "story_id": "US-100",
            "story_title": "Story A",
            "status": "accept",
            "duration_sec": "1000",
            "model": "sonnet",
            "retry_num": "2",
            "commit_sha": "ghi",
        },
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = detect_anomalies(tmp_path)

        # Check top-level keys
        assert "anomalies" in result
        assert "summary" in result

        # Check summary shape
        summary = result["summary"]
        assert "totalAnomalies" in summary
        assert "affectedStories" in summary
        assert isinstance(summary["totalAnomalies"], int)
        assert isinstance(summary["affectedStories"], int)

        # Check anomaly entry shape if any
        for anomaly in result["anomalies"]:
            assert "storyId" in anomaly
            assert "iteration" in anomaly
            assert "cost" in anomaly
            assert "median" in anomaly
            assert "zscore" in anomaly
            assert "model" in anomaly  # AC2: includes model
    finally:
        os.unlink(tmp_path)


# ── Integration test: AC2 — model included in anomaly entries ─────────────────


def test_anomaly_includes_model() -> None:
    """AC2: anomaly entries include the model used."""
    rows = [
        {
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "spiral_iter": str(i),
            "ralph_iter": "1",
            "story_id": "US-200",
            "story_title": "Big story",
            "status": "accept",
            "duration_sec": str(100 if i < 3 else 2000),
            "model": "opus" if i == 3 else "haiku",
            "retry_num": str(i),
            "commit_sha": "xyz",
        }
        for i in range(4)
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = detect_anomalies(tmp_path)
        anomalies = result["anomalies"]
        assert len(anomalies) >= 1
        # The anomaly should be from the opus row
        opus_anomaly = next((a for a in anomalies if a["model"] == "opus"), None)
        assert opus_anomaly is not None, "Expected anomaly for opus model row"
    finally:
        os.unlink(tmp_path)


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_no_anomalies_when_costs_uniform() -> None:
    """No anomalies when all costs are equal (stddev=0 → zscore=0)."""
    rows = [
        {
            "timestamp": f"2026-01-01T00:0{i}:00Z",
            "spiral_iter": str(i),
            "ralph_iter": "1",
            "story_id": "US-300",
            "story_title": "Uniform story",
            "status": "accept",
            "duration_sec": "250",
            "model": "haiku",
            "retry_num": str(i),
            "commit_sha": "abc",
        }
        for i in range(5)
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = detect_anomalies(tmp_path)
        assert result["anomalies"] == []
        assert result["summary"]["totalAnomalies"] == 0
    finally:
        os.unlink(tmp_path)


def test_missing_tsv_returns_empty() -> None:
    """Returns empty result when TSV file does not exist."""
    result = detect_anomalies("/nonexistent/path/results.tsv")
    assert result["anomalies"] == []
    assert result["summary"]["totalAnomalies"] == 0
    assert result["summary"]["affectedStories"] == 0


def test_summary_affected_stories_count() -> None:
    """affectedStories counts distinct story IDs that have anomalies."""
    # Two stories, each with one outlier
    def _make_rows(story_id: str, base_dur: float, spike_dur: float) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "spiral_iter": str(i),
                "ralph_iter": "1",
                "story_id": story_id,
                "story_title": story_id,
                "status": "accept",
                "duration_sec": str(spike_dur if i == 3 else base_dur),
                "model": "haiku",
                "retry_num": str(i),
                "commit_sha": "abc",
            }
            for i in range(4)
        ]

    rows = _make_rows("US-A", 100, 5000) + _make_rows("US-B", 200, 8000)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".tsv", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
    try:
        _write_tsv(rows, tmp_path)
        result = detect_anomalies(tmp_path)
        assert result["summary"]["affectedStories"] == 2
    finally:
        os.unlink(tmp_path)
