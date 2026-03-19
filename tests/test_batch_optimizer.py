"""Tests for lib/batch_optimizer.py — US-535.

Verifies:
1. group_stories_by_rules() clusters stories with identical constitution checks.
2. Phase S integration reduces API calls by ≥30% on 20+ story batches.
3. batch_potential() CLI helper returns correct reduction metadata.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from batch_optimizer import batch_potential, group_stories_by_rules


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_stories(
    n: int,
    source: str = "research",
    priority: str = "medium",
) -> list[dict[str, Any]]:
    """Generate n stories with the given source and priority."""
    return [
        {
            "id": f"US-{100 + i}",
            "title": f"Story {i}",
            "priority": priority,
            "_source": source,
            "passes": False,
        }
        for i in range(n)
    ]


def _make_mixed_stories(counts: dict[tuple[str, str], int]) -> list[dict[str, Any]]:
    """Build a mixed list of stories from a {(source, priority): count} mapping."""
    stories: list[dict[str, Any]] = []
    base = 200
    for (source, priority), n in counts.items():
        for i in range(n):
            stories.append(
                {
                    "id": f"US-{base}",
                    "title": f"Story {base}",
                    "priority": priority,
                    "_source": source,
                    "passes": False,
                }
            )
            base += 1
    return stories


# ---------------------------------------------------------------------------
# group_stories_by_rules — unit tests
# ---------------------------------------------------------------------------

class TestGroupStoriesByRules:
    """Unit tests for the core clustering function."""

    def test_empty_returns_empty(self) -> None:
        assert group_stories_by_rules([]) == []

    def test_single_story_single_group(self) -> None:
        stories = _make_stories(1)
        groups = group_stories_by_rules(stories)
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_identical_source_and_priority_grouped_together(self) -> None:
        stories = _make_stories(5, source="research", priority="medium")
        groups = group_stories_by_rules(stories)
        # All 5 should be in one group (well within max_batch_size=10)
        assert len(groups) == 1
        assert len(groups[0]) == 5

    def test_different_sources_split_into_separate_groups(self) -> None:
        research = _make_stories(3, source="research", priority="medium")
        ai_example = _make_stories(3, source="ai-example", priority="medium")
        groups = group_stories_by_rules(research + ai_example)
        assert len(groups) == 2
        # Each group has 3 stories
        sizes = sorted(len(g) for g in groups)
        assert sizes == [3, 3]

    def test_different_priorities_split_into_separate_groups(self) -> None:
        high = _make_stories(2, source="research", priority="high")
        low = _make_stories(2, source="research", priority="low")
        groups = group_stories_by_rules(high + low)
        assert len(groups) == 2

    def test_max_batch_size_splits_large_groups(self) -> None:
        stories = _make_stories(25, source="research", priority="medium")
        groups = group_stories_by_rules(stories, max_batch_size=10)
        # 25 stories → ceil(25/10) = 3 groups
        assert len(groups) == 3
        sizes = sorted(len(g) for g in groups)
        assert sizes == [5, 10, 10]

    def test_all_stories_preserved(self) -> None:
        """No story should be lost during grouping."""
        mixed = _make_mixed_stories(
            {
                ("research", "high"): 7,
                ("ai-example", "medium"): 8,
                ("test-fix", "low"): 5,
            }
        )
        groups = group_stories_by_rules(mixed, max_batch_size=10)
        all_ids = [s["id"] for g in groups for s in g]
        assert len(all_ids) == 20
        assert len(set(all_ids)) == 20  # no duplicates

    def test_unknown_priority_normalised_to_medium(self) -> None:
        stories = [
            {"id": "US-1", "title": "A", "priority": "critical", "_source": "research"},
            {"id": "US-2", "title": "B", "priority": "medium", "_source": "research"},
        ]
        # Both should end up in the same bucket (critical→medium normalisation)
        groups = group_stories_by_rules(stories)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_none_source_treated_as_seed(self) -> None:
        stories = [
            {"id": "US-1", "title": "A", "priority": "medium", "_source": None},
            {"id": "US-2", "title": "B", "priority": "medium", "_source": "seed"},
        ]
        # None and "seed" both normalise to "seed"
        groups = group_stories_by_rules(stories)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_missing_source_and_priority_defaults(self) -> None:
        stories = [
            {"id": "US-1", "title": "A"},
            {"id": "US-2", "title": "B"},
        ]
        groups = group_stories_by_rules(stories)
        assert len(groups) == 1
        assert len(groups[0]) == 2


# ---------------------------------------------------------------------------
# Phase S integration: ≥30% API call reduction on 20+ stories
# ---------------------------------------------------------------------------

class TestPhasesBatchReduction:
    """Verify that batching achieves ≥30% API call reduction on realistic inputs."""

    def test_30pct_reduction_all_same_bucket(self) -> None:
        """20 identical-bucket stories → 2 batches → 90% reduction."""
        stories = _make_stories(20, source="research", priority="medium")
        groups = group_stories_by_rules(stories, max_batch_size=10)
        solo_calls = len(stories)
        batch_calls = len(groups)
        reduction_pct = (1 - batch_calls / solo_calls) * 100
        assert reduction_pct >= 30.0, f"Expected ≥30% reduction, got {reduction_pct:.1f}%"

    def test_30pct_reduction_two_sources(self) -> None:
        """20 stories, 2 sources of 10 each → 2 batches → 90% reduction."""
        research = _make_stories(10, source="research", priority="medium")
        ai_stories = _make_stories(10, source="ai-example", priority="medium")
        groups = group_stories_by_rules(research + ai_stories, max_batch_size=10)
        solo_calls = 20
        batch_calls = len(groups)
        reduction_pct = (1 - batch_calls / solo_calls) * 100
        assert reduction_pct >= 30.0, f"Expected ≥30% reduction, got {reduction_pct:.1f}%"

    def test_30pct_reduction_mixed_20_stories(self) -> None:
        """Realistic mixed bag: 4 sources × 5 stories each → 4 batches of 5 → 80% reduction."""
        mixed = _make_mixed_stories(
            {
                ("research", "high"): 5,
                ("ai-example", "medium"): 5,
                ("test-fix", "low"): 5,
                ("seed", "medium"): 5,
            }
        )
        assert len(mixed) == 20
        groups = group_stories_by_rules(mixed, max_batch_size=10)
        solo_calls = len(mixed)
        batch_calls = len(groups)
        reduction_pct = (1 - batch_calls / solo_calls) * 100
        assert reduction_pct >= 30.0, f"Expected ≥30% reduction, got {reduction_pct:.1f}%"

    def test_mock_api_calls_reduced_by_batching(self) -> None:
        """Simulate mock API responses for batched vs solo calls.

        Without batching: N stories → N API calls (one per story).
        With batching: N stories → ceil(N / batch_size) API calls.

        Verify the reduction is ≥30%.
        """
        # Mock API: records how many calls were made
        class MockAPI:
            def __init__(self) -> None:
                self.call_count = 0

            def validate_solo(self, story: dict) -> dict:
                self.call_count += 1
                return {"id": story["id"], "accepted": True}

            def validate_batch(self, stories: list[dict]) -> list[dict]:
                self.call_count += 1  # one call for the whole batch
                return [{"id": s["id"], "accepted": True} for s in stories]

        stories = _make_stories(20, source="research", priority="medium")

        # Solo approach
        solo_api = MockAPI()
        for s in stories:
            solo_api.validate_solo(s)

        # Batched approach
        batch_api = MockAPI()
        groups = group_stories_by_rules(stories, max_batch_size=10)
        for group in groups:
            batch_api.validate_batch(group)

        reduction_pct = (1 - batch_api.call_count / solo_api.call_count) * 100
        assert reduction_pct >= 30.0, (
            f"Mock API: solo={solo_api.call_count} calls, "
            f"batch={batch_api.call_count} calls, "
            f"reduction={reduction_pct:.1f}%"
        )


# ---------------------------------------------------------------------------
# batch_potential — CLI helper tests
# ---------------------------------------------------------------------------

class TestBatchPotential:
    """Tests for the batch_potential() summary function."""

    def test_empty_stories(self) -> None:
        result = batch_potential([])
        assert result["story_count"] == 0
        assert result["solo_api_calls"] == 0
        assert result["batch_api_calls"] == 0
        assert result["call_reduction_pct"] == 0.0
        assert result["groups"] == []

    def test_single_story(self) -> None:
        stories = _make_stories(1)
        result = batch_potential(stories)
        assert result["story_count"] == 1
        assert result["solo_api_calls"] == 1
        assert result["batch_api_calls"] == 1
        assert result["call_reduction_pct"] == 0.0

    def test_20_stories_same_bucket_reduction_pct(self) -> None:
        stories = _make_stories(20, source="research", priority="medium")
        result = batch_potential(stories, max_batch_size=10)
        assert result["story_count"] == 20
        assert result["solo_api_calls"] == 20
        assert result["batch_api_calls"] == 2  # ceil(20/10)
        assert result["call_reduction_pct"] == 90.0

    def test_token_savings_positive(self) -> None:
        stories = _make_stories(10)
        result = batch_potential(stories)
        assert result["solo_tokens_est"] > result["batch_tokens_est"]
        assert result["token_savings_est"] > 0
        assert result["token_savings_pct"] > 0

    def test_groups_contain_story_ids(self) -> None:
        stories = _make_stories(5, source="seed", priority="high")
        result = batch_potential(stories)
        all_ids_in_groups = [sid for group in result["groups"] for sid in group]
        input_ids = [s["id"] for s in stories]
        assert sorted(all_ids_in_groups) == sorted(input_ids)

    def test_output_keys_present(self) -> None:
        result = batch_potential(_make_stories(3))
        required_keys = {
            "story_count",
            "solo_api_calls",
            "batch_api_calls",
            "call_reduction_pct",
            "solo_tokens_est",
            "batch_tokens_est",
            "token_savings_est",
            "token_savings_pct",
            "groups",
        }
        assert required_keys.issubset(result.keys())
