#!/usr/bin/env python3
"""Tests for lib/cost_estimator.py — cost prediction with variance bounds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.cost_estimator import (
    compute_historical_stats,
    predict_cost_for_n_iterations,
)


@pytest.fixture
def sample_results_tsv(tmp_path: Path) -> Path:
    """Create a minimal results.tsv with 10 sample stories for testing."""
    tsv_file = tmp_path / "results.tsv"

    # Header + 10 sample rows with varying models and durations
    header = (
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
        "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id"
    )
    rows = [
        "2026-04-01T00:00:00Z\t1\t1\tUS-001\tCLI: add feature X\tpass\t60\thaiku\t0\tabc123\t1",
        "2026-04-01T01:00:00Z\t1\t2\tUS-002\tDashboard update\tpass\t120\tsonnet\t0\tabc123\t2",
        "2026-04-01T02:00:00Z\t1\t3\tUS-003\tPerf optimization\tpass\t180\topus\t0\tabc123\t3",
        "2026-04-01T03:00:00Z\t2\t1\tUS-004\tBug fix\tpass\t60\thaiku\t0\tabc123\t4",
        "2026-04-01T04:00:00Z\t2\t2\tUS-005\tIntegration test\tpass\t90\tsonnet\t0\tabc123\t5",
        "2026-04-01T05:00:00Z\t2\t3\tUS-006\tRefactor storage\tpass\t150\topus\t0\tabc123\t6",
        "2026-04-01T06:00:00Z\t3\t1\tUS-007\tAPI endpoint\tpass\t75\thaiku\t0\tabc123\t7",
        "2026-04-01T07:00:00Z\t3\t2\tUS-008\tFrontend UI\tpass\t120\tsonnet\t0\tabc123\t8",
        "2026-04-01T08:00:00Z\t3\t3\tUS-009\tBackend service\tpass\t180\topus\t0\tabc123\t9",
        "2026-04-01T09:00:00Z\t4\t1\tUS-010\tSecurity audit\tpass\t120\thaiku\t0\tabc123\t10",
    ]

    with open(tsv_file, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")

    return tsv_file


def test_compute_historical_stats_with_data(sample_results_tsv: Path) -> None:
    """Test compute_historical_stats returns correct structure with sample data."""
    stats = compute_historical_stats(str(sample_results_tsv))

    assert "per_model" in stats
    assert "per_complexity" in stats
    assert "total_attempts" in stats
    assert "model_distribution" in stats

    # Should have 3 models (haiku, sonnet, opus)
    assert "haiku" in stats["per_model"]
    assert "sonnet" in stats["per_model"]
    assert "opus" in stats["per_model"]

    # Should have 10 total attempts
    assert stats["total_attempts"] == 10

    # Check model distribution sums to ~100%
    total_pct = sum(stats["model_distribution"].values())
    assert 99.5 <= total_pct <= 100.5

    # Each model should have avg_cost, std_dev_cost, count
    for model, data in stats["per_model"].items():
        assert "avg_cost" in data
        assert "std_dev_cost" in data
        assert "count" in data
        assert data["count"] > 0
        assert data["avg_cost"] > 0


def test_compute_historical_stats_empty_file(tmp_path: Path) -> None:
    """Test compute_historical_stats returns empty structure for missing file."""
    empty_tsv = tmp_path / "empty.tsv"
    empty_tsv.touch()

    stats = compute_historical_stats(str(empty_tsv))

    assert stats["per_model"] == {}
    assert stats["per_complexity"] == {}
    assert stats["total_attempts"] == 0
    assert stats["model_distribution"] == {}


def test_compute_historical_stats_no_file() -> None:
    """Test compute_historical_stats handles missing file gracefully."""
    stats = compute_historical_stats("/nonexistent/results.tsv")

    assert stats["per_model"] == {}
    assert stats["per_complexity"] == {}
    assert stats["total_attempts"] == 0
    assert stats["model_distribution"] == {}


def test_predict_cost_for_n_iterations(sample_results_tsv: Path) -> None:
    """Test predict_cost_for_n_iterations returns expected fields and reasonable values."""
    prediction = predict_cost_for_n_iterations(5, str(sample_results_tsv))

    # Check all required fields present
    assert "estimated_cost" in prediction
    assert "confidence_lower" in prediction
    assert "confidence_upper" in prediction
    assert "per_story_avg" in prediction
    assert "breakdown_by_model" in prediction
    assert "total_attempts" in prediction
    assert "note" in prediction

    # Basic sanity checks
    assert prediction["estimated_cost"] > 0
    assert prediction["confidence_lower"] >= 0
    assert prediction["confidence_upper"] > 0
    assert prediction["confidence_lower"] <= prediction["estimated_cost"]
    assert prediction["estimated_cost"] <= prediction["confidence_upper"]
    assert prediction["per_story_avg"] > 0
    assert prediction["total_attempts"] == 10

    # Breakdown should have entries for each model
    assert len(prediction["breakdown_by_model"]) > 0


def test_predict_cost_for_n_iterations_single_iteration(
    sample_results_tsv: Path,
) -> None:
    """Test prediction for a single iteration."""
    prediction = predict_cost_for_n_iterations(1, str(sample_results_tsv))

    assert prediction["estimated_cost"] > 0
    assert prediction["total_attempts"] == 10


def test_predict_cost_for_n_iterations_many_iterations(
    sample_results_tsv: Path,
) -> None:
    """Test prediction for 100 iterations — cost should scale appropriately."""
    pred_5 = predict_cost_for_n_iterations(5, str(sample_results_tsv))
    pred_100 = predict_cost_for_n_iterations(100, str(sample_results_tsv))

    # Costs should scale roughly linearly (with variance bands)
    assert pred_100["estimated_cost"] > pred_5["estimated_cost"]
    # Should be approximately 20x larger
    ratio = pred_100["estimated_cost"] / pred_5["estimated_cost"]
    # Allow some variance tolerance: 15-25x is reasonable given sqrt scaling of variance
    assert 15 <= ratio <= 25


def test_predict_cost_for_n_iterations_no_data(tmp_path: Path) -> None:
    """Test prediction returns zero cost when no historical data available."""
    empty_tsv = tmp_path / "empty.tsv"
    empty_tsv.touch()

    prediction = predict_cost_for_n_iterations(5, str(empty_tsv))

    assert prediction["estimated_cost"] == 0.0
    assert prediction["confidence_lower"] == 0.0
    assert prediction["confidence_upper"] == 0.0
    assert prediction["per_story_avg"] == 0.0
    assert prediction["total_attempts"] == 0
    assert "No historical data" in prediction["note"]


def test_cost_estimate_with_variance(sample_results_tsv: Path) -> None:
    """Test cost_estimate_with_variance — confidence bounds contain mean."""
    result = predict_cost_for_n_iterations(10, str(sample_results_tsv))

    # Confidence lower should be less than or equal to mean
    assert result["confidence_lower"] <= result["estimated_cost"]
    # Confidence upper should be greater than or equal to mean
    assert result["confidence_upper"] >= result["estimated_cost"]
    # Range should be positive
    assert result["confidence_upper"] - result["confidence_lower"] > 0


def test_predict_cost_breakdown_by_model(sample_results_tsv: Path) -> None:
    """Test breakdown_by_model has all expected fields."""
    prediction = predict_cost_for_n_iterations(5, str(sample_results_tsv))

    for model, breakdown in prediction["breakdown_by_model"].items():
        assert "pct" in breakdown
        assert "cost_per_story" in breakdown
        assert "total_cost" in breakdown
        assert 0 < breakdown["pct"] <= 100
        assert breakdown["cost_per_story"] >= 0
        assert breakdown["total_cost"] >= 0


def test_predict_cost_json_serializable(sample_results_tsv: Path) -> None:
    """Test prediction result is JSON-serializable."""
    prediction = predict_cost_for_n_iterations(5, str(sample_results_tsv))

    # Should not raise
    json_str = json.dumps(prediction)
    assert json_str
    # Verify we can parse it back
    parsed = json.loads(json_str)
    assert parsed["estimated_cost"] > 0


def test_estimate_story_cost_breakdown(sample_results_tsv: Path, tmp_path: Path) -> None:
    """Test per-story cost breakdown generation."""
    from lib.cost_estimator import estimate_story_cost_breakdown

    # Create a minimal prd.json
    prd_file = tmp_path / "prd.json"
    prd_data = {
        "userStories": [
            {
                "id": "US-001",
                "title": "CLI feature",
                "passes": False,
                "estimatedComplexity": "small",
            },
            {
                "id": "US-002",
                "title": "Large refactor with many changes",
                "passes": False,
                "estimatedComplexity": "large",
            },
        ]
    }
    with open(prd_file, "w", encoding="utf-8") as f:
        json.dump(prd_data, f)

    breakdown = estimate_story_cost_breakdown(prd_data, str(sample_results_tsv))

    # Should have 2 stories
    assert len(breakdown) == 2

    # Each story should have required fields
    for story in breakdown:
        assert "story_id" in story
        assert "complexity" in story
        assert "cost_haiku" in story
        assert "cost_sonnet" in story
        assert "cost_opus" in story
        assert "escalation_prob" in story
        assert "model_pick" in story
        assert "total_cost" in story

    # Costs should be positive
    for story in breakdown:
        assert story["cost_haiku"] > 0
        assert story["cost_sonnet"] > story["cost_haiku"]
        assert story["cost_opus"] > story["cost_sonnet"]


def test_compute_parallelization_adjustment() -> None:
    """Test parallelization factor calculation."""
    from lib.cost_estimator import compute_parallelization_adjustment

    # 10 stories, 5 workers, 2 iterations
    # iterations_per_worker = ceil(10/5) = 2
    # total_parallel_iterations = 2 * 2 = 4
    adj = compute_parallelization_adjustment(10, 5, 2)

    assert adj["iterations_per_worker"] == 2
    assert adj["total_parallel_iterations"] == 4
    assert adj["parallelization_factor"] < 1.0  # Parallel is more efficient than serial


def test_format_table_output() -> None:
    """Test human-readable table formatting."""
    from lib.cost_estimator import format_table_output

    breakdown = [
        {
            "story_id": "US-001",
            "complexity": "small",
            "tokens_h": 5000,
            "tokens_s": 5000,
            "tokens_o": 5000,
            "cost_haiku": 0.01,
            "cost_sonnet": 0.02,
            "cost_opus": 0.05,
            "escalation_prob": 10.0,
            "model_pick": "haiku",
            "total_cost": 0.015,
        },
    ]

    output = format_table_output(breakdown, 0.015)

    # Verify table contains expected headers and data
    assert "Complexity" in output
    assert "US-001" in output
    assert "Grand Total" in output
    assert "$" in output  # Currency formatting
    assert "ID" in output  # Column header


def test_format_json_output() -> None:
    """Test JSON output formatting."""
    from lib.cost_estimator import format_json_output

    breakdown = [
        {
            "story_id": "US-001",
            "complexity": "small",
            "tokens_h": 5000,
            "tokens_s": 5000,
            "tokens_o": 5000,
            "cost_haiku": 0.01,
            "cost_sonnet": 0.02,
            "cost_opus": 0.05,
            "escalation_prob": 10.0,
            "model_pick": "haiku",
            "total_cost": 0.015,
        },
    ]

    output = format_json_output(breakdown, 0.015)

    # Should be valid JSON
    parsed = json.loads(output)
    assert "breakdown" in parsed
    assert "subtotal" in parsed
    assert "contingency" in parsed
    assert "grand_total" in parsed
    assert len(parsed["breakdown"]) == 1


def test_format_csv_output() -> None:
    """Test CSV output formatting."""
    from lib.cost_estimator import format_csv_output

    breakdown = [
        {
            "story_id": "US-001",
            "complexity": "small",
            "tokens_h": 5000,
            "tokens_s": 5000,
            "tokens_o": 5000,
            "cost_haiku": 0.01,
            "cost_sonnet": 0.02,
            "cost_opus": 0.05,
            "escalation_prob": 10.0,
            "model_pick": "haiku",
            "total_cost": 0.015,
        },
    ]

    output = format_csv_output(breakdown, 0.015)

    # Should have header and data rows
    lines = output.split("\n")
    assert len(lines) >= 3  # Header + at least 1 data row + TOTAL line
    assert "story_id" in lines[0]
    assert "US-001" in output
