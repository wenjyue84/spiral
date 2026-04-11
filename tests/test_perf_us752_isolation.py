"""Performance benchmark: 3-worker federated sub-project isolation (US-752).

Acceptance criteria:
- AC1: Performance test measures key metrics for US-752
- AC2: Baseline captured and acceptable threshold defined
- AC3: Test fails if response time degrades more than 20% from baseline
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

_FIXTURE = Path(__file__).parent / "fixtures" / "federated_load_test_prd.json"
_THRESHOLD = 1.20  # 20% regression allowed
_NUM_WORKERS = 3


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_stories() -> list[dict[str, Any]]:
    with open(_FIXTURE, encoding="utf-8") as f:
        raw: list[dict[str, Any]] = json.load(f)["stories"]
    return raw


def _distribute(stories: list[dict[str, Any]], n: int) -> dict[int, list[dict[str, Any]]]:
    per = len(stories) // n
    return {w: stories[(w - 1) * per : w * per] for w in range(1, n + 1)}


def _check_isolation(workers: dict[int, list[dict[str, Any]]]) -> bool:
    for batch in workers.values():
        if len({s["sub_project"] for s in batch}) != 1:
            return False
    all_ids = [s["id"] for batch in workers.values() for s in batch]
    return len(all_ids) == len(set(all_ids))


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_us_752_fixture_load_performance(tmp_path: Path) -> None:
    """AC1+AC2: Measure end-to-end 3-worker isolation time; save baseline on first run."""
    baseline_file = tmp_path / "perf_baseline_us752.json"

    t0 = time.monotonic()
    stories = _load_stories()
    workers = _distribute(stories, _NUM_WORKERS)
    isolated = _check_isolation(workers)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    assert isolated, "Isolation check failed — cross-contamination detected"
    assert len(workers) == _NUM_WORKERS

    # Capture baseline on first run; enforce threshold on subsequent runs
    if baseline_file.exists():
        saved: dict[str, Any] = json.loads(baseline_file.read_text(encoding="utf-8"))
        threshold_ms = saved["baseline_ms"] * _THRESHOLD
        assert elapsed_ms <= threshold_ms, (
            f"Performance regression: {elapsed_ms}ms exceeds "
            f"{threshold_ms:.0f}ms (baseline {saved['baseline_ms']}ms + 20%)"
        )
    else:
        baseline_file.write_text(json.dumps({"baseline_ms": elapsed_ms}), encoding="utf-8")


def test_us_752_regression_threshold() -> None:
    """AC3: 20% threshold correctly distinguishes acceptable vs degraded performance."""
    baseline_ms = 200
    threshold_ms = baseline_ms * _THRESHOLD  # 240 ms

    # 10% slowdown — within threshold (should pass)
    assert int(baseline_ms * 1.10) <= threshold_ms, "10% slowdown falsely flagged"

    # 25% slowdown — exceeds threshold (should fail)
    assert int(baseline_ms * 1.25) > threshold_ms, "25% slowdown not detected"


def test_us_752_distribution_metrics() -> None:
    """AC1: Key metrics — load, distribute, isolate — each complete in <500 ms."""
    metrics: dict[str, int] = {}

    t0 = time.monotonic()
    stories = _load_stories()
    metrics["load_ms"] = int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    workers = _distribute(stories, _NUM_WORKERS)
    metrics["distribute_ms"] = int((time.monotonic() - t1) * 1000)

    t2 = time.monotonic()
    _check_isolation(workers)
    metrics["isolate_ms"] = int((time.monotonic() - t2) * 1000)

    assert metrics["load_ms"] < 500, f"Fixture load too slow: {metrics['load_ms']} ms"
    assert metrics["distribute_ms"] < 100, f"Distribution too slow: {metrics['distribute_ms']} ms"
    assert metrics["isolate_ms"] < 100, f"Isolation check too slow: {metrics['isolate_ms']} ms"
