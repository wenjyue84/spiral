"""tests/test_phase_v_performance.py — Tests for Phase V performance regression detector."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from phases.phase_v_performance import compare_to_baseline, parse_pytest_times  # noqa: E402


def test_detect_slowdown_regression(tmp_path: Path) -> None:
    """Flag tests that regress >10% vs baseline."""
    baseline = {
        "tests/test_foo.py::test_slow": 1000.0,
        "tests/test_foo.py::test_fast": 200.0,
    }
    baseline_file = tmp_path / "performance_baseline.json"
    baseline_file.write_text(json.dumps(baseline), encoding="utf-8")

    # test_slow regressed 10.1%, test_fast is fine
    current = {
        "tests/test_foo.py::test_slow": 1101.0,
        "tests/test_foo.py::test_fast": 205.0,
    }
    regressions = compare_to_baseline(current, str(baseline_file))

    assert len(regressions) == 1
    assert regressions[0]["test"] == "tests/test_foo.py::test_slow"
    assert regressions[0]["pct_change"] > 10.0


def test_no_regression_within_threshold(tmp_path: Path) -> None:
    """Tests within 10% threshold are not flagged."""
    baseline = {"tests/test_bar.py::test_ok": 1000.0}
    baseline_file = tmp_path / "performance_baseline.json"
    baseline_file.write_text(json.dumps(baseline), encoding="utf-8")

    current = {"tests/test_bar.py::test_ok": 1099.0}  # 9.9% — under threshold
    regressions = compare_to_baseline(current, str(baseline_file))

    assert regressions == []


def test_parse_pytest_times() -> None:
    """parse_pytest_times extracts duration_ms from pytest JSON report."""
    report = {
        "tests": [
            {"nodeid": "tests/test_a.py::test_x", "call": {"duration": 0.5}},
            {"nodeid": "tests/test_a.py::test_y", "call": {"duration": 1.2}},
        ]
    }
    times = parse_pytest_times(report)

    assert times["tests/test_a.py::test_x"] == pytest.approx(500.0)
    assert times["tests/test_a.py::test_y"] == pytest.approx(1200.0)


def test_missing_baseline_returns_no_regressions(tmp_path: Path) -> None:
    """If baseline file doesn't exist, no regressions are reported."""
    current = {"tests/test_c.py::test_z": 9999.0}
    regressions = compare_to_baseline(current, str(tmp_path / "nonexistent.json"))
    assert regressions == []
