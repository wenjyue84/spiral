#!/usr/bin/env python3
"""test_perf_us_522_profile_endpoint.py — Performance benchmarks for /profile endpoint.

Tests measure endpoint latency and detect performance regressions.
Tests are discoverable via: pytest tests/ -k us_522 -v
"""

import csv
import shutil
import time
from pathlib import Path
from typing import Any, Generator

import pytest

from lib.dashboard.api import app

# Baseline latency in milliseconds (measured on small dataset)
# Should not exceed 20% increase when dataset size grows 10x
BASELINE_LATENCY_MS = 50.0


@pytest.fixture
def synthetic_results_tsv_100rows(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a synthetic results.tsv with 100 rows for baseline testing."""
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

        for i in range(100):
            row = {
                "story_id": f"US-{100 + i}",
                "spiral_iter": i % 10,
                "ralph_iter": 0,
                "attempt": 1,
                "status": "passed" if i % 2 == 0 else "failed",
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

        for i in range(1000):
            row = {
                "story_id": f"US-{1000 + i}",
                "spiral_iter": i % 10,
                "ralph_iter": 0,
                "attempt": 1,
                "status": "passed" if i % 2 == 0 else "failed",
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


@pytest.mark.us_522
def test_profile_endpoint_baseline() -> None:
    """Test baseline /profile endpoint latency on real results.tsv.

    Measures wall time for /profile endpoint and prints baseline.
    Acceptance Criteria: endpoint responds and latency is under 1s
    """
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Measure /profile endpoint latency against the real results.tsv
    start = time.perf_counter()
    response = client.get("/profile")
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Verify response is valid
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data: dict[str, Any] = response.json()

    # Print baseline for reference
    print(f"\n[BASELINE] /profile endpoint latency: {elapsed_ms:.2f} ms")
    print(f"  mean_phase_durations: {data.get('mean_phase_durations')}")
    print(f"  slowest_stories count: {len(data.get('slowest_stories', []))}")
    print(f"  escalation_frequency count: {len(data.get('escalation_frequency', {}))}")

    # Assert baseline is within reasonable bounds
    assert elapsed_ms < 1000, f"Baseline latency {elapsed_ms:.2f}ms exceeded 1s threshold"


@pytest.mark.us_522
def test_profile_endpoint_degradation_with_synthetic_data(
    synthetic_results_tsv_100rows: Path,
    synthetic_results_tsv_1000rows: Path,
) -> None:
    """Test /profile endpoint degradation on synthetic datasets.

    Verifies that latency increase is under 20% when data volume increases 10x.
    Acceptance Criteria: fails if latency >20% slower on 1000-row dataset
    """
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Back up the real results.tsv
    results_path = Path(".spiral/results.tsv")
    backup_path = Path(".spiral/results.tsv.bak")
    if results_path.exists():
        shutil.copy2(results_path, backup_path)

    try:
        # Measure baseline (100 rows)
        shutil.copy2(synthetic_results_tsv_100rows, results_path)
        start_baseline = time.perf_counter()
        response_baseline = client.get("/profile")
        baseline_latency_ms = (time.perf_counter() - start_baseline) * 1000
        assert response_baseline.status_code == 200

        # Measure 10x dataset (1000 rows)
        shutil.copy2(synthetic_results_tsv_1000rows, results_path)
        start_10x = time.perf_counter()
        response_10x = client.get("/profile")
        threshold_latency_ms = (time.perf_counter() - start_10x) * 1000
        assert response_10x.status_code == 200

        # Calculate degradation percentage
        if baseline_latency_ms > 0:
            degradation_pct = (threshold_latency_ms - baseline_latency_ms) / baseline_latency_ms * 100
        else:
            degradation_pct = 0

        print("\n[THRESHOLD] /profile endpoint latency comparison:")
        print(f"  Baseline (100 rows):  {baseline_latency_ms:.2f} ms")
        print(f"  Threshold (1000 rows): {threshold_latency_ms:.2f} ms")
        print(f"  Degradation: {degradation_pct:.1f}%")

        # FAIL if degradation exceeds 20%
        assert degradation_pct <= 20.0, f"Endpoint latency degraded {degradation_pct:.1f}% (exceeds 20% threshold)"

    finally:
        # Restore the original results.tsv
        if backup_path.exists():
            shutil.copy2(backup_path, results_path)
            backup_path.unlink()


@pytest.mark.us_522
def test_profile_endpoint_response_structure() -> None:
    """Test that /profile endpoint returns correctly structured response.

    Acceptance Criteria: response includes mean_phase_durations, slowest_stories, escalation_frequency
    """
    from fastapi.testclient import TestClient

    client = TestClient(app)

    response = client.get("/profile")
    assert response.status_code == 200

    data: dict[str, Any] = response.json()

    # Verify required top-level keys
    assert "mean_phase_durations" in data, "Missing mean_phase_durations"
    assert "slowest_stories" in data, "Missing slowest_stories"
    assert "escalation_frequency" in data, "Missing escalation_frequency"

    # Verify mean_phase_durations structure
    mean_phases = data["mean_phase_durations"]
    assert isinstance(mean_phases, dict), "mean_phase_durations must be dict"
    assert "decompose_secs" in mean_phases
    assert "impl_secs" in mean_phases
    assert "verify_secs" in mean_phases
    assert isinstance(mean_phases["decompose_secs"], (int, float))
    assert isinstance(mean_phases["impl_secs"], (int, float))
    assert isinstance(mean_phases["verify_secs"], (int, float))
    assert all(v >= 0 for v in mean_phases.values()), "Phase durations must be non-negative"

    # Verify slowest_stories structure
    slowest = data["slowest_stories"]
    assert isinstance(slowest, list), "slowest_stories must be list"
    assert len(slowest) <= 5, "slowest_stories should have at most 5 entries"
    for story in slowest:
        assert "story_id" in story, "slowest story missing story_id"
        assert "total_duration" in story, "slowest story missing total_duration"
        assert isinstance(story["story_id"], str)
        assert isinstance(story["total_duration"], (int, float))
        assert story["total_duration"] >= 0

    # Verify escalation_frequency structure (can be empty if no escalations in data)
    escalation = data["escalation_frequency"]
    assert isinstance(escalation, dict), "escalation_frequency must be dict"
    for story_id, count in escalation.items():
        assert isinstance(story_id, str)
        assert isinstance(count, int)
        assert count > 0, "Escalation count must be positive"

    print("\n[RESPONSE STRUCTURE]")
    print(f"  mean_decompose: {mean_phases['decompose_secs']:.2f}s")
    print(f"  mean_impl: {mean_phases['impl_secs']:.2f}s")
    print(f"  mean_verify: {mean_phases['verify_secs']:.2f}s")
    print(f"  slowest_stories: {len(slowest)} entries")
    print(f"  escalation_frequency: {len(escalation)} stories with escalations")
