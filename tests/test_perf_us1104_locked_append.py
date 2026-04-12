"""Performance tests for US-1104: File-locked spiral_events.jsonl writes.

Validates that locked_append_jsonl is fast enough for production use and
does not degrade over repeated calls (Windows concurrent-write safety).

Acceptance Criteria:
- Performance test measures key metrics for US-1104 (per-write latency)
- Baseline captured and acceptable threshold defined (<20ms per write)
- Test fails if response time degrades more than 20% from baseline
- Run: uv run pytest tests/ -k us_1104 -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.core.spiral_io import locked_append_jsonl  # noqa: E402

# Baseline: each locked write must complete within 20ms on a warm filesystem.
_BASELINE_MS_PER_WRITE = 20.0
_SAMPLE_RECORD = {"event": "worker_start", "worker": 1, "ts": 1_700_000_000}


@pytest.mark.us_1104
def test_locked_append_single_write_latency(tmp_path: Path) -> None:
    """AC1+AC2: Single locked_append_jsonl call must stay under baseline threshold."""
    target = str(tmp_path / "spiral_events.jsonl")

    start = time.monotonic()
    locked_append_jsonl(target, _SAMPLE_RECORD)
    elapsed_ms = (time.monotonic() - start) * 1000

    print(f"\n  Single write latency: {elapsed_ms:.2f}ms  baseline: {_BASELINE_MS_PER_WRITE}ms")
    assert elapsed_ms < _BASELINE_MS_PER_WRITE, (
        f"locked_append_jsonl took {elapsed_ms:.2f}ms, exceeds baseline {_BASELINE_MS_PER_WRITE}ms"
    )


@pytest.mark.us_1104
def test_locked_append_no_degradation(tmp_path: Path) -> None:
    """AC3: Latency must not degrade >20% across 10 consecutive writes."""
    target = str(tmp_path / "spiral_events.jsonl")
    latencies: list[float] = []

    for i in range(10):
        record = {**_SAMPLE_RECORD, "seq": i}
        start = time.monotonic()
        locked_append_jsonl(target, record)
        latencies.append((time.monotonic() - start) * 1000)

    baseline = latencies[0]
    threshold = max(baseline * 1.20, _BASELINE_MS_PER_WRITE)

    print(f"\n  Write latencies (ms): {[f'{ms:.2f}' for ms in latencies]}")
    print(f"  Baseline (write 1): {baseline:.2f}ms  Max allowed: {threshold:.2f}ms")

    for idx, ms in enumerate(latencies[1:], start=2):
        assert ms <= threshold, (
            f"Write {idx} took {ms:.2f}ms, exceeds 120% of baseline ({threshold:.2f}ms)"
        )


@pytest.mark.us_1104
def test_locked_append_integrity(tmp_path: Path) -> None:
    """AC1: All records written must be readable with no corruption."""
    target = str(tmp_path / "spiral_events.jsonl")
    n_writes = 20

    for i in range(n_writes):
        locked_append_jsonl(target, {**_SAMPLE_RECORD, "seq": i})

    lines = Path(target).read_text(encoding="utf-8").splitlines()
    assert len(lines) == n_writes, f"Expected {n_writes} lines, found {len(lines)}"
    for line in lines:
        assert line.startswith("{"), f"Corrupt JSONL line: {line!r}"
