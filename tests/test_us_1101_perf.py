"""Performance test for Phase E batch story enrichment.

Verifies that batch enrichment (US-1101) reduces per-story Claude CLI overhead
by processing 5-10 stories in a single prompt vs one-at-a-time enrichment.

For 20 stories:
- Sequential: ~60s (3s startup per story × 20)
- Batch (4 calls): ~12s (3s base + processing time)
- Expected speedup: 5x improvement

Story: US-1245 - Performance Test for Batch Enrichment
Story reference: US-1101 - Phase E batch enrichment implementation
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Add lib/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.research.enrich_stories import (
    _enrich_batch,
    _enrich_one,
)

BASELINE_FILE = Path(".spiral") / "enrich_batch_baseline.json"


def _load_baseline() -> dict[str, Any] | None:
    """Load baseline metrics from .spiral/enrich_batch_baseline.json."""
    if not BASELINE_FILE.exists():
        return None
    try:
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
            if isinstance(data, dict):
                return data
            return None
    except (json.JSONDecodeError, OSError):
        return None


def _save_baseline(baseline: dict[str, Any]) -> None:
    """Save baseline metrics to .spiral/enrich_batch_baseline.json."""
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)


def _create_test_story(idx: int) -> dict[str, Any]:
    """Create a test story for enrichment."""
    return {
        "id": f"TEST-{idx}",
        "title": f"Test Feature {idx}",
        "priority": "medium",
        "description": f"Test story {idx} for batch enrichment performance.",
        "acceptanceCriteria": [f"Feature {idx} works"],
        "technicalNotes": [f"Note {idx}"],
        "dependencies": [],
        "estimatedComplexity": "medium",
        "_source": "research",
        "passes": False,
    }


def _create_mock_claude_response_enrich(story: dict[str, Any]) -> str:
    """Create a mock Claude response for enrichment action."""
    enriched = dict(story)
    enriched["technicalNotes"] = [
        f"File to edit: lib/feature_{story.get('id')}.py (implement_feature)",
        f"Test command: uv run pytest tests/test_{story.get('id')}.py -v",
    ]
    enriched["filesTouch"] = [f"lib/feature_{story.get('id')}.py", f"tests/test_{story.get('id')}.py"]
    enriched["_enriched"] = True
    return json.dumps({"action": "enrich", "story": enriched})


def _create_mock_batch_response(stories: list[dict[str, Any]]) -> str:
    """Create a mock Claude batch enrichment response."""
    batch_result: dict[str, list[dict[str, Any]]] = {"stories": []}
    for idx, story in enumerate(stories):
        enriched = dict(story)
        enriched["technicalNotes"] = [
            f"File to edit: lib/feature_{story.get('id')}.py (implement_feature)",
            f"Test command: uv run pytest tests/test_{story.get('id')}.py -v",
        ]
        enriched["filesTouch"] = [f"lib/feature_{story.get('id')}.py", f"tests/test_{story.get('id')}.py"]
        enriched["_enriched"] = True

        batch_result["stories"].append(
            {
                "original_index": idx,
                "action": "enrich",
                "results": [enriched],
            }
        )
    return json.dumps(batch_result)


@pytest.mark.us_1101
class TestBatchEnrichmentPerformance:
    """Performance benchmarks comparing batch vs sequential enrichment."""

    def test_batch_vs_sequential_enrichment(self) -> None:
        """
        Compare batch enrichment vs sequential enrichment for 20 stories.

        AC1: Batch enrichment achieves >=75% CLI call reduction vs sequential
        AC2: Baseline captured and available for regression detection
        AC3: Fail if call reduction efficiency degrades >20% from baseline
        """
        num_stories = 20
        batch_size = 5
        stories = [_create_test_story(i) for i in range(num_stories)]

        # Track Claude calls
        sequential_calls = [0]
        batch_calls = [0]

        def mock_claude_sequential(prompt: str, model: str) -> str:
            """Mock Claude for sequential enrichment with latency simulation."""
            sequential_calls[0] += 1
            # Simulate CLI startup overhead + processing: ~10ms per call
            time.sleep(0.01)
            # Extract story from prompt and return enriched version
            for story in stories:
                if story["title"] in prompt:
                    return _create_mock_claude_response_enrich(story)
            return json.dumps({"action": "enrich", "story": stories[0]})

        def mock_claude_batch(prompt: str, model: str) -> str:
            """Mock Claude for batch enrichment with latency simulation."""
            batch_calls[0] += 1
            # Simulate CLI startup overhead + batch processing: 10ms base + 2ms per story
            story_count = prompt.count('"title":')
            time.sleep(0.01 + 0.002 * story_count)
            return _create_mock_batch_response(stories[: min(batch_size, story_count)])

        # ─ Sequential enrichment: enrich N stories one-at-a-time ────────────────────
        sequential_start = time.perf_counter()
        sequential_calls[0] = 0

        with patch("lib.research.enrich_stories.call_claude", side_effect=mock_claude_sequential):
            for story in stories:
                result = _enrich_one(story, model="sonnet")
                assert len(result) == 1, f"Expected 1 result, got {len(result)}"
                assert result[0].get("_enriched") is True, "Story should be marked as enriched"

        sequential_time = time.perf_counter() - sequential_start
        sequential_call_count = sequential_calls[0]

        # ─ Batch enrichment: enrich N stories in batches ──────────────────────────────
        batch_start = time.perf_counter()
        batch_calls[0] = 0

        with patch("lib.research.enrich_stories.call_claude", side_effect=mock_claude_batch):
            # Simulate batching: split stories into chunks of batch_size
            for i in range(0, len(stories), batch_size):
                batch = stories[i : i + batch_size]
                result_dict = _enrich_batch(batch, model="sonnet")
                assert len(result_dict) == len(batch), f"Expected {len(batch)} results, got {len(result_dict)}"

        batch_time = time.perf_counter() - batch_start
        batch_call_count = batch_calls[0]

        # ─ Metrics ──────────────────────────────────────────────────────────────────
        speedup = sequential_time / batch_time if batch_time > 0 else 0
        call_reduction_pct = (1 - batch_call_count / sequential_call_count) * 100 if sequential_call_count > 0 else 0
        efficiency_score = call_reduction_pct  # Higher is better

        # AC1: Batch should achieve >=75% call reduction
        assert call_reduction_pct >= 75.0, (
            f"Expected >=75% reduction in Claude CLI calls, got {call_reduction_pct:.1f}%. "
            f"Sequential: {sequential_call_count} calls, Batch: {batch_call_count} calls"
        )

        # ─ Baseline comparison (AC2, AC3) ───────────────────────────────────────────
        baseline = _load_baseline()

        # Print benchmark results
        print()
        print("=" * 70)
        print("Phase E Batch Story Enrichment Performance Benchmark")
        print("=" * 70)
        print(f"Stories enriched:           {num_stories}")
        print(f"Batch size:                 {batch_size}")
        print(f"Sequential time:            {sequential_time:8.3f} s  ({sequential_call_count} Claude calls)")
        print(f"Batch time:                 {batch_time:8.3f} s  ({batch_call_count} Claude calls)")
        print(f"Speedup factor:             {speedup:8.2f}x")
        print(f"Claude call reduction:      {call_reduction_pct:8.1f}%")
        print(f"Efficiency score:           {efficiency_score:8.1f}%")

        # AC2: Capture baseline
        if baseline is not None:
            baseline_efficiency = baseline.get("efficiency_score", 0)
            if baseline_efficiency > 0:
                degradation_pct = ((baseline_efficiency - efficiency_score) / baseline_efficiency * 100)
            else:
                degradation_pct = 0.0
            print(f"Previous baseline:          {baseline_efficiency:8.1f}%")
            print(f"Degradation from baseline:  {degradation_pct:8.2f}%")
        print("=" * 70)

        # AC3: Fail if efficiency degrades >20% from baseline (i.e., call reduction drops too much)
        if baseline is not None:
            baseline_efficiency = baseline.get("efficiency_score", 0)
            if baseline_efficiency > 0:
                degradation_pct = ((baseline_efficiency - efficiency_score) / baseline_efficiency) * 100
                assert degradation_pct <= 20.0, (
                    f"Call reduction efficiency degraded {degradation_pct:.2f}% from baseline "
                    f"{baseline_efficiency:.1f}%. Exceeded 20% threshold. Current: {efficiency_score:.1f}%"
                )

        # Save current baseline for next run
        _save_baseline(
            {
                "efficiency_score": efficiency_score,
                "call_reduction_pct": call_reduction_pct,
                "speedup_factor": speedup,
                "batch_time": batch_time,
                "sequential_time": sequential_time,
                "num_stories": num_stories,
                "batch_size": batch_size,
            }
        )

    def test_cli_call_reduction_proportion(self) -> None:
        """
        Verify that batch enrichment reduces Claude CLI calls proportionally to batch size.

        For N=20 stories with batch_size=5: expect 4 calls (vs 20 sequential calls).
        For N=20 stories with batch_size=10: expect 2 calls (vs 20 sequential calls).

        AC: Call reduction = (N - ceil(N/batch_size)) / N >= 80% for batch_size=5.
        """
        test_cases = [
            (10, 5, 2),   # 10 stories, batch 5 = 2 calls (vs 10)
            (20, 5, 4),   # 20 stories, batch 5 = 4 calls (vs 20)
            (20, 10, 2),  # 20 stories, batch 10 = 2 calls (vs 20)
            (15, 3, 5),   # 15 stories, batch 3 = 5 calls (vs 15)
        ]

        for num_stories, batch_size, expected_batch_calls in test_cases:
            stories = [_create_test_story(i) for i in range(num_stories)]
            call_count = [0]

            def mock_batch_call(prompt: str, model: str) -> str:
                """Mock batch Claude call."""
                call_count[0] += 1
                story_count = min(batch_size, prompt.count('"title":'))
                return _create_mock_batch_response(stories[: story_count])

            with patch("lib.research.enrich_stories.call_claude", side_effect=mock_batch_call):
                # Simulate batching
                for i in range(0, len(stories), batch_size):
                    batch = stories[i : i + batch_size]
                    result = _enrich_batch(batch, model="sonnet")
                    assert len(result) > 0, f"Batch enrichment failed for batch starting at {i}"

            call_reduction_pct = (1 - call_count[0] / num_stories) * 100
            assert call_count[0] == expected_batch_calls, (
                f"For {num_stories} stories with batch_size={batch_size}: "
                f"expected {expected_batch_calls} calls, got {call_count[0]} calls. "
                f"Reduction: {call_reduction_pct:.1f}%"
            )

            msg = f"✓ {num_stories} stories, batch {batch_size}: {call_count[0]} calls "
            msg += f"(reduction: {call_reduction_pct:.1f}%)"
            print(msg)
