"""tests/test_forecast_ceiling.py — Tests for forecast_ceiling module (US-699)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


class TestLoadResults:
    """Test load_results function."""

    def test_load_results_missing_file(self) -> None:
        """Missing results.tsv returns empty list."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import load_results

        result = load_results(Path("/nonexistent/results.tsv"))
        assert result == []

    def test_load_results_empty_file(self) -> None:
        """Empty results.tsv returns empty list."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import load_results

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            # Write header only
            f.write("spiral_iter\tcache_read_tokens\tcache_creation_tokens\treview_tokens\n")
            f.flush()
            temp_path = Path(f.name)

        try:
            result = load_results(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_load_results_single_row(self) -> None:
        """Single row results.tsv loads correctly."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import load_results

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("spiral_iter\tcache_read_tokens\tcache_creation_tokens\treview_tokens\n")
            f.write("1\t1000\t500\t0\n")
            f.flush()
            temp_path = Path(f.name)

        try:
            result = load_results(temp_path)
            assert len(result) == 1
            assert result[0]["spiral_iter"] == "1"
            assert result[0]["cache_read_tokens"] == "1000"
        finally:
            temp_path.unlink()


class TestComputeCostPerIteration:
    """Test compute_cost_per_iteration function."""

    def test_compute_empty_list(self) -> None:
        """Empty list returns empty dict."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import compute_cost_per_iteration

        result = compute_cost_per_iteration([])
        assert result == {}

    def test_compute_single_iteration(self) -> None:
        """Single iteration sums all token columns."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import compute_cost_per_iteration

        rows = [
            {
                "spiral_iter": "1",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "500",
                "review_tokens": "100",
            }
        ]
        result = compute_cost_per_iteration(rows)
        assert result == {1: 1600}

    def test_compute_multiple_iterations(self) -> None:
        """Multiple iterations aggregate correctly."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import compute_cost_per_iteration

        rows = [
            {
                "spiral_iter": "1",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "500",
                "review_tokens": "100",
            },
            {
                "spiral_iter": "1",
                "cache_read_tokens": "500",
                "cache_creation_tokens": "300",
                "review_tokens": "50",
            },
            {
                "spiral_iter": "2",
                "cache_read_tokens": "2000",
                "cache_creation_tokens": "1000",
                "review_tokens": "200",
            },
        ]
        result = compute_cost_per_iteration(rows)
        assert result == {1: 2450, 2: 3200}

    def test_compute_missing_fields(self) -> None:
        """Missing token fields default to 0."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import compute_cost_per_iteration

        rows = [{"spiral_iter": "1", "cache_read_tokens": "1000"}]
        result = compute_cost_per_iteration(rows)
        assert result == {1: 1000}

    def test_compute_invalid_iteration(self) -> None:
        """Invalid spiral_iter skipped."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import compute_cost_per_iteration

        rows = [
            {
                "spiral_iter": "invalid",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "500",
                "review_tokens": "100",
            }
        ]
        result = compute_cost_per_iteration(rows)
        assert result == {}


class TestForecastBreach:
    """Test forecast_breach function."""

    def test_forecast_empty_iterations(self) -> None:
        """Empty iterations returns no breach."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        result = forecast_breach(100.0, {})
        assert result["breach_iteration"] == -1
        assert result["confidence"] == "low"
        assert result["data_points"] == 0

    def test_forecast_low_confidence(self) -> None:
        """Less than 5 data points returns low confidence."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        iter_tokens = {1: 1000, 2: 2000, 3: 3000}
        result = forecast_breach(100.0, iter_tokens)
        assert result["confidence"] == "low"
        assert result["data_points"] == 3

    def test_forecast_high_confidence(self) -> None:
        """5+ data points returns high confidence."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        iter_tokens = {1: 1000, 2: 2000, 3: 3000, 4: 4000, 5: 5000}
        result = forecast_breach(100.0, iter_tokens)
        assert result["confidence"] == "high"
        assert result["data_points"] == 5

    def test_forecast_breach_projected(self) -> None:
        """Linear increase in tokens projects breach."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        # 5000 tokens/iteration, linear trend
        iter_tokens = {1: 5000, 2: 10000, 3: 15000, 4: 20000, 5: 25000}
        # Ceiling of $20 = 20,000 tokens
        result = forecast_breach(20.0, iter_tokens)
        assert result["breach_iteration"] > 0
        assert result["confidence"] == "high"
        assert result["burn_rate"] > 0

    def test_forecast_no_breach_flat_trend(self) -> None:
        """Flat tokens (no burn rate) projects breach very far in future."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        # Flat trend: same tokens every iteration
        iter_tokens = {1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 1000}
        result = forecast_breach(100.0, iter_tokens)
        # Flat trend has slope ≈ 0, so cumulative growth is very slow
        # Breach will be projected far in future (>50 iterations) or -1
        if result["breach_iteration"] > 0:
            assert result["breach_iteration"] > 50
        else:
            assert result["breach_iteration"] == -1

    def test_forecast_single_iteration(self) -> None:
        """Single iteration returns low confidence, no breach."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        iter_tokens = {1: 5000}
        result = forecast_breach(10.0, iter_tokens)
        assert result["confidence"] == "low"
        assert result["data_points"] == 1


class TestFormatForecast:
    """Test format_forecast function."""

    def test_format_no_breach(self) -> None:
        """Format message when no breach detected."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import format_forecast

        result = {
            "breach_iteration": -1,
            "confidence": "high",
            "data_points": 5,
            "burn_rate": 0.0,
        }
        msg = format_forecast(result, 100.0)
        assert "No breach detected" in msg
        assert "$100.00" in msg

    def test_format_breach_detected(self) -> None:
        """Format message when breach detected."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import format_forecast

        result = {
            "breach_iteration": 10.5,
            "confidence": "high",
            "data_points": 5,
            "burn_rate": 5000.0,
        }
        msg = format_forecast(result, 50.0)
        assert "10.5" in msg
        assert "5000" in msg or "5000.0" in msg

    def test_format_low_confidence_warning(self) -> None:
        """Low confidence adds warning."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import format_forecast

        result = {
            "breach_iteration": 8.0,
            "confidence": "low",
            "data_points": 2,
            "burn_rate": 3000.0,
        }
        msg = format_forecast(result, 50.0)
        assert "WARNING" in msg or "low confidence" in msg


