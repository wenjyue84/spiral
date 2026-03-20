"""lib/worker_balancer.py — Worker load balancer for SPIRAL Phase I (US-562).

Distributes pending stories across parallel workers using greedy bin-packing
to minimize execution variance. Stories are sorted by complexity (descending)
and assigned one-by-one to the least-loaded worker.

Public API
----------
assign_stories_to_workers(stories, num_workers, prd=None) -> dict[int, list[str]]
    Greedy bin-packing assignment. Returns {worker_id: [story_ids]}.
"""

from __future__ import annotations

from typing import Any

from story_complexity import compute_story_complexity

__all__ = ["assign_stories_to_workers"]


def assign_stories_to_workers(
    stories: list[dict[str, Any]],
    num_workers: int,
    prd: dict[str, Any] | None = None,
) -> dict[int, list[str]]:
    """Distribute stories across workers using greedy bin-packing.

    Algorithm:
        1. Compute complexity for each story.
        2. Sort stories by complexity descending (heaviest first).
        3. For each story, assign it to the worker with the lowest current load.

    Parameters
    ----------
    stories:
        List of story dicts (from prd.json ``userStories``).
    num_workers:
        Number of parallel workers available.
    prd:
        Full PRD dict, passed to ``compute_story_complexity``.
        If None, a minimal PRD is constructed from the stories list.

    Returns
    -------
    dict[int, list[str]]
        Mapping of worker_id (0-based) to list of story IDs assigned.
        Every worker_id in range(num_workers) is present even if empty.

    Raises
    ------
    ValueError
        If num_workers < 1 or stories is empty.
    """
    if num_workers < 1:
        msg = f"num_workers must be >= 1, got {num_workers}"
        raise ValueError(msg)
    if not stories:
        msg = "stories list must not be empty"
        raise ValueError(msg)

    if prd is None:
        prd = {"userStories": stories}

    # Compute complexity for each story
    scored: list[tuple[str, float]] = []
    for story in stories:
        sid = story.get("id", "")
        complexity = compute_story_complexity(story, prd)
        scored.append((sid, complexity))

    # Sort by complexity descending (heaviest first for greedy bin-packing)
    scored.sort(key=lambda x: x[1], reverse=True)

    # Initialize worker bins
    assignment: dict[int, list[str]] = {w: [] for w in range(num_workers)}
    loads: dict[int, float] = {w: 0.0 for w in range(num_workers)}

    # Greedy assignment: each story goes to the least-loaded worker
    for sid, complexity in scored:
        lightest = min(range(num_workers), key=lambda w: loads[w])
        assignment[lightest].append(sid)
        loads[lightest] += complexity

    return assignment
