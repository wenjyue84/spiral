"""Worker Load Balancer - Distribute stories across parallel workers by complexity.

This module implements story-to-worker assignment optimization that distributes
pending stories across parallel workers to minimize execution variance.

Complexity is computed as: token_count + (dependency_count * 2)

The greedy bin-packing algorithm:
1. Sort stories by complexity (descending)
2. For each story, assign it to the least-loaded worker
3. Return assignment dict: {worker_id -> [story_ids]}

Fairness metric: max_worker_complexity / min_worker_complexity should be < 1.20
(load variance < 20%) after assignment.
"""

from typing import Any


def distribute_stories(stories: list[dict[str, Any]], num_workers: int) -> dict[int, list[str]]:
    """Distribute stories across workers using greedy bin-packing.

    Args:
        stories: List of story dicts with keys:
            - 'id': str (story ID, e.g., 'US-001')
            - 'estimated_tokens': int (forecasted token count, 100-4000)
            - 'dependencies': list[str] (IDs of dependent stories, 0-3)
        num_workers: Number of workers to distribute across (e.g., 8)

    Returns:
        Dict mapping worker_id (int 0..num_workers-1) to list of story IDs assigned to that worker.
        Example: {0: ['US-001', 'US-005'], 1: ['US-002'], ...}

    The algorithm assigns high-complexity stories first to ensure better load balancing.
    """
    if not stories:
        return {i: [] for i in range(num_workers)}

    if num_workers <= 0:
        raise ValueError("num_workers must be > 0")

    # Calculate complexity for each story: tokens + (dependencies * 2)
    story_complexity: list[tuple[str, int]] = []
    for story in stories:
        tokens = story.get("estimated_tokens", 0)
        deps_count = len(story.get("dependencies", []))
        complexity = tokens + (deps_count * 2)
        story_id: str = story["id"]
        story_complexity.append((story_id, complexity))

    # Sort by complexity descending (assign hard stories first)
    story_complexity.sort(key=lambda x: x[1], reverse=True)

    # Initialize workers with zero load
    worker_loads: list[int] = [0] * num_workers
    worker_assignments: dict[int, list[str]] = {i: [] for i in range(num_workers)}

    # Greedy assignment: assign each story to least-loaded worker
    for story_id, complexity in story_complexity:
        # Find worker with minimum load
        least_loaded_worker = 0
        min_load = worker_loads[0]
        for worker_id in range(1, num_workers):
            if worker_loads[worker_id] < min_load:
                min_load = worker_loads[worker_id]
                least_loaded_worker = worker_id

        # Assign story to that worker
        worker_assignments[least_loaded_worker].append(story_id)
        worker_loads[least_loaded_worker] += complexity

    return worker_assignments