class TestForecastCeilingCli:
    """Test forecast_ceiling_cli function."""

    def test_cli_with_results_file(self) -> None:
        """CLI processes results.tsv and returns forecast."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_ceiling_cli

        # Create temp results file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("spiral_iter\tcache_read_tokens\tcache_creation_tokens\treview_tokens\n")
            for i in range(1, 6):
                f.write(f"{i}\t{i * 5000}\t{i * 2000}\t{i * 500}\n")
            f.flush()
            results_path = Path(f.name)

        try:
            result = forecast_ceiling_cli(
                cost_ceiling=50.0,
                prd_path="prd.json",
                results_path=results_path,
                until_date=False,
            )
            assert "forecast" in result
            assert "message" in result
            assert result["cost_ceiling_usd"] == 50.0
            assert "data_source" in result
        finally:
            results_path.unlink()

    def test_cli_with_until_date(self) -> None:
        """CLI includes date when --until-date specified."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_ceiling_cli

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("spiral_iter\tcache_read_tokens\tcache_creation_tokens\treview_tokens\n")
            for i in range(1, 6):
                f.write(f"{i}\t{i * 5000}\t{i * 2000}\t{i * 500}\n")
            f.flush()
            results_path = Path(f.name)

        try:
            result = forecast_ceiling_cli(
                cost_ceiling=10.0,
                prd_path="prd.json",
                results_path=results_path,
                until_date=True,
            )
            assert isinstance(result, dict)
            # May or may not have projected_breach_date depending on whether breach occurs
            assert "message" in result
        finally:
            results_path.unlink()

    def test_cli_missing_results_file(self) -> None:
        """CLI handles missing results.tsv gracefully."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_ceiling_cli

        result = forecast_ceiling_cli(
            cost_ceiling=50.0,
            prd_path="prd.json",
            results_path=Path("/nonexistent/results.tsv"),
            until_date=False,
        )
        assert "forecast" in result
        # No data points, should return -1 breach
        assert result["forecast"]["data_points"] == 0


class TestIntegration:
    """Integration tests for full workflow."""

    def test_forecast_workflow(self) -> None:
        """Full workflow: load → compute → forecast → format."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import (
            compute_cost_per_iteration,
            forecast_breach,
            format_forecast,
            load_results,
        )

        # Create realistic results.tsv
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("spiral_iter\tcache_read_tokens\tcache_creation_tokens\treview_tokens\n")
            # 5 iterations with increasing token consumption
            for i in range(1, 6):
                read = i * 10000
                creation = i * 5000
                review = i * 1000
                f.write(f"{i}\t{read}\t{creation}\t{review}\n")
            f.flush()
            results_path = Path(f.name)

        try:
            rows = load_results(results_path)
            assert len(rows) == 5

            iter_tokens = compute_cost_per_iteration(rows)
            assert len(iter_tokens) == 5

            result = forecast_breach(50.0, iter_tokens)
            assert "breach_iteration" in result
            assert "confidence" in result
            assert result["confidence"] == "high"

            msg = format_forecast(result, 50.0)
            assert isinstance(msg, str)
            assert len(msg) > 0
        finally:
            results_path.unlink()

    def test_regression_linear_trend(self) -> None:
        """Test that linear regression correctly identifies trend."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from forecast_ceiling import forecast_breach

        # Perfect linear: 1000, 2000, 3000, 4000, 5000
        iter_tokens = {1: 1000, 2: 2000, 3: 3000, 4: 4000, 5: 5000}
        result = forecast_breach(10.0, iter_tokens)  # 10 * 1000 = 10000 tokens

        # Should detect breach at some future iteration
        assert result["breach_iteration"] > 0
        assert result["confidence"] == "high"
        assert result["burn_rate"] > 0
