#!/usr/bin/env python3
"""
pytest-benchmark tests for lib/ critical path functions.

Benchmarks merge_stories, validate_prd, decompose_story, and slice_prd
to establish performance baselines and detect regressions.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add lib/ to path so we can import the modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))

from merge_stories import (
    is_duplicate,
    overlap_ratio,
)
from prd_schema import validate_prd
from slice_prd import slice_prd


@pytest.fixture
def prd_data() -> dict[str, Any]:
    """Load the actual prd.json for realistic benchmarking."""
    prd_path = Path(__file__).parent.parent.parent / "prd.json"
    if not prd_path.exists():
        pytest.skip("prd.json not found")
    with open(prd_path, encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, dict)
        return data


@pytest.mark.benchmark
class TestLibBenchmarks:
    """Benchmark suite for lib/ critical path functions."""

    def test_validate_prd_baseline(self, benchmark: Any, prd_data: dict[str, Any]) -> None:
        """Benchmark validate_prd function."""
        result = benchmark(validate_prd, prd_data)
        # Should return a list (empty if valid)
        assert isinstance(result, list)

    def test_slice_prd_baseline(self, benchmark: Any, prd_data: dict[str, Any]) -> None:
        """Benchmark slice_prd function with batch_size=5."""
        result = benchmark(slice_prd, prd_data, 5)
        # Should return a dict with userStories
        assert isinstance(result, dict)
        assert "userStories" in result
        assert len(result["userStories"]) <= len(prd_data.get("userStories", []))

    def test_overlap_ratio_short_strings(self, benchmark: Any) -> None:
        """Benchmark overlap_ratio with short strings (common case)."""
        a = "Add pytest-benchmark for critical path functions"
        b = "Benchmark critical path functions with pytest"
        result = benchmark(overlap_ratio, a, b)
        assert isinstance(result, float)
        assert 0 <= result <= 1

    def test_overlap_ratio_long_strings(self, benchmark: Any) -> None:
        """Benchmark overlap_ratio with longer strings."""
        a = " ".join(["word"] * 50)
        b = " ".join(["word"] * 40 + ["different"] * 10)
        result = benchmark(overlap_ratio, a, b)
        assert isinstance(result, float)
        assert 0 <= result <= 1

    def test_is_duplicate_check(self, benchmark: Any, prd_data: dict[str, Any]) -> None:
        """Benchmark is_duplicate with real story titles from prd.json."""
        stories = prd_data.get("userStories", [])
        if not stories:
            pytest.skip("No stories in prd.json")

        # Use first few stories' titles
        titles = [s.get("title", "") for s in stories[:10] if "title" in s]
        if not titles:
            pytest.skip("No story titles found")

        candidate = titles[0]
        existing = titles[1:]

        def check_duplicate() -> bool:
            result_val = is_duplicate(candidate, existing, threshold=0.6)
            assert isinstance(result_val, bool)
            return result_val

        result = benchmark(check_duplicate)
        assert isinstance(result, bool)

    def test_slice_prd_large_batch(self, benchmark: Any, prd_data: dict[str, Any]) -> None:
        """Benchmark slice_prd with larger batch size."""
        result = benchmark(slice_prd, prd_data, 50)
        assert isinstance(result, dict)
        assert "userStories" in result

    def test_slice_prd_zero_batch(self, benchmark: Any, prd_data: dict[str, Any]) -> None:
        """Benchmark slice_prd with batch_size=0 (should return unchanged)."""
        result = benchmark(slice_prd, prd_data, 0)
        assert result == prd_data


@pytest.mark.benchmark
def test_validate_prd_empty_dict(benchmark: Any) -> None:
    """Benchmark validate_prd with empty dict (error case)."""
    empty: dict[str, Any] = {}
    result = benchmark(validate_prd, empty)
    assert isinstance(result, list)
    assert len(result) > 0  # Should have validation errors


@pytest.mark.benchmark
def test_slice_prd_empty_stories(benchmark: Any) -> None:
    """Benchmark slice_prd with empty stories list."""
    prd: dict[str, Any] = {"userStories": []}
    result = benchmark(slice_prd, prd, 5)
    assert result["userStories"] == []
