#!/usr/bin/env python3
"""
tests/test_diminishing_returns.py — Unit tests for US-783 diminishing returns detection.

Tests verify that SPIRAL exits when cost-per-pass doubles 3 consecutive times.
"""

import tempfile
from pathlib import Path

import pytest

from lib.diminishing_returns import (
    calculate_cost_per_pass,
    check_diminishing_returns,
    detect_diminishing_returns,
    generate_diagnostic_report,
    parse_iteration_costs,
)


@pytest.fixture
def tmp_tsv():
    """Create a temporary TSV file that is closed before test runs."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
        path = f.name
    yield Path(path)
    # Cleanup
    Path(path).unlink(missing_ok=True)


class TestParseIterationCosts:
    """Test iteration cost parsing from results.tsv."""

    def test_parse_empty_file(self, tmp_tsv):
        """Parsing empty TSV returns empty dict."""
        tmp_tsv.write_text("timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\n")
        result = parse_iteration_costs(str(tmp_tsv))
        assert result == {}

    def test_parse_single_iteration(self, tmp_tsv):
        """Parse single iteration with one story."""
        content = (
            "timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\tcache_creation_tokens\n"
            "2026-03-23T00:00:00Z\t1\tUS-100\taccept\t1000\t100\n"
        )
        tmp_tsv.write_text(content)
        result = parse_iteration_costs(str(tmp_tsv))
        assert 1 in result
        assert result[1]["new_passes"] == 1
        assert result[1]["story_count"] == 1
        # Cost: 1000 * 0.0008 + 100 * 0.001 = 0.8 + 0.1 = $0.90
        assert result[1]["total_cost_usd"] == pytest.approx(0.9, abs=0.01)

    def test_parse_multiple_iterations(self, tmp_tsv):
        """Parse multiple iterations with varying pass counts."""
        content = (
            "timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\tcache_creation_tokens\n"
            "2026-03-23T00:00:00Z\t1\tUS-100\taccept\t1000\t100\n"
            "2026-03-23T00:01:00Z\t1\tUS-101\treject\t500\t50\n"
            "2026-03-23T00:02:00Z\t2\tUS-102\taccept\t2000\t200\n"
            "2026-03-23T00:03:00Z\t2\tUS-103\treject\t1000\t100\n"
        )
        tmp_tsv.write_text(content)
        result = parse_iteration_costs(str(tmp_tsv))

        assert len(result) == 2
        assert result[1]["new_passes"] == 1
        assert result[1]["story_count"] == 2
        assert result[2]["new_passes"] == 1
        assert result[2]["story_count"] == 2


class TestCalculateCostPerPass:
    """Test cost-per-pass calculation."""

    def test_single_pass(self):
        """Cost per pass with single passing story."""
        data = {
            1: {"new_passes": 1, "total_cost_usd": 1.0, "story_count": 1},
        }
        result = calculate_cost_per_pass(data)
        assert result[1] == 1.0

    def test_multiple_passes(self):
        """Cost per pass with multiple passing stories in one iteration."""
        data = {
            1: {"new_passes": 3, "total_cost_usd": 6.0, "story_count": 3},
        }
        result = calculate_cost_per_pass(data)
        assert result[1] == 2.0

    def test_no_passes(self):
        """Cost per pass when no stories pass (None)."""
        data = {
            1: {"new_passes": 0, "total_cost_usd": 1.0, "story_count": 1},
        }
        result = calculate_cost_per_pass(data)
        assert result[1] is None

    def test_multiple_iterations(self):
        """Cost per pass across multiple iterations."""
        data = {
            1: {"new_passes": 1, "total_cost_usd": 1.0, "story_count": 1},
            2: {"new_passes": 1, "total_cost_usd": 2.0, "story_count": 1},
            3: {"new_passes": 1, "total_cost_usd": 4.0, "story_count": 1},
        }
        result = calculate_cost_per_pass(data)
        assert result[1] == 1.0
        assert result[2] == 2.0
        assert result[3] == 4.0


class TestDetectDiminishingReturns:
    """Test diminishing returns detection (3 consecutive doublings)."""

    def test_no_doubling(self):
        """No doubling detected when costs are stable."""
        cpp = {1: 1.0, 2: 1.1, 3: 1.2}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=2.0)
        assert detected is False
        assert sequence == []

    def test_two_doublings_not_triggered(self):
        """Two doublings do not trigger (need 3 consecutive)."""
        cpp = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.5}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=2.0)
        assert detected is False
        assert sequence == []

    def test_three_consecutive_doublings(self):
        """Three consecutive doublings trigger exit."""
        cpp = {1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=2.0)
        assert detected is True
        assert len(sequence) == 3
        assert sequence[0] == (1, 1.0)
        assert sequence[1] == (2, 2.0)
        assert sequence[2] == (3, 4.0)

    def test_with_custom_multiplier(self):
        """Custom multiplier (1.5x instead of 2.0x)."""
        cpp = {1: 1.0, 2: 1.5, 3: 2.25}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=1.5)
        assert detected is True
        assert len(sequence) == 3

    def test_with_none_values(self):
        """None values are skipped when forming windows."""
        cpp = {1: 1.0, 2: None, 3: 2.0, 4: 4.0, 5: 8.0}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=2.0)
        # sorted_iters (non-None): [1, 3, 4, 5]
        # Window (1, 3, 4): 2.0 >= 1.0*2 (yes), 4.0 >= 2.0*2 (yes) -> triggers
        assert detected is True
        assert sequence[0] == (1, 1.0)

    def test_insufficient_iterations(self):
        """Less than 3 iterations cannot trigger."""
        cpp = {1: 1.0, 2: 2.0}
        detected, sequence = detect_diminishing_returns(cpp, multiplier=2.0)
        assert detected is False
        assert sequence == []


class TestGenerateDiagnosticReport:
    """Test diagnostic report generation."""

    def test_empty_data(self):
        """Report generated even with no data."""
        report = generate_diagnostic_report({}, {}, False)
        assert "DIMINISHING RETURNS ANALYSIS" in report
        assert "No iteration data available" in report

    def test_healthy_trend_report(self):
        """Report shows healthy trend when not diminishing."""
        iteration_data = {
            1: {"new_passes": 2, "total_cost_usd": 2.0, "story_count": 2},
            2: {"new_passes": 3, "total_cost_usd": 2.5, "story_count": 3},
        }
        cpp = {1: 1.0, 2: 0.83}
        report = generate_diagnostic_report(iteration_data, cpp, False)
        assert "✓ Cost-per-pass trend is healthy" in report
        assert "Continuing loop" in report

    def test_diminishing_return_report(self):
        """Report shows warning when diminishing returns detected."""
        iteration_data = {
            1: {"new_passes": 1, "total_cost_usd": 1.0, "story_count": 1},
            2: {"new_passes": 1, "total_cost_usd": 2.0, "story_count": 1},
            3: {"new_passes": 1, "total_cost_usd": 4.0, "story_count": 1},
        }
        cpp = {1: 1.0, 2: 2.0, 3: 4.0}
        sequence = [(1, 1.0), (2, 2.0), (3, 4.0)]
        report = generate_diagnostic_report(iteration_data, cpp, True, sequence)
        assert "⚠️  DIMINISHING RETURNS DETECTED" in report
        assert "Exit loop to avoid budget waste" in report
        assert "Iteration 1: $1.00" in report


class TestCheckDiminishingReturns:
    """Integration test: check_diminishing_returns main entry point."""

    def test_no_results_file(self):
        """No results file returns False."""
        should_exit, report = check_diminishing_returns("/nonexistent/path.tsv")
        assert should_exit is False
        assert report == ""

    def test_doubling_cost_per_pass(self, tmp_tsv):
        """Main test: cost-per-pass $1→$2→$4→$8 triggers exit."""
        content = (
            "timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\tcache_creation_tokens\n"
            "2026-03-23T00:00:00Z\t1\tUS-100\taccept\t1250\t0\n"
            "2026-03-23T00:01:00Z\t2\tUS-101\taccept\t2500\t0\n"
            "2026-03-23T00:02:00Z\t3\tUS-102\taccept\t5000\t0\n"
            "2026-03-23T00:03:00Z\t4\tUS-103\taccept\t10000\t0\n"
        )
        tmp_tsv.write_text(content)
        should_exit, report = check_diminishing_returns(str(tmp_tsv), multiplier=2.0)
        assert should_exit is True
        assert "DIMINISHING RETURNS DETECTED" in report
        assert "budget waste" in report

    def test_no_diminishing_returns(self, tmp_tsv):
        """Stable cost-per-pass does not trigger exit."""
        content = (
            "timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\tcache_creation_tokens\n"
            "2026-03-23T00:00:00Z\t1\tUS-100\taccept\t1250\t0\n"
            "2026-03-23T00:01:00Z\t2\tUS-101\taccept\t1250\t0\n"
            "2026-03-23T00:02:00Z\t3\tUS-102\taccept\t1250\t0\n"
        )
        tmp_tsv.write_text(content)
        should_exit, report = check_diminishing_returns(str(tmp_tsv), multiplier=2.0)
        assert should_exit is False

    def test_single_iteration(self, tmp_tsv):
        """Single iteration cannot trigger (need 3)."""
        content = (
            "timestamp\tspiral_iter\tstory_id\tstatus\tcache_read_tokens\tcache_creation_tokens\n"
            "2026-03-23T00:00:00Z\t1\tUS-100\taccept\t1250\t0\n"
        )
        tmp_tsv.write_text(content)
        should_exit, report = check_diminishing_returns(str(tmp_tsv), multiplier=2.0)
        assert should_exit is False
