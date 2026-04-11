#!/usr/bin/env python3
"""test_dashboard_profile.py — Integration tests for /profile endpoint."""

import json
import os
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app


def test_profile_endpoint_returns_200() -> None:
    """Test /profile endpoint returns HTTP 200."""
    client = TestClient(app)
    response = client.get("/profile")
    assert response.status_code == 200


def test_profile_returns_correct_json_structure() -> None:
    """Test /profile returns JSON with correct keys."""
    client = TestClient(app)
    response = client.get("/profile")
    data = response.json()

    assert "mean_phase_durations" in data
    assert "slowest_stories" in data
    assert "escalation_frequency" in data


def test_profile_mean_phase_durations_has_required_keys() -> None:
    """Test mean_phase_durations has decompose_secs, impl_secs, verify_secs."""
    client = TestClient(app)
    response = client.get("/profile")
    data = response.json()

    mean_phases = data["mean_phase_durations"]
    assert "decompose_secs" in mean_phases
    assert "impl_secs" in mean_phases
    assert "verify_secs" in mean_phases

    # Verify they are numeric
    assert isinstance(mean_phases["decompose_secs"], (int, float))
    assert isinstance(mean_phases["impl_secs"], (int, float))
    assert isinstance(mean_phases["verify_secs"], (int, float))


# ---------------------------------------------------------------------------
# Performance Tests for US-522
# ---------------------------------------------------------------------------


def _load_baseline(metric_name: str) -> float | None:
    """Load baseline metrics from .spiral/us_522_baseline.json, or None if not found."""
    baseline_file = ".spiral/us_522_baseline.json"
    if not os.path.exists(baseline_file):
        return None
    try:
        with open(baseline_file, encoding="utf-8") as f:
            data: dict[str, float] = json.load(f)
            return data.get(metric_name)
    except (json.JSONDecodeError, OSError):
        return None


def _save_baseline(metric_name: str, value: float) -> None:
    """Save baseline metrics to .spiral/us_522_baseline.json."""
    baseline_file = ".spiral/us_522_baseline.json"
    os.makedirs(".spiral", exist_ok=True)

    data: dict[str, float] = {}
    if os.path.exists(baseline_file):
        try:
            with open(baseline_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

    data[metric_name] = value

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@pytest.fixture
def large_results_tsv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Generator[Path, None, None]:
    """Fixture that creates a large results.tsv with 200 realistic rows."""
    # Create a temporary results.tsv
    results_file = tmp_path / "results.tsv"

    # Write TSV header
    with open(results_file, "w", encoding="utf-8") as f:
        f.write("story_id\tdecompose_secs\timpl_secs\tverify_secs\tretry_escalation_count\n")

        # Generate 200 rows with realistic data
        for i in range(200):
            story_id = f"US-{1000 + i}"
            decompose = 10.5 + (i % 5) * 2.3
            impl = 45.2 + (i % 7) * 3.1
            verify = 8.1 + (i % 3) * 1.5
            escalation = i % 10

            f.write(f"{story_id}\t{decompose}\t{impl}\t{verify}\t{escalation}\n")

    # Point the app to use our temporary results.tsv
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    results_dest = spiral_dir / "results.tsv"
    results_dest.write_text(results_file.read_text())

    # Temporarily override the path in the app
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        yield results_dest
    finally:
        os.chdir(original_cwd)


@pytest.mark.us_522
def test_us_522_profile_endpoint_performance_100_rows(tmp_path: Path) -> None:
    """Measure /profile endpoint response time with 100 rows. Baseline: ~5ms."""
    # Create results.tsv with 100 rows
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    results_file = spiral_dir / "results.tsv"

    with open(results_file, "w", encoding="utf-8") as f:
        f.write("story_id\tdecompose_secs\timpl_secs\tverify_secs\tretry_escalation_count\n")
        for i in range(100):
            story_id = f"US-{1000 + i}"
            decompose = 10.5 + (i % 5) * 2.3
            impl = 45.2 + (i % 7) * 3.1
            verify = 8.1 + (i % 3) * 1.5
            escalation = i % 10
            f.write(f"{story_id}\t{decompose}\t{impl}\t{verify}\t{escalation}\n")

    # Change to temp directory so app reads our results.tsv
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        client = TestClient(app)

        # Measure response time
        start = time.perf_counter()
        response = client.get("/profile")
        elapsed = time.perf_counter() - start

        # Verify endpoint works
        assert response.status_code == 200
        data = response.json()
        assert "mean_phase_durations" in data
        assert "slowest_stories" in data
        assert "escalation_frequency" in data

        # Return to original cwd before checking baseline
        os.chdir(original_cwd)

        # Check against baseline (saved in project root)
        baseline = _load_baseline("profile_endpoint_100_sec")
        if baseline is not None:
            max_allowed = baseline * 1.20  # 20% degradation threshold
            assert elapsed <= max_allowed, (
                f"Profile endpoint 100 rows: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("profile_endpoint_100_sec", elapsed)

    finally:
        if os.getcwd() != original_cwd:
            os.chdir(original_cwd)


@pytest.mark.us_522
def test_us_522_profile_endpoint_performance_200_rows(tmp_path: Path) -> None:
    """Measure /profile endpoint response time with 200 rows. Baseline: ~10ms."""
    # Create results.tsv with 200 rows
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    results_file = spiral_dir / "results.tsv"

    with open(results_file, "w", encoding="utf-8") as f:
        f.write("story_id\tdecompose_secs\timpl_secs\tverify_secs\tretry_escalation_count\n")
        for i in range(200):
            story_id = f"US-{1000 + i}"
            decompose = 10.5 + (i % 5) * 2.3
            impl = 45.2 + (i % 7) * 3.1
            verify = 8.1 + (i % 3) * 1.5
            escalation = i % 10
            f.write(f"{story_id}\t{decompose}\t{impl}\t{verify}\t{escalation}\n")

    # Change to temp directory so app reads our results.tsv
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        client = TestClient(app)

        # Measure response time
        start = time.perf_counter()
        response = client.get("/profile")
        elapsed = time.perf_counter() - start

        # Verify endpoint works
        assert response.status_code == 200
        data = response.json()
        assert len(data["slowest_stories"]) <= 5
        assert all("story_id" in s and "total_duration" in s for s in data["slowest_stories"])

        # Return to original cwd before checking baseline
        os.chdir(original_cwd)

        # Check against baseline (saved in project root)
        baseline = _load_baseline("profile_endpoint_200_sec")
        if baseline is not None:
            max_allowed = baseline * 1.20  # 20% degradation threshold
            assert elapsed <= max_allowed, (
                f"Profile endpoint 200 rows: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("profile_endpoint_200_sec", elapsed)

    finally:
        if os.getcwd() != original_cwd:
            os.chdir(original_cwd)


@pytest.mark.us_522
def test_us_522_profile_baseline_capture() -> None:
    """Ensure baseline metrics are recorded after first run."""
    baseline_file = ".spiral/us_522_baseline.json"
    os.makedirs(".spiral", exist_ok=True)

    # After running the tests above, baselines should exist or be created
    # This test confirms the mechanism works
    _save_baseline("test_metric", 0.005)
    assert os.path.exists(baseline_file)

    with open(baseline_file, encoding="utf-8") as f:
        data = json.load(f)
        assert "test_metric" in data
        assert data["test_metric"] == 0.005
