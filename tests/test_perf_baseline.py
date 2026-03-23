"""
tests/test_perf_baseline.py — Unit tests for lib/perf_baseline.py
"""

import json
from pathlib import Path

import pytest

from lib.perf_baseline import check_regression, update_baseline


class TestUpdateBaseline:
    """Test baseline update functionality."""

    def test_update_baseline_creates_baseline(self, tmp_path: Path) -> None:
        """Test creating a new baseline from iteration summary."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        iteration_data = {
            "iteration": 1,
            "phase_r_duration_s": 45.5,
            "phase_t_duration_s": 12.3,
            "phase_m_duration_s": 8.1,
            "phase_i_duration_s": 150.0,
            "phase_v_duration_s": 90.0,
            "phase_c_duration_s": 2.1,
        }

        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        baseline = update_baseline(iteration_file, baseline_file)

        assert len(baseline["rolling_window"]) == 1
        assert baseline["rolling_window"][0]["iteration"] == 1
        assert baseline["rolling_window"][0]["phases"]["R"] == 45.5
        assert "p50" in baseline
        assert "p90" in baseline
        assert baseline["p50"]["I"] == 150.0  # single value → p50 = p90 = value
        assert baseline["p90"]["I"] == 150.0

    def test_update_baseline_rolling_window(self, tmp_path: Path) -> None:
        """Test rolling window keeps last 10 iterations."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        # Create initial baseline with 10 iterations
        baseline = {"rolling_window": [], "p50": {}, "p90": {}}
        for i in range(1, 11):
            baseline["rolling_window"].append(
                {
                    "iteration": i,
                    "phases": {
                        "I": float(100 + i * 10),  # 110, 120, 130, ...
                    },
                }
            )

        with open(baseline_file, "w") as f:
            json.dump(baseline, f)

        # Add iteration 11
        iteration_data = {
            "iteration": 11,
            "phase_i_duration_s": 210.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        updated = update_baseline(iteration_file, baseline_file, window_size=10)

        # Should have exactly 10 entries (oldest dropped)
        assert len(updated["rolling_window"]) == 10
        assert updated["rolling_window"][0]["iteration"] == 2
        assert updated["rolling_window"][-1]["iteration"] == 11

    def test_update_baseline_missing_iteration_summary(self, tmp_path: Path) -> None:
        """Test graceful handling of missing iteration summary."""
        iteration_file = tmp_path / "missing.json"
        baseline_file = tmp_path / "baseline.json"

        baseline = update_baseline(iteration_file, baseline_file)

        assert "error" in baseline
        assert len(baseline["rolling_window"]) == 0


class TestCheckRegression:
    """Test regression detection functionality."""

    def test_check_regression_no_baseline(self, tmp_path: Path) -> None:
        """Test first iteration (no baseline) → no regression."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        iteration_data = {
            "iteration": 1,
            "phase_i_duration_s": 150.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        has_regression, report = check_regression(iteration_file, baseline_file)

        assert has_regression is False
        assert "No baseline yet" in report.get("message", "")

    def test_check_regression_within_threshold(self, tmp_path: Path) -> None:
        """Test phase within 2x P90 → no regression."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        # Create baseline: P90 for Phase I = 200s
        baseline = {
            "rolling_window": [
                {"iteration": 1, "phases": {"I": 100.0}},
                {"iteration": 2, "phases": {"I": 200.0}},
                {"iteration": 3, "phases": {"I": 150.0}},
            ],
            "p50": {"I": 150.0},
            "p90": {"I": 200.0},
        }
        with open(baseline_file, "w") as f:
            json.dump(baseline, f)

        # Current: Phase I = 350s (1.75x P90, below 2.0x threshold)
        iteration_data = {
            "iteration": 4,
            "phase_i_duration_s": 350.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        has_regression, report = check_regression(
            iteration_file, baseline_file, multiplier=2.0
        )

        assert has_regression is False
        assert len(report["regressions"]) == 0

    def test_check_regression_exceeds_threshold(self, tmp_path: Path) -> None:
        """Test phase exceeding 2x P90 → regression detected."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        # Create baseline: P90 for Phase I = 400s
        baseline = {
            "rolling_window": [
                {"iteration": 1, "phases": {"I": 350.0}},
                {"iteration": 2, "phases": {"I": 400.0}},
            ],
            "p50": {"I": 375.0},
            "p90": {"I": 400.0},
        }
        with open(baseline_file, "w") as f:
            json.dump(baseline, f)

        # Current: Phase I = 850s (2.125x P90, exceeds 2.0x threshold)
        iteration_data = {
            "iteration": 3,
            "phase_i_duration_s": 850.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        has_regression, report = check_regression(
            iteration_file, baseline_file, multiplier=2.0
        )

        assert has_regression is True
        assert len(report["regressions"]) == 1
        assert report["regressions"][0]["phase"] == "I"
        assert report["regressions"][0]["ratio"] == 2.12  # 850/400

    def test_check_regression_multiple_phases(self, tmp_path: Path) -> None:
        """Test regression in multiple phases."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        baseline = {
            "rolling_window": [
                {
                    "iteration": 1,
                    "phases": {"R": 50.0, "I": 100.0, "V": 80.0},
                },
            ],
            "p50": {"R": 50.0, "I": 100.0, "V": 80.0},
            "p90": {"R": 50.0, "I": 100.0, "V": 80.0},
        }
        with open(baseline_file, "w") as f:
            json.dump(baseline, f)

        # R: 90 (1.8x, no regression), I: 250 (2.5x, regression), V: 85 (1.06x, no)
        iteration_data = {
            "iteration": 2,
            "phase_r_duration_s": 90.0,
            "phase_i_duration_s": 250.0,
            "phase_v_duration_s": 85.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        has_regression, report = check_regression(
            iteration_file, baseline_file, multiplier=2.0
        )

        assert has_regression is True
        assert len(report["regressions"]) == 1
        assert report["regressions"][0]["phase"] == "I"

    def test_check_regression_custom_multiplier(self, tmp_path: Path) -> None:
        """Test regression detection with custom multiplier."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        baseline = {
            "rolling_window": [
                {"iteration": 1, "phases": {"I": 100.0}},
            ],
            "p50": {"I": 100.0},
            "p90": {"I": 100.0},
        }
        with open(baseline_file, "w") as f:
            json.dump(baseline, f)

        # Current: I = 150s
        iteration_data = {
            "iteration": 2,
            "phase_i_duration_s": 150.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        # With 2.0x multiplier: 150 < 200 → no regression
        has_regression, report = check_regression(
            iteration_file, baseline_file, multiplier=2.0
        )
        assert has_regression is False

        # With 1.4x multiplier: 150 > 140 → regression
        has_regression, report = check_regression(
            iteration_file, baseline_file, multiplier=1.4
        )
        assert has_regression is True


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_check_regression_missing_iteration_file(self, tmp_path: Path) -> None:
        """Test handling of missing iteration file."""
        iteration_file = tmp_path / "missing.json"
        baseline_file = tmp_path / "baseline.json"

        has_regression, report = check_regression(iteration_file, baseline_file)

        assert has_regression is False
        assert "error" in report

    def test_update_baseline_with_partial_phases(self, tmp_path: Path) -> None:
        """Test handling iterations with only some phases reported."""
        iteration_file = tmp_path / "iteration.json"
        baseline_file = tmp_path / "baseline.json"

        # Only R and I reported
        iteration_data = {
            "iteration": 1,
            "phase_r_duration_s": 45.0,
            "phase_i_duration_s": 150.0,
        }
        with open(iteration_file, "w") as f:
            json.dump(iteration_data, f)

        baseline = update_baseline(iteration_file, baseline_file)

        assert "R" in baseline["rolling_window"][0]["phases"]
        assert "I" in baseline["rolling_window"][0]["phases"]
        assert "T" not in baseline["rolling_window"][0]["phases"]
