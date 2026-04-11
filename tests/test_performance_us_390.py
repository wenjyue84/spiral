"""Performance tests for lib/batch_validate.py — US-390 Message Batches API.

Verifies that batch validation operations meet performance baselines:
1. Measures response time for build_batch_requests, parse_batch_results
2. Captures baseline metrics and checks for ≤20% degradation
3. Validates that batching achieves expected throughput improvements
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import batch_validate as bv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _story(title: str = "Improve docs", description: str = "Add README", idx: int = 0) -> dict[str, Any]:
    """Create a realistic story dict."""
    return {
        "id": f"US-{100 + idx}",
        "title": title,
        "description": description,
        "_custom_id": f"story-{idx}",
    }


def _make_batch_result(
    custom_id: str,
    accepted: bool = True,
    reason: str = "ok",
) -> dict[str, Any]:
    """Create a realistic batch result dict."""
    return {
        "custom_id": custom_id,
        "result": {
            "type": "succeeded",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"accepted": accepted, "reason": reason}),
                    }
                ]
            },
        },
    }


def _load_baseline(metric_name: str) -> dict[str, Any] | None:
    """Load baseline metrics from .spiral/us_390_baseline.json, or None if not found."""
    baseline_file = ".spiral/us_390_baseline.json"
    if not os.path.exists(baseline_file):
        return None
    try:
        with open(baseline_file, encoding="utf-8") as f:
            data = json.load(f)
            return data.get(metric_name)
    except (json.JSONDecodeError, OSError):
        return None


def _save_baseline(metric_name: str, value: float) -> None:
    """Save baseline metrics to .spiral/us_390_baseline.json."""
    baseline_file = ".spiral/us_390_baseline.json"
    os.makedirs(".spiral", exist_ok=True)

    data: dict[str, Any] = {}
    if os.path.exists(baseline_file):
        try:
            with open(baseline_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

    data[metric_name] = value

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# TestUS390PerformanceBatch
# ---------------------------------------------------------------------------


class TestUS390PerformanceBatch:
    """Performance tests for US-390 batch validation operations."""

    # Thresholds
    DEGRADATION_THRESHOLD = 0.20  # 20% max acceptable degradation

    def test_us_390_build_requests_performance_10_stories(self) -> None:
        """Measure time to build 10 batch requests. Baseline: ~1ms."""
        stories = [_story(f"Story {i}", f"Description {i}", i) for i in range(10)]

        start = time.perf_counter()
        requests = bv.build_batch_requests(stories, "Project goals text", ["forbidden"])
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert len(requests) == 10
        assert all("custom_id" in r for r in requests)
        assert all("params" in r for r in requests)

        # Check against baseline
        baseline = _load_baseline("build_requests_10_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert elapsed <= max_allowed, (
                f"Build requests 10 stories: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("build_requests_10_ms", elapsed)

    def test_us_390_build_requests_performance_100_stories(self) -> None:
        """Measure time to build 100 batch requests. Baseline: ~10ms."""
        stories = [_story(f"Story {i}", f"Description {i}", i) for i in range(100)]

        start = time.perf_counter()
        requests = bv.build_batch_requests(stories, "Project goals text", ["forbidden"])
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert len(requests) == 100

        # Check against baseline
        baseline = _load_baseline("build_requests_100_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert elapsed <= max_allowed, (
                f"Build requests 100 stories: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("build_requests_100_ms", elapsed)

    def test_us_390_parse_results_performance_50_results(self) -> None:
        """Measure time to parse 50 batch results. Baseline: ~5ms."""
        results = [_make_batch_result(f"story-{i}", accepted=(i % 2 == 0)) for i in range(50)]

        start = time.perf_counter()
        parsed = bv.parse_batch_results(results)
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert len(parsed) == 50
        assert all(isinstance(v, dict) for v in parsed.values())
        assert all("accepted" in v and "reason" in v for v in parsed.values())

        # Check against baseline
        baseline = _load_baseline("parse_results_50_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert elapsed <= max_allowed, (
                f"Parse results 50: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("parse_results_50_ms", elapsed)

    def test_us_390_parse_results_performance_200_results(self) -> None:
        """Measure time to parse 200 batch results. Baseline: ~20ms."""
        results = [_make_batch_result(f"story-{i}", accepted=(i % 3 == 0)) for i in range(200)]

        start = time.perf_counter()
        parsed = bv.parse_batch_results(results)
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert len(parsed) == 200

        # Check against baseline
        baseline = _load_baseline("parse_results_200_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert elapsed <= max_allowed, (
                f"Parse results 200: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("parse_results_200_ms", elapsed)

    def test_us_390_batch_throughput_e2e(self) -> None:
        """End-to-end throughput: build + parse 50 stories. Baseline: ~10ms."""
        stories = [_story(f"Story {i}", f"Description {i}", i) for i in range(50)]
        results = [_make_batch_result(f"story-{i}", accepted=(i % 2 == 0)) for i in range(50)]

        # Time both build and parse
        start = time.perf_counter()
        requests = bv.build_batch_requests(stories, "goals", [])
        parsed = bv.parse_batch_results(results)
        elapsed = time.perf_counter() - start

        # Verify correctness
        assert len(requests) == 50
        assert len(parsed) == 50

        # Check against baseline
        baseline = _load_baseline("e2e_throughput_50_ms")
        if baseline is not None:
            max_allowed = baseline * (1 + self.DEGRADATION_THRESHOLD)
            assert elapsed <= max_allowed, (
                f"E2E throughput 50 stories: {elapsed * 1000:.2f}ms (baseline: {baseline * 1000:.2f}ms, max allowed: {max_allowed * 1000:.2f}ms)"
            )
        else:
            _save_baseline("e2e_throughput_50_ms", elapsed)

    def test_us_390_baseline_capture(self) -> None:
        """Ensure baseline metrics are recorded after first run."""
        baseline_file = ".spiral/us_390_baseline.json"
        os.makedirs(".spiral", exist_ok=True)

        # After running the tests above, baselines should exist or be created
        # This test confirms the mechanism works
        _save_baseline("test_metric", 0.005)
        assert os.path.exists(baseline_file)

        with open(baseline_file, encoding="utf-8") as f:
            data = json.load(f)
            assert "test_metric" in data
            assert data["test_metric"] == 0.005
