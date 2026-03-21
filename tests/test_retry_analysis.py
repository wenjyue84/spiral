"""tests/test_retry_analysis.py — Retry analysis module tests (US-655)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


from retry_analysis import compute_retry_rates, compute_retry_stats, load_results


class TestLoadResults:
    """Tests for load_results function."""

    def test_load_results_missing_file(self, tmp_path: Path) -> None:
        """Test load_results with missing file returns empty list."""
        missing = tmp_path / "missing.tsv"
        result = load_results(missing)
        assert result == []

    def test_load_results_empty_file(self, tmp_path: Path) -> None:
        """Test load_results with empty file returns empty list."""
        empty_file = tmp_path / "empty.tsv"
        empty_file.write_text("phase\tretry_count\n")
        result = load_results(empty_file)
        assert result == []

    def test_load_results_single_row(self, tmp_path: Path) -> None:
        """Test load_results with single data row."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text("phase\tretry_count\nI\t2\n")
        result = load_results(tsv_file)
        assert len(result) == 1
        assert result[0]["phase"] == "I"
        assert result[0]["retry_count"] == "2"


class TestComputeRetryStats:
    """Tests for compute_retry_stats function."""

    def test_compute_retry_stats_empty(self) -> None:
        """Test compute_retry_stats with empty results."""
        result = compute_retry_stats([])
        assert result == {}

    def test_compute_retry_stats_single_phase(self) -> None:
        """Test compute_retry_stats with single phase."""
        results = [
            {"phase": "I", "retry_count": "1"},
            {"phase": "I", "retry_count": "2"},
            {"phase": "I", "retry_count": "3"},
        ]
        result = compute_retry_stats(results)
        assert "I" in result
        assert result["I"]["count"] == 3
        assert result["I"]["mean"] == 2.0
        assert result["I"]["median"] == 2
        assert result["I"]["max"] == 3
        assert result["I"]["story_count"] == 3

    def test_compute_retry_stats_multi_phase(self) -> None:
        """Test compute_retry_stats with multiple phases."""
        results = [
            {"phase": "R", "retry_count": "0"},
            {"phase": "R", "retry_count": "1"},
            {"phase": "I", "retry_count": "2"},
            {"phase": "I", "retry_count": "3"},
            {"phase": "I", "retry_count": "4"},
        ]
        result = compute_retry_stats(results)
        assert len(result) == 2
        assert result["I"]["count"] == 3
        assert result["R"]["count"] == 2
        assert result["I"]["mean"] == 3.0
        assert result["R"]["mean"] == 0.5

    def test_compute_retry_stats_missing_phase(self) -> None:
        """Test compute_retry_stats with missing phase field."""
        results = [
            {"retry_count": "1"},
            {"phase": "I", "retry_count": "2"},
        ]
        result = compute_retry_stats(results)
        assert "UNKNOWN" in result
        assert "I" in result
        assert result["UNKNOWN"]["count"] == 1
        assert result["I"]["count"] == 1

    def test_compute_retry_stats_invalid_retry_count(self) -> None:
        """Test compute_retry_stats handles non-numeric retry_count."""
        results = [
            {"phase": "I", "retry_count": "invalid"},
            {"phase": "I", "retry_count": "2"},
        ]
        result = compute_retry_stats(results)
        assert result["I"]["count"] == 2
        # First story gets 0 retries (parse error)
        assert result["I"]["max"] == 2

    def test_compute_retry_stats_retry_rate(self) -> None:
        """Test compute_retry_stats calculates retry_rate correctly."""
        results = [
            {"phase": "I", "retry_count": "0"},
            {"phase": "I", "retry_count": "2"},
            {"phase": "I", "retry_count": "4"},
        ]
        result = compute_retry_stats(results)
        # Total retries: 0 + 2 + 4 = 6, count = 3, rate = 6/3 = 2.0
        assert result["I"]["retry_rate"] == 2.0


