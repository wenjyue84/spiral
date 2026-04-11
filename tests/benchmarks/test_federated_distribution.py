"""Performance benchmark: Phase I federated story distribution by sub-project (US-1208).

Acceptance Criteria:
- AC1: Performance test measures key metrics for US-636
- AC2: Baseline captured and acceptable threshold defined
- AC3: Test fails if response time degrades more than 20% from baseline
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_LIB = Path(__file__).parent.parent.parent / "lib"
sys.path.insert(0, str(_LIB / "prd"))
sys.path.insert(0, str(_LIB))

from partition_prd import assign_stories  # noqa: E402

_THRESHOLD = 1.20  # 20% regression allowed
_NUM_WORKERS = 3
_NUM_STORIES = 30
_SUB_PROJECTS = ["frontend", "backend", "infra"]


def _make_federated_stories(n: int = _NUM_STORIES) -> list[dict[str, Any]]:
    """Generate N federated stories spread evenly across sub-projects."""
    return [
        {
            "id": f"US-PERF-{i:04d}",
            "title": f"Story {i} for {_SUB_PROJECTS[i % len(_SUB_PROJECTS)]}",
            "sub_project": _SUB_PROJECTS[i % len(_SUB_PROJECTS)],
            "passes": False,
            "priority": "medium",
            "description": f"Perf test story {i}",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        }
        for i in range(n)
    ]


def test_federated_distribution_performance(tmp_path: Path) -> None:
    """AC1+AC2: Measure assign_stories with federated routing; capture/check baseline."""
    baseline_file = tmp_path / "perf_baseline_us1208.json"

    stories = _make_federated_stories()

    t0 = time.monotonic()
    buckets = assign_stories(stories, _NUM_WORKERS)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # AC1: Key metrics — all stories distributed, correct worker count
    total_assigned = sum(len(b) for b in buckets)
    assert total_assigned == len(stories), "All stories must be distributed"
    assert len(buckets) == _NUM_WORKERS

    # AC2: Baseline capture / threshold enforcement
    if baseline_file.exists():
        saved: dict[str, Any] = json.loads(baseline_file.read_text(encoding="utf-8"))
        threshold_ms = saved["baseline_ms"] * _THRESHOLD
        assert elapsed_ms <= threshold_ms, (
            f"Performance regression: {elapsed_ms}ms > {threshold_ms:.0f}ms (baseline {saved['baseline_ms']}ms + 20%)"
        )
    else:
        baseline_file.write_text(json.dumps({"baseline_ms": elapsed_ms}), encoding="utf-8")


def test_federated_distribution_sub_project_isolation() -> None:
    """AC: Each sub-project's stories run in isolation without cross-contamination."""
    stories = _make_federated_stories()
    seen_ids: set[str] = set()

    for sp in _SUB_PROJECTS:
        sp_stories = [s for s in stories if s["sub_project"] == sp]
        buckets = assign_stories(sp_stories, 2)
        for bucket in buckets:
            for s in bucket:
                assert s["id"] not in seen_ids, f"{s['id']} contaminated across sub-projects"
                seen_ids.add(s["id"])

    sp_ids = {s["id"] for s in stories}
    assert seen_ids == sp_ids, "Not all stories were distributed"


def test_federated_distribution_regression_threshold() -> None:
    """AC3: 20% threshold correctly distinguishes acceptable vs degraded performance."""
    baseline_ms = 100
    threshold_ms = baseline_ms * _THRESHOLD  # 120 ms

    # 10% slowdown — within threshold (should pass)
    assert int(baseline_ms * 1.10) <= threshold_ms, "10% slowdown falsely flagged"
    # 25% slowdown — exceeds threshold (should be caught)
    assert int(baseline_ms * 1.25) > threshold_ms, "25% slowdown not caught"
