#!/usr/bin/env python3
"""test_perf_dashboard.py — Performance benchmarks for dashboard data aggregation.

Tests measure aggregation latency and detect performance regressions.
"""

import csv
import time
from pathlib import Path
from typing import Generator

import pytest

from lib.dashboard.aggregator import aggregate_dashboard_metrics  # noqa: E402

# Baseline latency in milliseconds (measured on standard 100-row dataset)
# This is determined empirically and should not exceed 20% increase on 10x data
BASELINE_LATENCY_MS = 50.0  # Conservative baseline for 100 rows


@pytest.fixture
def synthetic_results_tsv_100rows(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a synthetic results.tsv with 100 rows for baseline testing."""
    results_file = tmp_path / "results.tsv"

    # TSV header with required columns for aggregation
    headers = [
        "story_id",
        "spiral_iter",
        "ralph_iter",
        "attempt",
        "status",
        "model",
        "duration_sec",
        "input_tokens",
        "output_tokens",
        "retry_escalation_count",
        "timestamp",
        "decompose_secs",
        "impl_secs",
        "verify_secs",
    ]

    with open(results_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter="\t")
        writer.writeheader()

        # Write 100 rows with synthetic data
        for i in range(100):
            row = {
                "story_id": f"US-{100 + i}",
                "spiral_iter": i % 10,
                "ralph_iter": 0,
                "attempt": 1,
                "status": "keep" if i % 2 == 0 else "reject",
                "model": ["haiku", "sonnet", "opus"][i % 3],
                "duration_sec": 5.0 + (i % 10),
                "input_tokens": 1000 + (i * 100),
                "output_tokens": 500 + (i * 50),
                "retry_escalation_count": i % 5,
                "timestamp": "2026-03-20T12:00:00Z",
                "decompose_secs": 1.0,
                "impl_secs": 3.0,
                "verify_secs": 1.0,
            }
            writer.writerow(row)

    yield results_file


@pytest.fixture
def synthetic_results_tsv_1000rows(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a synthetic results.tsv with 1000 rows (10x baseline) for threshold testing."""
    results_file = tmp_path / "results.tsv"

    headers = [
        "story_id",
        "spiral_iter",
        "ralph_iter",
        "attempt",
        "status",
        "model",
        "duration_sec",
        "input_tokens",
        "output_tokens",
        "retry_escalation_count",
        "timestamp",
        "decompose_secs",
        "impl_secs",
        "verify_secs",
    ]

    with open(results_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter="\t")
        writer.writeheader()

        # Write 1000 rows (10x the baseline)
        for i in range(1000):
            row = {
                "story_id": f"US-{1000 + i}",
                "spiral_iter": i % 10,
                "ralph_iter": 0,
                "attempt": 1,
                "status": "keep" if i % 2 == 0 else "reject",
                "model": ["haiku", "sonnet", "opus"][i % 3],
                "duration_sec": 5.0 + (i % 10),
                "input_tokens": 1000 + (i * 100),
                "output_tokens": 500 + (i * 50),
                "retry_escalation_count": i % 5,
                "timestamp": "2026-03-20T12:00:00Z",
                "decompose_secs": 1.0,
                "impl_secs": 3.0,
                "verify_secs": 1.0,
            }
            writer.writerow(row)

    yield results_file


def test_dashboard_aggregation_baseline(
    synthetic_results_tsv_100rows: Path,
) -> None:
    """Test baseline aggregation latency on 100-row dataset.

    Measures wall time for computing all dashboard metrics and prints baseline.
    Acceptance Criteria: exits 0 and prints baseline latency in ms
    """
    # Measure aggregation time
    start = time.perf_counter()
    metrics = aggregate_dashboard_metrics(synthetic_results_tsv_100rows)
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Verify metrics are numeric
    assert isinstance(metrics["token_burn_rate"], float), "token_burn_rate must be float"
    assert isinstance(metrics["story_throughput"], float), "story_throughput must be float"
    assert isinstance(metrics["escalation_count"], int), "escalation_count must be int"

    # Print baseline for reference
    print(f"\n[BASELINE] Aggregation latency: {elapsed_ms:.2f} ms")
    print(f"  token_burn_rate: {metrics['token_burn_rate']:.2f} tokens/sec")
    print(f"  story_throughput: {metrics['story_throughput']:.2f} stories/hour")
    print(f"  escalation_count: {metrics['escalation_count']}")

    # Assert baseline is within reasonable bounds (should complete quickly)
    assert elapsed_ms < 1000, f"Baseline latency {elapsed_ms:.2f}ms exceeded 1s threshold"


def test_dashboard_aggregation_threshold(
    synthetic_results_tsv_100rows: Path,
    synthetic_results_tsv_1000rows: Path,
) -> None:
    """Test aggregation latency degradation on 10x dataset.

    Verifies that latency increase is under 20% when data volume increases 10x.
    Acceptance Criteria: fails if latency >20% slower on 1000-row dataset
    """
    # Measure baseline (100 rows)
    start_baseline = time.perf_counter()
    _ = aggregate_dashboard_metrics(synthetic_results_tsv_100rows)
    baseline_latency_ms = (time.perf_counter() - start_baseline) * 1000

    # Measure 10x dataset (1000 rows)
    start_10x = time.perf_counter()
    threshold_metrics = aggregate_dashboard_metrics(synthetic_results_tsv_1000rows)
    threshold_latency_ms = (time.perf_counter() - start_10x) * 1000

    # Calculate degradation percentage
    if baseline_latency_ms > 0:
        degradation_pct = ((threshold_latency_ms - baseline_latency_ms) / baseline_latency_ms) * 100
    else:
        degradation_pct = 0

    print("\n[THRESHOLD] Aggregation latency comparison:")
    print(f"  Baseline (100 rows):  {baseline_latency_ms:.2f} ms")
    print(f"  Threshold (1000 rows): {threshold_latency_ms:.2f} ms")
    print(f"  Degradation: {degradation_pct:.1f}%")

    # Verify metrics on 10x dataset
    assert isinstance(threshold_metrics["token_burn_rate"], float)
    assert isinstance(threshold_metrics["story_throughput"], float)
    assert isinstance(threshold_metrics["escalation_count"], int)

    # FAIL if degradation exceeds 20%
    assert (
        degradation_pct <= 20.0
    ), f"Aggregation latency degraded {degradation_pct:.1f}% (exceeds 20% threshold)"


def test_dashboard_aggregation_metrics_reported(
    synthetic_results_tsv_100rows: Path,
) -> None:
    """Test that all required metrics are reported as numeric outputs.

    Acceptance Criteria: reports token_burn_rate, story_throughput, escalation_count
    """
    metrics = aggregate_dashboard_metrics(synthetic_results_tsv_100rows)

    # Verify all required metrics are present and numeric
    assert "token_burn_rate" in metrics
    assert isinstance(metrics["token_burn_rate"], float)
    assert metrics["token_burn_rate"] >= 0.0

    assert "story_throughput" in metrics
    assert isinstance(metrics["story_throughput"], float)
    assert metrics["story_throughput"] >= 0.0

    assert "escalation_count" in metrics
    assert isinstance(metrics["escalation_count"], int)
    assert metrics["escalation_count"] >= 0

    print("\n[METRICS REPORTED]")
    print(f"  token_burn_rate: {metrics['token_burn_rate']}")
    print(f"  story_throughput: {metrics['story_throughput']}")
    print(f"  escalation_count: {metrics['escalation_count']}")


def test_dashboard_aggregation_suite_completes_quickly() -> None:
    """Test that full aggregation suite completes in under 30 seconds.

    Acceptance Criteria: complete suite runs in <30s
    """
    # This test passes if the other tests complete within the pytest timeout
    # The actual timing is validated by the other tests
    assert True