class TestComputeRetryRates:
    """Tests for compute_retry_rates function."""

    def test_compute_retry_rates_empty(self) -> None:
        """Test compute_retry_rates with empty results."""
        result = compute_retry_rates([])
        assert result == []

    def test_compute_retry_rates_single_phase(self) -> None:
        """Test compute_retry_rates with single phase."""
        results = [
            {"phase": "I", "retry_count": "1"},
            {"phase": "I", "retry_count": "2"},
        ]
        result = compute_retry_rates(results)
        assert len(result) == 1
        assert result[0]["phase"] == "I"
        assert result[0]["story_count"] == 2

    def test_compute_retry_rates_sorted_descending(self) -> None:
        """Test compute_retry_rates sorts by retry_rate descending."""
        results = [
            {"phase": "R", "retry_count": "0"},
            {"phase": "R", "retry_count": "0"},
            {"phase": "I", "retry_count": "2"},
            {"phase": "I", "retry_count": "4"},
            {"phase": "I", "retry_count": "6"},
            {"phase": "V", "retry_count": "1"},
        ]
        result = compute_retry_rates(results)
        # I: (2+4+6)/3 = 4.0, V: 1/1 = 1.0, R: 0/2 = 0.0
        assert result[0]["phase"] == "I"
        assert result[1]["phase"] == "V"
        assert result[2]["phase"] == "R"

    def test_compute_retry_rates_has_required_fields(self) -> None:
        """Test compute_retry_rates output has required fields."""
        results = [
            {"phase": "I", "retry_count": "2"},
        ]
        result = compute_retry_rates(results)
        assert len(result) == 1
        assert "phase" in result[0]
        assert "retry_rate" in result[0]
        assert "story_count" in result[0]


class TestRetryAnalysisIntegration:
    """Integration tests with 15 mock stories."""

    def test_integration_15_stories_across_phases(self) -> None:
        """Test with 15 stories across 6 phases with varying retry counts."""
        results = [
            # R phase: 2 stories
            {"phase": "R", "retry_count": "0"},
            {"phase": "R", "retry_count": "1"},
            # T phase: 3 stories
            {"phase": "T", "retry_count": "0"},
            {"phase": "T", "retry_count": "0"},
            {"phase": "T", "retry_count": "2"},
            # S phase: 2 stories
            {"phase": "S", "retry_count": "1"},
            {"phase": "S", "retry_count": "1"},
            # M phase: 3 stories
            {"phase": "M", "retry_count": "0"},
            {"phase": "M", "retry_count": "1"},
            {"phase": "M", "retry_count": "2"},
            # I phase: 3 stories
            {"phase": "I", "retry_count": "3"},
            {"phase": "I", "retry_count": "5"},
            {"phase": "I", "retry_count": "2"},
            # V phase: 2 stories
            {"phase": "V", "retry_count": "0"},
            {"phase": "V", "retry_count": "1"},
        ]

        stats = compute_retry_stats(results)
        assert len(stats) == 6
        assert all(phase in stats for phase in ["R", "T", "S", "M", "I", "V"])

        rates = compute_retry_rates(results)
        assert len(rates) == 6
        # I should be first (highest retry_rate): (3+5+2)/3 = 3.33
        assert rates[0]["phase"] == "I"
        assert rates[0]["story_count"] == 3
        assert rates[0]["retry_rate"] == 3.3333

        # Verify total stories
        total_stories = sum(r["story_count"] for r in rates)
        assert total_stories == 15

    def test_integration_all_zero_retries(self) -> None:
        """Test with all stories having zero retries."""
        results = [
            {"phase": "I", "retry_count": "0"},
            {"phase": "I", "retry_count": "0"},
            {"phase": "I", "retry_count": "0"},
        ]
        stats = compute_retry_stats(results)
        assert stats["I"]["retry_rate"] == 0.0

        rates = compute_retry_rates(results)
        assert rates[0]["retry_rate"] == 0.0

    def test_integration_all_high_retries(self) -> None:
        """Test with all stories having high retry counts."""
        results = [
            {"phase": "I", "retry_count": "5"},
            {"phase": "I", "retry_count": "5"},
            {"phase": "I", "retry_count": "5"},
        ]
        stats = compute_retry_stats(results)
        assert stats["I"]["retry_rate"] == 5.0

        rates = compute_retry_rates(results)
        assert rates[0]["retry_rate"] == 5.0
