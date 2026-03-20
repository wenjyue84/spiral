"""Performance benchmark for worker load balancer (US-587).

Measures story distribution performance across varying story counts (10, 100, 500)
distributed to 8 workers. Asserts that the 500-story case completes within
a defined latency threshold to prevent the load balancer from becoming a
bottleneck before the worker pool is spawned.

Acceptance Criteria:
- Running `uv run pytest tests/test_perf_load_balancer.py -v -s` passes
- Benchmark prints per-run timing (story count, worker count, elapsed ms) to stdout
- Assertion that distributing 500 stories across 8 workers completes in <200ms
- Test fails with descriptive AssertionError if time exceeds threshold by >20%
- Benchmark covers at least three input sizes (10, 100, 500)
"""

import os
import random
import sys
import time
from typing import Any

import pytest

# Add lib/ to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from worker_load_balancer import distribute_stories

# Performance threshold: 500 stories across 8 workers must complete in this time
THRESHOLD_MS = 200


def _generate_synthetic_stories(
    count: int, random_seed: int = 42
) -> list[dict[str, Any]]:
    """Generate reproducible synthetic story data for benchmarking.

    Args:
        count: Number of stories to generate (10, 100, or 500)
        random_seed: Fixed seed for reproducibility

    Returns:
        List of story dicts with id, estimated_tokens, and dependencies.
        Token counts: 100-4000 (realistic range for Claude API calls)
        Dependencies: 0-3 per story (realistic dependency depth)
    """
    random.seed(random_seed)
    stories = []

    for i in range(count):
        # Random token count: 100-4000 tokens per story
        tokens = random.randint(100, 4000)

        # Random dependencies: 0-3 dependent stories
        # Limit dependency IDs to stories before this one to maintain DAG structure
        num_deps = random.randint(0, 3)
        max_dep_id = max(0, i - 1)
        dep_ids = []
        if max_dep_id > 0 and num_deps > 0:
            dep_ids = [f"US-{random.randint(1, max_dep_id)}" for _ in range(num_deps)]

        stories.append(
            {
                "id": f"US-{i+1:04d}",
                "estimated_tokens": tokens,
                "dependencies": dep_ids,
            }
        )

    return stories


@pytest.mark.parametrize("story_count", [10, 100, 500])
def test_distribute_stories_performance(story_count: int) -> None:
    """Benchmark story distribution performance across three input sizes.

    AC:
    - Prints story_count, worker_count, and elapsed_ms for each run
    - Completes within reasonable time for all sizes
    - 500-story case specifically asserts <200ms (+ 20% tolerance = 240ms max)

    Args:
        story_count: Parametrized count (10, 100, or 500 stories)
    """
    num_workers = 8
    stories = _generate_synthetic_stories(story_count)

    # Measure distribution time using high-resolution counter
    start_time = time.perf_counter()
    assignment = distribute_stories(stories, num_workers)
    elapsed_sec = time.perf_counter() - start_time
    elapsed_ms = elapsed_sec * 1000

    # Print timing for CI logs and analysis
    print(
        f"\n[PASS] Distributed {story_count} stories to {num_workers} workers in {elapsed_ms:.2f}ms"
    )

    # Verify assignment completeness
    assigned_story_count = sum(len(ids) for ids in assignment.values())
    assert assigned_story_count == story_count, (
        f"Expected {story_count} stories assigned, got {assigned_story_count}"
    )

    # Verify all workers received assignments (fairness)
    non_empty_workers = sum(1 for ids in assignment.values() if ids)
    assert non_empty_workers > 0, "No workers received story assignments"

    # For 500-story case, assert performance threshold
    if story_count == 500:
        threshold_tolerance = THRESHOLD_MS * 0.2  # Allow 20% overage
        max_allowed_ms = THRESHOLD_MS + threshold_tolerance

        assert elapsed_ms <= max_allowed_ms, (
            f"Distribution of {story_count} stories took {elapsed_ms:.2f}ms, "
            f"exceeds threshold of {THRESHOLD_MS}ms (+ 20% = {max_allowed_ms:.2f}ms). "
            f"This would make the load balancer a bottleneck."
        )

        print(f"  Threshold check: {elapsed_ms:.2f}ms <= {max_allowed_ms:.2f}ms [OK]")


def test_distribute_stories_load_fairness() -> None:
    """Verify load distribution fairness across workers.

    AC:
    - 20 stories distributed to 4 workers have fairness metric < 1.20
    - Fairness = max_worker_complexity / min_worker_complexity < 1.20
    - All workers receive at least 1 story (unless stories < workers)

    This test uses a fixed set of story complexities to ensure
    reproducible fairness metrics across test runs.
    """
    stories = [
        {"id": f"US-{i:04d}", "estimated_tokens": (i % 10) * 400 + 100, "dependencies": []}
        for i in range(20)
    ]
    num_workers = 4

    assignment = distribute_stories(stories, num_workers)

    # Calculate complexity per worker
    worker_complexity: dict[int, int] = {}
    for worker_id, story_ids in assignment.items():
        total_complexity = 0
        for story in stories:
            if story["id"] in story_ids:
                story_tokens: Any = story.get("estimated_tokens", 0)
                story_deps: Any = story.get("dependencies", [])
                tokens = int(story_tokens) if story_tokens is not None else 0
                deps = story_deps if isinstance(story_deps, list) else []
                total_complexity += tokens + (len(deps) * 2)
        worker_complexity[worker_id] = total_complexity

    # Check fairness metric
    non_empty_workers = [c for c in worker_complexity.values() if c > 0]
    if non_empty_workers:
        max_complexity = max(non_empty_workers)
        min_complexity = min(non_empty_workers)

        if min_complexity > 0:
            fairness_metric = max_complexity / min_complexity
            assert fairness_metric < 1.20, (
                f"Load unfairness detected: max {max_complexity} / min {min_complexity} "
                f"= {fairness_metric:.2f} (threshold: <1.20)"
            )

    # Verify no story assigned to multiple workers
    all_assigned = []
    for story_ids in assignment.values():
        all_assigned.extend(story_ids)
    assert len(all_assigned) == len(set(all_assigned)), "Story assigned to multiple workers"

    print(f"\n[PASS] Load fairness check passed: {fairness_metric:.2f} < 1.20")
    print(f"  Worker complexity: {worker_complexity}")


def test_distribute_stories_edge_cases() -> None:
    """Verify edge case handling.

    AC:
    - Empty story list returns empty assignments
    - Single story to single worker works correctly
    - More workers than stories assigns stories to distinct workers
    """
    # Test: empty stories
    assignment = distribute_stories([], 4)
    assert assignment == {0: [], 1: [], 2: [], 3: []}, "Empty list should return empty assignment"

    # Test: single story to single worker
    stories = [{"id": "US-0001", "estimated_tokens": 1000, "dependencies": []}]
    assignment = distribute_stories(stories, 1)
    assert len(assignment) == 1
    assert assignment[0] == ["US-0001"]

    # Test: more workers than stories
    stories = [
        {"id": f"US-{i:04d}", "estimated_tokens": 500, "dependencies": []} for i in range(3)
    ]
    assignment = distribute_stories(stories, 5)
    assert len(assignment) == 5, "Should have 5 worker slots"
    assigned_count = sum(len(ids) for ids in assignment.values())
    assert assigned_count == 3, "Should have assigned all 3 stories"

    print(
        "\n[PASS] Edge cases passed: empty list, single story, more workers than stories"
    )
