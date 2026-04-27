#!/usr/bin/env python3
"""
test_cost_analysis.py — Tests for the cost_analysis module.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.cost_analysis import (
    compute_iteration_costs,
    compute_model_costs,
    compute_phase_costs,
    compute_story_costs,
    parse_results_tsv,
)


def test_parse_results_tsv_empty_file():
    """Test parsing an empty results.tsv."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\n")
        f.flush()
        path = Path(f.name)

    try:
        rows = parse_results_tsv(path)
        assert rows == []
    finally:
        path.unlink()


def test_parse_results_tsv_with_data():
    """Test parsing results.tsv with actual data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\n")
        f.write("2026-04-05T20:15:47Z\t1\t1\tUS-100\tTest Story\tkeep\t300\thaiku\t0\n")
        f.write("2026-04-05T21:00:00Z\t2\t1\tUS-101\tAnother Story\tkeep\t600\tsonnet\t1\n")
        f.flush()
        path = Path(f.name)

    try:
        rows = parse_results_tsv(path)
        assert len(rows) == 2
        assert rows[0]["story_id"] == "US-100"
        assert rows[0]["model"] == "haiku"
        assert rows[0]["duration_sec"] == 300.0
        assert rows[0]["spiral_iter"] == 1
        assert rows[0]["tokens"] > 0
        assert rows[0]["cost_usd"] > 0
        assert rows[1]["story_id"] == "US-101"
        assert rows[1]["model"] == "sonnet"
        assert rows[1]["duration_sec"] == 600.0
    finally:
        path.unlink()


def test_compute_model_costs():
    """Test computing costs by model."""
    rows = [
        {
            "story_id": "US-100",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
        {
            "story_id": "US-101",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
        {
            "story_id": "US-102",
            "model": "sonnet",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.005,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
    ]

    model_costs = compute_model_costs(rows)
    assert "haiku" in model_costs
    assert "sonnet" in model_costs
    assert model_costs["haiku"] == pytest.approx(0.002, abs=0.0001)
    assert model_costs["sonnet"] == pytest.approx(0.005, abs=0.0001)


def test_compute_story_costs():
    """Test computing costs by story."""
    rows = [
        {
            "story_id": "US-100",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "First Story",
        },
        {
            "story_id": "US-100",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 1,
            "status": "keep",
            "title": "First Story",
        },
        {
            "story_id": "US-101",
            "model": "sonnet",
            "duration_sec": 200.0,
            "tokens": 4000,
            "cost_usd": 0.010,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Second Story",
        },
    ]

    story_costs = compute_story_costs(rows)
    assert len(story_costs) == 2
    # Should be sorted by cost descending
    assert story_costs[0][0] == "US-101"  # Higher cost
    assert story_costs[0][2] == pytest.approx(0.010, abs=0.0001)
    assert story_costs[0][3] == 1  # Attempt count
    assert story_costs[1][0] == "US-100"  # Lower cost
    assert story_costs[1][2] == pytest.approx(0.002, abs=0.0001)
    assert story_costs[1][3] == 2  # Two attempts


def test_compute_iteration_costs():
    """Test computing costs by iteration."""
    rows = [
        {
            "story_id": "US-100",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
        {
            "story_id": "US-101",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
        {
            "story_id": "US-102",
            "model": "sonnet",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.005,
            "spiral_iter": 2,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
    ]

    iter_costs = compute_iteration_costs(rows)
    assert 1 in iter_costs
    assert 2 in iter_costs
    assert iter_costs[1] == pytest.approx(0.002, abs=0.0001)
    assert iter_costs[2] == pytest.approx(0.005, abs=0.0001)


def test_cost_breakdown_by_phase():
    """
    Integration test for cost breakdown.

    This is the test referenced in the story's technical notes.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\n")
        f.write("2026-04-05T20:15:47Z\t1\t1\tUS-100\tTest Story 1\tkeep\t300\thaiku\t0\n")
        f.write("2026-04-05T21:00:00Z\t2\t1\tUS-101\tTest Story 2\tkeep\t600\tsonnet\t1\n")
        f.write("2026-04-05T22:00:00Z\t2\t1\tUS-102\tTest Story 3\tkeep\t300\topus\t0\n")
        f.flush()
        path = Path(f.name)

    try:
        rows = parse_results_tsv(path)
        assert len(rows) == 3

        # Verify model breakdown
        model_costs = compute_model_costs(rows)
        assert len(model_costs) == 3
        assert all(cost > 0 for cost in model_costs.values())

        # Verify story breakdown
        story_costs = compute_story_costs(rows)
        assert len(story_costs) == 3

        # Verify iteration breakdown
        iter_costs = compute_iteration_costs(rows)
        assert len(iter_costs) == 2
        assert iter_costs[1] > 0
        assert iter_costs[2] > 0
    finally:
        path.unlink()


def test_parse_results_tsv_with_invalid_duration():
    """Test that rows with invalid duration are skipped."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\n")
        f.write("2026-04-05T20:15:47Z\t1\t1\tUS-100\tTest Story\tkeep\t300\thaiku\n")
        f.write("2026-04-05T21:00:00Z\t2\t1\tUS-101\tBad Story\tkeep\tinvalid\tsonnet\n")
        f.flush()
        path = Path(f.name)

    try:
        rows = parse_results_tsv(path)
        assert len(rows) == 1
        assert rows[0]["story_id"] == "US-100"
    finally:
        path.unlink()


def test_parse_results_tsv_missing_file():
    """Test parsing a non-existent file."""
    path = Path("/nonexistent/results.tsv")
    rows = parse_results_tsv(path)
    assert rows == []


def test_compute_phase_costs():
    """Test computing costs by phase."""
    rows = [
        {
            "story_id": "US-100",
            "model": "haiku",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.001,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
        {
            "story_id": "US-101",
            "model": "sonnet",
            "duration_sec": 100.0,
            "tokens": 2000,
            "cost_usd": 0.005,
            "spiral_iter": 1,
            "retry_num": 0,
            "status": "keep",
            "title": "Test",
        },
    ]

    phase_costs = compute_phase_costs(rows)
    # Should have all phases
    assert len(phase_costs) == 12
    assert all(phase in phase_costs for phase in ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C", "L"])
    # Costs should be positive and sum to total
    assert all(cost > 0 for cost in phase_costs.values())
    total = sum(phase_costs.values())
    assert total == pytest.approx(0.006, abs=0.0001)
