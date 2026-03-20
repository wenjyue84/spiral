"""Tests for lib/worker_balancer.py — worker load balancer (US-562)."""

from __future__ import annotations

import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from story_complexity import compute_story_complexity
from worker_balancer import assign_stories_to_workers

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_story(
    sid: str,
    description: str = "",
    dependencies: list[str] | None = None,
    files_touch: list[str] | None = None,
    retry_num: int = 0,
) -> dict:
    story: dict = {
        "id": sid,
        "title": f"Test story {sid}",
        "description": description,
        "dependencies": dependencies or [],
        "passes": False,
    }
    if files_touch is not None:
        story["filesTouch"] = files_touch
    if retry_num:
        story["retry_num"] = retry_num
    return story


def _make_prd(stories: list[dict]) -> dict:
    return {"userStories": stories}


def _stories_with_varied_complexity(n: int) -> list[dict]:
    """Create n stories with complexities roughly spanning 1-10.

    Uses description length and dependency count to vary complexity.
    """
    stories: list[dict] = []
    for i in range(n):
        # Scale word count from 5 to 250, deps from 0 to 5
        word_count = 5 + int((i / max(n - 1, 1)) * 245)
        dep_count = min(i % 6, 5)
        files_count = min(i % 11, 10)
        stories.append(
            _make_story(
                sid=f"US-{i + 1:03d}",
                description=" ".join(["word"] * word_count),
                dependencies=[f"US-DEP-{d}" for d in range(dep_count)],
                files_touch=[f"file{f}.py" for f in range(files_count)],
                retry_num=i % 4,
            )
        )
    return stories


def _compute_worker_loads(
    assignment: dict[int, list[str]],
    stories: list[dict],
    prd: dict,
) -> dict[int, float]:
    """Compute total complexity load per worker from an assignment."""
    story_map = {s["id"]: s for s in stories}
    loads: dict[int, float] = {}
    for worker_id, sids in assignment.items():
        total = 0.0
        for sid in sids:
            total += compute_story_complexity(story_map[sid], prd)
        loads[worker_id] = total
    return loads


# ── Unit tests ─────────────────────────────────────────────────────────────────


class TestAssignStoriesToWorkers:
    """Core assignment function tests."""

    def test_single_worker_gets_all(self) -> None:
        stories = _stories_with_varied_complexity(5)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=1, prd=prd)
        assert len(result) == 1
        assert len(result[0]) == 5

    def test_all_workers_present_in_result(self) -> None:
        stories = _stories_with_varied_complexity(3)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=5, prd=prd)
        assert set(result.keys()) == {0, 1, 2, 3, 4}

    def test_no_story_assigned_twice(self) -> None:
        stories = _stories_with_varied_complexity(20)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=4, prd=prd)
        all_assigned = [sid for sids in result.values() for sid in sids]
        assert len(all_assigned) == len(set(all_assigned)), "Duplicate story assignment"

    def test_all_stories_assigned(self) -> None:
        stories = _stories_with_varied_complexity(20)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=4, prd=prd)
        all_assigned = sorted(sid for sids in result.values() for sid in sids)
        expected = sorted(s["id"] for s in stories)
        assert all_assigned == expected

    def test_raises_on_zero_workers(self) -> None:
        stories = _stories_with_varied_complexity(3)
        with pytest.raises(ValueError, match="num_workers must be >= 1"):
            assign_stories_to_workers(stories, num_workers=0)

    def test_raises_on_empty_stories(self) -> None:
        with pytest.raises(ValueError, match="stories list must not be empty"):
            assign_stories_to_workers([], num_workers=2)


class TestFairnessMetric:
    """Acceptance criterion: max/min load ratio < 1.20 (variance <20%)."""

    def test_20_stories_4_workers_fairness(self) -> None:
        """Integration test: 20 stories with varied complexity across 4 workers."""
        stories = _stories_with_varied_complexity(20)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=4, prd=prd)

        # All stories assigned exactly once
        all_assigned = [sid for sids in result.values() for sid in sids]
        assert len(all_assigned) == 20
        assert len(set(all_assigned)) == 20, "No duplicates"

        # All workers get at least 1 story
        for worker_id in range(4):
            assert len(result[worker_id]) >= 1, f"Worker {worker_id} has no stories"

        # Fairness: max_load / min_load < 1.20
        loads = _compute_worker_loads(result, stories, prd)
        active_loads = [v for v in loads.values() if v > 0]
        assert len(active_loads) == 4, "All workers should have load > 0"
        ratio = max(active_loads) / min(active_loads)
        assert ratio < 1.20, (
            f"Load variance too high: max/min = {ratio:.3f} (loads: {loads})"
        )

    def test_equal_complexity_stories_perfect_balance(self) -> None:
        """Identical stories should be evenly distributed."""
        stories = [
            _make_story(f"US-{i:03d}", description="same words same words")
            for i in range(8)
        ]
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=4, prd=prd)

        counts = [len(sids) for sids in result.values()]
        assert all(c == 2 for c in counts), f"Expected 2 per worker, got {counts}"

    def test_10_stories_3_workers_fairness(self) -> None:
        """Smaller case: 10 stories across 3 workers."""
        stories = _stories_with_varied_complexity(10)
        prd = _make_prd(stories)
        result = assign_stories_to_workers(stories, num_workers=3, prd=prd)

        loads = _compute_worker_loads(result, stories, prd)
        active_loads = [v for v in loads.values() if v > 0]
        ratio = max(active_loads) / min(active_loads)
        assert ratio < 1.20, f"Load variance too high: {ratio:.3f}"


class TestPrdAutoConstruction:
    """When prd=None, the function should auto-construct from stories."""

    def test_works_without_explicit_prd(self) -> None:
        stories = _stories_with_varied_complexity(6)
        result = assign_stories_to_workers(stories, num_workers=2)
        all_assigned = [sid for sids in result.values() for sid in sids]
        assert len(all_assigned) == 6
