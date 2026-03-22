#!/usr/bin/env python3
"""
Flaky Test Detection for Phase T: Test Synthesis

Tracks test failure history across iterations in .spiral/test_failure_history.json.
Tests failing <50% across last 5 iterations are flagged flaky and excluded from story generation.

Functions:
  - record_test_result(test_id: str, passed: bool) -> None
  - is_flaky_test(test_id: str, window_size: int = 5, threshold: float = 0.5) -> bool
  - get_flaky_tests(window_size: int = 5, threshold: float = 0.5) -> list[str]
  - get_flaky_tests_with_rates(window_size: int = 5, threshold: float = 0.5) -> list[tuple[str, float]]
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _history_file(spiral_home: str | None = None) -> str:
    """Return path to test failure history file."""
    if spiral_home is None:
        spiral_home = os.environ.get("SPIRAL_HOME", ".")
    history_dir = os.path.join(spiral_home, ".spiral")
    os.makedirs(history_dir, exist_ok=True)
    return os.path.join(history_dir, "test_failure_history.json")


def _load_history(path: str) -> dict[str, Any]:
    """Load test failure history from JSON file."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_history(path: str, history: dict[str, Any]) -> None:
    """Save test failure history to JSON file atomically."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Write to temp file, then move atomically
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def record_test_result(test_id: str, passed: bool, spiral_home: str | None = None) -> None:
    """
    Record a pass or fail for a test across iterations.

    Args:
        test_id: Test identifier (e.g., 'tests.unit.test_module.test_function')
        passed: True if test passed, False if failed
        spiral_home: SPIRAL_HOME path (defaults to env var or '.')
    """
    path = _history_file(spiral_home)
    history = _load_history(path)

    if test_id not in history:
        history[test_id] = {"results": [], "last_updated": ""}

    entry = history[test_id]
    entry["results"].append(1 if passed else 0)
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()

    _save_history(path, history)


def is_flaky_test(
    test_id: str,
    window_size: int = 5,
    threshold: float = 0.5,
    spiral_home: str | None = None,
) -> bool:
    """
    Check if a test is flaky (fails between 0% and <threshold% in the last window_size iterations).

    A test is flaky if:
    - It has at least window_size result entries
    - It has SOME failures (not always passing)
    - Failure rate (failures / total) is below threshold (default: <50%)

    This means intermittent failures but not consistently failing.

    Args:
        test_id: Test identifier
        window_size: Number of iterations to consider (default: 5)
        threshold: Failure rate threshold below which a test is considered flaky (default: 0.5)
        spiral_home: SPIRAL_HOME path

    Returns:
        True if test is flaky (fails <threshold% but >0% in last window_size iterations)
    """
    path = _history_file(spiral_home)
    history = _load_history(path)

    if test_id not in history:
        return False

    results = history[test_id].get("results", [])
    if len(results) < window_size:
        return False

    # Look at last window_size results
    recent = results[-window_size:]
    failures_count = window_size - sum(recent)
    failure_rate = failures_count / window_size

    # Flaky: has failures but less than threshold
    return bool(0 < failure_rate < threshold)


def get_flaky_tests(
    window_size: int = 5,
    threshold: float = 0.5,
    spiral_home: str | None = None,
) -> list[str]:
    """
    Get list of all flaky test IDs.

    Args:
        window_size: Number of iterations to consider
        threshold: Failure rate threshold
        spiral_home: SPIRAL_HOME path

    Returns:
        List of test IDs that are flaky
    """
    path = _history_file(spiral_home)
    history = _load_history(path)

    flaky = []
    for test_id in history:
        if is_flaky_test(test_id, window_size, threshold, spiral_home):
            flaky.append(test_id)

    return sorted(flaky)


def get_flaky_tests_with_rates(
    window_size: int = 5,
    threshold: float = 0.5,
    spiral_home: str | None = None,
) -> list[tuple[str, float]]:
    """
    Get list of flaky tests with their failure rates.

    Args:
        window_size: Number of iterations to consider
        threshold: Failure rate threshold
        spiral_home: SPIRAL_HOME path

    Returns:
        List of (test_id, failure_rate) tuples, sorted by test_id
    """
    path = _history_file(spiral_home)
    history = _load_history(path)

    result = []
    for test_id in sorted(history.keys()):
        if is_flaky_test(test_id, window_size, threshold, spiral_home):
            results = history[test_id].get("results", [])
            recent = results[-window_size:]
            failures = window_size - sum(recent)
            failure_rate = failures / window_size
            result.append((test_id, failure_rate))

    return result


if __name__ == "__main__":
    # Simple CLI for testing
    if len(sys.argv) < 2:
        print("Usage: flaky_detector.py <command> [args]")
        print("  record <test_id> <pass|fail>")
        print("  is_flaky <test_id>")
        print("  list")
        print("  list_with_rates")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "record" and len(sys.argv) >= 4:
        test_id = sys.argv[2]
        result = sys.argv[3]
        record_test_result(test_id, result.lower() == "pass")
    elif cmd == "is_flaky" and len(sys.argv) >= 3:
        test_id = sys.argv[2]
        flaky = is_flaky_test(test_id)
        print("true" if flaky else "false")
    elif cmd == "list":
        flaky_tests_list = get_flaky_tests()
        for test_id in flaky_tests_list:
            print(test_id)
    elif cmd == "list_with_rates":
        flaky_tests_with_rates = get_flaky_tests_with_rates()
        for test_id, rate in flaky_tests_with_rates:
            print(f"{test_id}: {rate:.1%}")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
