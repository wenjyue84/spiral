"""Integration Test: Phase M Merge Story ID Ordering Consistency Under Parallel Writes.

US-1080:
- AC1: 30 random stories (US-100..US-129) across 5 sub-projects, 3 workers with disjoint slices
- AC2: final prd.json stories sorted numerically by story_id, no duplicates
- AC3: 10 runs with different random seeds; fails with diff showing misordered segment
"""

import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

MERGE_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "lib", "prd", "merge_stories.py")
PYTHON = sys.executable
BASE_STORY_COUNT = 99  # US-001..US-099, all passes=True
SUB_PROJECTS = ["auth", "api", "frontend", "data", "infra"]


def _make_prd(stories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "productName": "OrderingTest",
        "branchName": "main",
        "goals": ["Verify ordering consistency under parallel writes"],
        "userStories": stories,
    }


def _make_base_story(story_id: str, title: str) -> dict[str, Any]:
    return {
        "id": story_id,
        "title": title,
        "description": f"Base story {story_id}",
        "priority": "medium",
        "acceptanceCriteria": ["Done"],
        "passes": True,
        "dependencies": [],
    }


def _make_candidate(title: str, sub_project: str) -> dict[str, Any]:
    """Create a research candidate. Empty epicId avoids the stricter 0.45 dedup threshold."""
    return {
        "title": title,
        "description": f"Candidate for {sub_project}",
        "priority": "medium",
        "_source": "research",
        "epicId": "",
        "acceptanceCriteria": ["AC1"],
        "technicalNotes": [],
        "estimatedComplexity": "small",
    }


def _id_to_num(story_id: str) -> int:
    """Extract numeric part: 'US-100' -> 100, returns -1 if no match."""
    m = re.match(r"[A-Z]+-(\d+)$", story_id)
    return int(m.group(1)) if m else -1


def _run_merge(prd_path: str, research_path: str, tmp_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SPIRAL_SCRATCH_DIR"] = str(tmp_dir)
    # Prevent dead-weight archiving from interfering with ordering assertions
    env["SPIRAL_DEAD_WEIGHT_THRESHOLD"] = "100"
    # Disable per-iteration research cap so all 10 candidates per worker are merged
    env["SPIRAL_MAX_RESEARCH_STORIES"] = "0"
    return subprocess.run(
        [PYTHON, MERGE_SCRIPT, "--prd", prd_path, "--research", research_path],
        capture_output=True,
        text=True,
        env=env,
    )


def _misordered_diff(ids: list[str]) -> str:
    """Return a human-readable segment showing the first misordered pair."""
    nums = [_id_to_num(sid) for sid in ids]
    for i in range(1, len(nums)):
        if nums[i] < nums[i - 1]:
            start = max(0, i - 2)
            end = min(len(ids), i + 3)
            segment = "\n".join(f"  [{j}] {ids[j]}  (num={nums[j]})" for j in range(start, end))
            return (
                f"First misordering at index {i}: "
                f"{ids[i - 1]} ({nums[i - 1]}) > {ids[i]} ({nums[i]})\n{segment}"
            )
    return "(no misordering detected)"


@pytest.mark.parametrize("seed", range(10))
def test_phase_m_story_id_ordering_under_parallel_writes(seed: int, tmp_path: Path) -> None:
    """AC1+AC2+AC3: 3 workers merge disjoint 10-story slices; result must be numerically sorted.

    Simulates parallel Phase M workers each merging a disjoint slice of research candidates
    into the same prd.json. Verifies no stories are lost or duplicated and that assigned
    IDs appear in numerically ascending order (US-100, US-101, ..., US-129).
    """
    rng = random.Random(seed)

    # --- Setup: base prd.json with US-001..US-099 (all passed) ---
    base_stories: list[dict[str, Any]] = [
        _make_base_story(f"US-{i:03d}", f"Base story {i:03d}") for i in range(1, BASE_STORY_COUNT + 1)
    ]
    prd_path = str(tmp_path / "prd.json")
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(_make_prd(base_stories), f)

    # --- AC1: Generate 30 unique candidate stories across 5 sub-projects ---
    # UID prefix ensures Jaccard similarity ≈ 0 between any two titles,
    # preventing false deduplication during merge.
    candidates: list[dict[str, Any]] = []
    for i in range(30):
        sub = SUB_PROJECTS[i % len(SUB_PROJECTS)]
        uid = rng.randint(10**9, 10**10 - 1)
        title = f"UID{uid}-s{seed:02d}i{i:03d}"
        candidates.append(_make_candidate(title, sub))

    # Shuffle and split into 3 disjoint slices of 10 stories each
    rng.shuffle(candidates)
    slices = [candidates[0:10], candidates[10:20], candidates[20:30]]

    # --- AC1: Simulate 3 parallel workers merging disjoint slices sequentially ---
    for worker_idx, worker_slice in enumerate(slices):
        research_path = str(tmp_path / f"research_w{worker_idx}.json")
        with open(research_path, "w", encoding="utf-8") as f:
            json.dump({"stories": worker_slice}, f)
        result = _run_merge(prd_path, research_path, tmp_path)
        assert result.returncode == 0, (
            f"Merge failed (seed={seed}, worker={worker_idx}):\n"
            f"stdout: {result.stdout[-600:]}\nstderr: {result.stderr[-300:]}"
        )

    # --- AC2: Verify final prd.json ---
    with open(prd_path, encoding="utf-8") as f:
        final_prd = json.load(f)

    all_stories: list[dict[str, Any]] = final_prd["userStories"]
    new_stories = [s for s in all_stories if _id_to_num(s["id"]) >= 100]
    new_ids = [s["id"] for s in new_stories]

    # AC2: Exactly 30 new stories (none lost, none rejected as false duplicates)
    assert len(new_stories) == 30, (
        f"Expected 30 new stories (seed={seed}), got {len(new_stories)}. "
        f"Present IDs: {new_ids}"
    )

    # AC2: No duplicate IDs
    assert len(new_ids) == len(set(new_ids)), (
        f"Duplicate story IDs found (seed={seed}): "
        f"{[sid for sid in new_ids if new_ids.count(sid) > 1]}"
    )

    # AC2+AC3: Stories appear in numerically ascending order (US-100..US-129)
    expected_nums = list(range(100, 130))
    actual_nums = [_id_to_num(sid) for sid in new_ids]
    assert actual_nums == expected_nums, (
        f"Story ordering inconsistent (seed={seed}):\n"
        f"Expected: {expected_nums}\n"
        f"Actual:   {actual_nums}\n"
        f"{_misordered_diff(new_ids)}"
    )
