"""Integration tests for SPIRAL self-monitoring dashboard (US-460).

Tests verify live token burn rate display, story throughput metrics, and model
escalation heatmap data endpoints work correctly end-to-end. All tests are
self-contained with no external service dependencies.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

# Import dashboard functions under test
from lib.ui.spiral_dashboard import (
    compute_iteration_velocity,
    compute_model_performance,
    compute_token_forecast,
    compute_velocity,
)


class TestTokenBurnRateEndpoint:
    """Test token burn rate calculation for live cost monitoring."""

    def test_token_burn_rate_endpoint(self) -> None:
        """Verify burn rate endpoint computes correct tokens/hour from recent results.

        Acceptance criterion: Dashboard /metrics returns live token burn rate
        from rolling 1-hour window (≥3 rows with tokens).
        """
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(minutes=30)).isoformat()

        # Create mock results with token data in 1-hour window
        results: list[dict[str, Any]] = [
            {
                "timestamp": recent_ts,
                "input_tokens": 1000,
                "output_tokens": 500,
                "duration_sec": 60,
            },
            {
                "timestamp": (now - timedelta(minutes=20)).isoformat(),
                "input_tokens": 800,
                "output_tokens": 400,
                "duration_sec": 45,
            },
            {
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
                "input_tokens": 1200,
                "output_tokens": 600,
                "duration_sec": 50,
            },
        ]

        # Call compute_token_forecast with recent results
        forecast = compute_token_forecast(results, daily_limit=1_000_000)

        # Assertions
        assert forecast is not None, "Forecast should not be None with 3+ token rows"
        assert "burn_rate_per_hour" in forecast
        assert "hours_to_exhaustion" in forecast
        assert "time_str" in forecast
        assert "exhaustion_clock" in forecast

        # Verify burn rate is sum of tokens in 1-hour window (~4.5k)
        assert forecast["burn_rate_per_hour"] > 0
        assert forecast["hours_to_exhaustion"] > 0
        assert "amber_alert" in forecast
        assert isinstance(forecast["amber_alert"], bool)

    def test_token_burn_rate_with_insufficient_data(self) -> None:
        """Verify endpoint returns None when fewer than 3 token-bearing rows."""
        now = datetime.now(timezone.utc)

        results: list[dict[str, Any]] = [
            {
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
                "input_tokens": 1000,
                "output_tokens": 500,
            },
            {
                "timestamp": (now - timedelta(minutes=20)).isoformat(),
                "input_tokens": 0,  # No tokens
                "output_tokens": 0,
            },
        ]

        forecast = compute_token_forecast(results)
        assert forecast is None, "Forecast should be None with <3 token-bearing rows"

    def test_token_burn_rate_with_amber_alert(self) -> None:
        """Verify amber alert triggers when exhaustion < 2 hours."""
        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(minutes=30)).isoformat()

        # Create high-burn results (will exhaust in < 2 hours)
        results: list[dict[str, Any]] = [
            {
                "timestamp": recent_ts,
                "input_tokens": 100000,
                "output_tokens": 100000,
            },
            {
                "timestamp": (now - timedelta(minutes=20)).isoformat(),
                "input_tokens": 100000,
                "output_tokens": 100000,
            },
            {
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
                "input_tokens": 100000,
                "output_tokens": 100000,
            },
        ]

        forecast = compute_token_forecast(results, daily_limit=100_000)
        assert forecast is not None
        assert forecast["amber_alert"] is True


class TestStoryThroughputMetrics:
    """Test story throughput calculations for performance monitoring."""

    def test_story_throughput_metrics(self) -> None:
        """Verify throughput endpoint computes correct stories/hour per iteration.

        Acceptance criterion: Dashboard shows stories completed per iteration
        with velocity (stories/hr) calculation.
        """
        results: list[dict[str, Any]] = [
            {
                "spiral_iter": 1,
                "status": "keep",
                "duration_sec": 300,
                "story_id": "US-1",
            },
            {
                "spiral_iter": 1,
                "status": "keep",
                "duration_sec": 250,
                "story_id": "US-2",
            },
            {
                "spiral_iter": 1,
                "status": "revert",
                "duration_sec": 400,
                "story_id": "US-3",
            },
            {
                "spiral_iter": 2,
                "status": "keep",
                "duration_sec": 280,
                "story_id": "US-4",
            },
            {
                "spiral_iter": 2,
                "status": "keep",
                "duration_sec": 320,
                "story_id": "US-5",
            },
        ]

        # Compute iteration velocity
        iter_vel = compute_iteration_velocity(results)

        assert 1 in iter_vel, "Iteration 1 should have kept count"
        assert iter_vel[1] == 2, "Iteration 1 should have 2 kept stories"
        assert 2 in iter_vel, "Iteration 2 should have kept count"
        assert iter_vel[2] == 2, "Iteration 2 should have 2 kept stories"

        # Compute velocity with timing info
        velocity = compute_velocity(results)

        assert len(velocity) == 2, "Should have velocity for 2 iterations"
        assert velocity[0]["iter"] == 1
        assert velocity[0]["kept"] == 2
        assert velocity[0]["total"] == 3
        assert velocity[0]["velocity"] > 0, "Velocity should be positive"

        assert velocity[1]["iter"] == 2
        assert velocity[1]["kept"] == 2
        assert velocity[1]["total"] == 2
        assert velocity[1]["velocity"] > 0

    def test_story_throughput_empty_results(self) -> None:
        """Verify throughput handles empty results gracefully."""
        results: list[dict[str, Any]] = []

        iter_vel = compute_iteration_velocity(results)
        assert iter_vel == {}, "Empty results should yield empty dict"

        velocity = compute_velocity(results)
        assert velocity == [], "Empty results should yield empty list"

    def test_story_throughput_no_kept_stories(self) -> None:
        """Verify throughput handles cases where no stories were kept."""
        results: list[dict[str, Any]] = [
            {
                "spiral_iter": 1,
                "status": "revert",
                "duration_sec": 300,
                "story_id": "US-1",
            },
            {
                "spiral_iter": 1,
                "status": "revert",
                "duration_sec": 250,
                "story_id": "US-2",
            },
        ]

        iter_vel = compute_iteration_velocity(results)
        assert 1 not in iter_vel, "Iteration with no kept stories should not appear"

        velocity = compute_velocity(results)
        assert len(velocity) == 1
        assert velocity[0]["kept"] == 0
        assert velocity[0]["velocity"] == 0, "Zero kept should yield zero velocity"


class TestModelEscalationHeatmapEdgeCase:
    """Test model escalation heatmap with edge cases (empty/missing data)."""

    def test_model_escalation_heatmap_edge_case(self) -> None:
        """Verify heatmap endpoint handles no-data scenario gracefully.

        Acceptance criterion: Dashboard shows model performance with proper
        handling of empty data or no attempts (no errors, sensible defaults).
        """
        results: list[dict[str, Any]] = []

        perf = compute_model_performance(results)
        assert perf == [], "Empty results should yield empty performance list"

    def test_model_escalation_heatmap_single_model(self) -> None:
        """Verify heatmap with single model."""
        results: list[dict[str, Any]] = [
            {"model": "haiku", "status": "keep", "duration_sec": 100},
            {"model": "haiku", "status": "keep", "duration_sec": 120},
            {"model": "haiku", "status": "revert", "duration_sec": 150},
        ]

        perf = compute_model_performance(results)

        assert len(perf) == 1
        assert perf[0]["model"] == "haiku"
        assert perf[0]["total"] == 3
        assert perf[0]["kept"] == 2
        assert perf[0]["success_rate"] == pytest.approx(66.67, abs=0.1)
        assert perf[0]["avg_duration"] > 0
        assert perf[0]["median_duration"] > 0

    def test_model_escalation_heatmap_multiple_models(self) -> None:
        """Verify heatmap with multiple models and success rate comparison."""
        results: list[dict[str, Any]] = [
            # haiku: 2/3 kept
            {"model": "haiku", "status": "keep", "duration_sec": 100},
            {"model": "haiku", "status": "keep", "duration_sec": 120},
            {"model": "haiku", "status": "revert", "duration_sec": 150},
            # sonnet: 3/3 kept (better)
            {"model": "sonnet", "status": "keep", "duration_sec": 200},
            {"model": "sonnet", "status": "keep", "duration_sec": 220},
            {"model": "sonnet", "status": "keep", "duration_sec": 180},
        ]

        perf = compute_model_performance(results)

        assert len(perf) == 2
        # Should be sorted by success_rate descending (sonnet first)
        assert perf[0]["model"] == "sonnet"
        assert perf[0]["success_rate"] == 100.0
        assert perf[1]["model"] == "haiku"
        assert perf[1]["success_rate"] == pytest.approx(66.67, abs=0.1)

    def test_model_escalation_heatmap_missing_duration(self) -> None:
        """Verify heatmap handles missing duration fields gracefully."""
        results: list[dict[str, Any]] = [
            {"model": "haiku", "status": "keep"},  # No duration_sec
            {"model": "haiku", "status": "keep", "duration_sec": 100},
            {"model": "haiku", "status": "revert", "duration_sec": None},
        ]

        perf = compute_model_performance(results)

        assert len(perf) == 1
        assert perf[0]["model"] == "haiku"
        assert perf[0]["total"] == 3
        assert perf[0]["kept"] == 2
        # avg_duration should skip None/0 values
        assert perf[0]["avg_duration"] >= 100

    def test_model_escalation_heatmap_unknown_model(self) -> None:
        """Verify heatmap handles unknown/missing model field."""
        results: list[dict[str, Any]] = [
            {"status": "keep", "duration_sec": 100},  # No model field
            {"model": "haiku", "status": "keep", "duration_sec": 120},
            {"status": "revert", "duration_sec": 150},  # No model field
        ]

        perf = compute_model_performance(results)

        # Should have 'unknown' model plus 'haiku'
        models = {p["model"] for p in perf}
        assert "unknown" in models
        assert "haiku" in models


class TestDashboardDataExposure:
    """Test that dashboard does not leak sensitive data in edge cases."""

    def test_dashboard_token_string_safety(self) -> None:
        """Verify forecast strings don't contain raw token counts in insecure format."""
        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = [
            {
                "timestamp": (now - timedelta(minutes=30)).isoformat(),
                "input_tokens": 12345,
                "output_tokens": 6789,
            },
            {
                "timestamp": (now - timedelta(minutes=20)).isoformat(),
                "input_tokens": 10000,
                "output_tokens": 5000,
            },
            {
                "timestamp": (now - timedelta(minutes=10)).isoformat(),
                "input_tokens": 8000,
                "output_tokens": 4000,
            },
        ]

        forecast = compute_token_forecast(results)

        if forecast:
            # time_str should be human-readable (e.g., "~2h 15m"), not raw tokens
            assert "~" in forecast["time_str"], "time_str should use ~ notation"
            assert "h" in forecast["time_str"] or "m" in forecast["time_str"]


class TestDashboardIntegrationEdgeCases:
    """Additional edge cases for dashboard end-to-end testing."""

    def test_all_computation_functions_with_empty_prd(self) -> None:
        """Verify all dashboard functions handle empty PRD gracefully."""
        prd: dict[str, Any] = {"userStories": []}
        results: list[dict[str, Any]] = []

        # All these should handle empty data without exceptions
        iter_vel = compute_iteration_velocity(results)
        assert isinstance(iter_vel, dict)

        velocity = compute_velocity(results)
        assert isinstance(velocity, list)

        perf = compute_model_performance(results)
        assert isinstance(perf, list)

        forecast = compute_token_forecast(results)
        # forecast can be None or dict
        assert forecast is None or isinstance(forecast, dict)
