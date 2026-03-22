"""Phase V: Test Execution Time Performance Regression Detector.

Parses pytest JSON output (--json-report) to detect per-test slowdowns
vs a stored baseline. Fails validation if any test regresses >10%.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_pytest_times(report: dict[str, Any]) -> dict[str, float]:
    """Extract per-test duration in milliseconds from a pytest JSON report.

    Args:
        report: Parsed pytest-json-report dict (from --json-report output).

    Returns:
        Mapping of test node_id -> duration_ms.
    """
    times: dict[str, float] = {}
    for test in report.get("tests", []):
        node_id = test.get("nodeid", "")
        call = test.get("call", {}) or {}
        duration_s = call.get("duration", 0.0) or 0.0
        times[node_id] = duration_s * 1000.0
    return times


def compare_to_baseline(current: dict[str, float], baseline_path: str) -> list[dict[str, object]]:
    """Compare current test durations to stored baseline; return regressions.

    A regression is any test that takes >10% longer than its baseline value.

    Args:
        current: Mapping of test node_id -> duration_ms from current run.
        baseline_path: Path to .spiral/performance_baseline.json.

    Returns:
        List of dicts with keys: test, current_ms, baseline_ms, pct_change.
        Empty list means no regressions.
    """
    baseline_file = Path(baseline_path)
    if not baseline_file.exists():
        return []

    with open(baseline_file, encoding="utf-8") as f:
        baseline: dict[str, float] = json.load(f)

    regressions: list[dict[str, object]] = []
    for node_id, current_ms in current.items():
        if node_id not in baseline:
            continue
        baseline_ms = baseline[node_id]
        if baseline_ms <= 0:
            continue
        pct_change = (current_ms - baseline_ms) / baseline_ms * 100.0
        if pct_change > 10.0:
            regressions.append(
                {
                    "test": node_id,
                    "current_ms": current_ms,
                    "baseline_ms": baseline_ms,
                    "pct_change": round(pct_change, 1),
                }
            )
    return regressions


def run_performance_check(report_path: str, baseline_path: str) -> bool:
    """Run regression check and update baseline if no regressions found.

    Args:
        report_path: Path to pytest JSON report file.
        baseline_path: Path to .spiral/performance_baseline.json.

    Returns:
        True if validation passes (no regressions), False otherwise.
    """
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    current = parse_pytest_times(report)
    regressions = compare_to_baseline(current, baseline_path)

    if regressions:
        for r in regressions:
            print(
                f"REGRESSION: {r['test']} — {r['current_ms']:.0f}ms vs "
                f"{r['baseline_ms']:.0f}ms baseline ({r['pct_change']:+.1f}%)"
            )
        return False

    # No regressions — update baseline
    Path(baseline_path).parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return True
