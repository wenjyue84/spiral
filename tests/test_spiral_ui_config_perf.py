#!/usr/bin/env python3
"""test_spiral_ui_config_perf.py — Performance benchmark for POST /api/config endpoint.

Tests measure endpoint latency and ensure it responds within 200ms baseline (US-1311).
Tests are discoverable via: pytest tests/test_spiral_ui_config_perf.py -k us_1214 -v
"""

import statistics
import time
from pathlib import Path
from typing import Any, Generator

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from lib.dashboard.api import app


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient for the dashboard API."""
    return TestClient(app)


@pytest.fixture
def mock_spiral_dir(tmp_path: Path, monkeypatch: MonkeyPatch) -> Generator[Path, None, None]:
    """Create a temporary .spiral directory and change into it."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    yield spiral_dir


@pytest.mark.us_1214
def test_config_post_latency_us_1214(client: TestClient, mock_spiral_dir: Path) -> None:
    """Performance benchmark: POST /api/config responds within 200ms baseline.

    Measures wall-clock latency over 50 iterations and asserts:
    - All requests return HTTP 200
    - p50 latency is recorded
    - p99 latency is < 200ms (0.2 seconds)

    Story: US-1311
    Acceptance criteria:
      ✓ Test records p50 and p99 latency and asserts p99 < 200ms
      ✓ Test fails if POST /api/config returns a non-200 HTTP status
    """
    payload: dict[str, Any] = {
        "SPIRAL_MAX_PENDING": 5,
        "SPIRAL_MODEL_ROUTING": "auto",
        "SPIRAL_VALIDATE_CMD": "pytest tests/",
    }
    num_iterations = 50
    latencies: list[float] = []

    # Warm-up request (not timed)
    response = client.post("/api/config", json=payload)
    assert response.status_code == 200, f"Warm-up request failed: {response.status_code}"

    # Measure 50 POST requests
    for _ in range(num_iterations):
        start = time.perf_counter()
        response = client.post("/api/config", json=payload)
        end = time.perf_counter()

        # Assert all requests return 200
        assert response.status_code == 200, f"Request failed with status {response.status_code}: {response.text}"

        # Record latency in seconds
        latency_seconds = end - start
        latencies.append(latency_seconds)

    # Calculate percentiles using statistics.quantiles
    # quantiles(n=100) gives us 99 cut points, so [98] gives the 99th percentile
    percentiles = statistics.quantiles(latencies, n=100)
    p50_idx = 49  # 50th percentile is at index 49 (0-indexed)
    p99_idx = 98  # 99th percentile is at index 98 (0-indexed)

    p50_seconds = percentiles[p50_idx]
    p99_seconds = percentiles[p99_idx]

    # Convert to milliseconds for reporting
    p50_ms = p50_seconds * 1000
    p99_ms = p99_seconds * 1000

    # Report latencies
    print("\nPOST /api/config latency baseline (50 iterations):")
    print(f"  p50: {p50_ms:.2f}ms")
    print(f"  p99: {p99_ms:.2f}ms")
    print(f"  min: {min(latencies) * 1000:.2f}ms")
    print(f"  max: {max(latencies) * 1000:.2f}ms")

    # Assert p99 < 200ms
    assert p99_seconds < 0.2, f"p99 latency {p99_ms:.2f}ms exceeds 200ms baseline"
