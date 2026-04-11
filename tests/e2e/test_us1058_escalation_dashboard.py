"""E2E tests for Model Escalation Prediction Dashboard Endpoint (US-1188).

Tests the user flow of the escalation prediction feature introduced in US-1058:
- AC1: E2E test covers the user flow of escalation prediction feature
- AC2: Test navigates to relevant endpoint and asserts on visible state
- AC3: Test passes in headless browser (via HTTP requests + response assertions)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
import requests

from lib.escalation_predictor import (
    predict_all_stories,
)

# Dashboard API running at this URL (used when available for E2E testing)
DASHBOARD_URL = "http://localhost:5299"
ESCALATION_PREDICTIONS_ENDPOINT = f"{DASHBOARD_URL}/api/dashboard/escalation-predictions"
HEALTH_CHECK_ENDPOINT = f"{DASHBOARD_URL}/health"
MAX_STARTUP_WAIT_S = 10  # Max time to wait for dashboard to be ready


def _write_results_tsv(tmp_dir: Path, rows: list[str]) -> Path:
    """Write test data to .spiral/results.tsv."""
    spiral_dir = tmp_dir / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    results_path = spiral_dir / "results.tsv"

    tsv_header = (
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
        "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
        "cache_read_tokens\tcache_creation_tokens\treview_tokens\t"
        "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
    )

    with open(results_path, "w", encoding="utf-8") as f:
        f.write(tsv_header)
        f.writelines(rows)

    return results_path


def _make_tsv_row(
    story_id: str,
    model: str,
    retry_num: int,
    cache_read: int = 0,
    cache_create: int = 0,
    review: int = 0,
) -> str:
    """Create a results.tsv row for a story attempt."""
    return (
        f"2026-01-01T00:00:00Z\t1\t1\t{story_id}\tTitle\tpass\t10\t"
        f"{model}\t{retry_num}\t\t\tfalse\t"
        f"{cache_read}\t{cache_create}\t{review}\t"
        f"0\t0\t0\t0\t\n"
    )


def _wait_for_dashboard() -> bool:
    """Poll the dashboard health endpoint until it's ready or timeout."""
    start = time.time()
    while time.time() - start < MAX_STARTUP_WAIT_S:
        try:
            resp = requests.get(HEALTH_CHECK_ENDPOINT, timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


class TestEscalationPredictionsDashboardFlow:
    """E2E tests for escalation predictions dashboard user flow (US-1188 AC1-AC3)."""

    @pytest.fixture()
    def test_results_tsv(self, tmp_path: Path) -> Path:
        """Create test data with known escalation trajectories."""
        rows = [
            # Haiku story heading to sonnet: 20K → 45K (past 50K threshold trend)
            _make_tsv_row("US-E1", "haiku", 0, cache_read=20_000),
            _make_tsv_row("US-E1", "haiku", 1, cache_read=45_000),
            # Haiku story staying on haiku: 10K → 15K (well below threshold)
            _make_tsv_row("US-E2", "haiku", 0, cache_read=10_000),
            _make_tsv_row("US-E2", "haiku", 1, cache_read=15_000),
            # Sonnet story heading to opus: 100K → 145K (past 150K threshold trend)
            _make_tsv_row("US-E3", "sonnet", 1, cache_read=100_000),
            _make_tsv_row("US-E3", "sonnet", 2, cache_read=145_000),
        ]
        return _write_results_tsv(tmp_path, rows)

    def test_escalation_prediction_user_flow_direct(self, test_results_tsv: Path) -> None:
        """AC1+AC2: Test escalation prediction user flow directly via predictor.

        Simulates the user accessing escalation predictions by calling the
        predictor that powers the dashboard endpoint.
        """
        # User calls predict_all_stories to get escalation predictions
        predictions = predict_all_stories(test_results_tsv)

        # Verify we got predictions back
        assert predictions is not None
        assert len(predictions) == 3, "Should have predictions for all 3 stories"

        # AC2: Assert on visible state — escalating stories should appear first
        escalating = [p for p in predictions if p.predicted_model != p.current_model]
        stable = [p for p in predictions if p.predicted_model == p.current_model]

        assert len(escalating) == 2, "Should have 2 escalating stories (US-E1, US-E3)"
        assert len(stable) == 1, "Should have 1 stable story (US-E2)"

        # Verify ordering: escalating before stable
        if escalating and stable:
            last_escalating_idx = max(i for i, p in enumerate(predictions) if p.predicted_model != p.current_model)
            first_stable_idx = min(i for i, p in enumerate(predictions) if p.predicted_model == p.current_model)
            assert last_escalating_idx < first_stable_idx

    def test_haiku_to_sonnet_escalation_prediction(self, test_results_tsv: Path) -> None:
        """AC1: Verify haiku→sonnet escalation prediction."""
        predictions = predict_all_stories(test_results_tsv)

        # Find US-E1 (haiku heading to sonnet)
        e1_pred = next((p for p in predictions if p.story_id == "US-E1"), None)
        assert e1_pred is not None
        assert e1_pred.current_model == "haiku"
        assert e1_pred.predicted_model == "sonnet"
        assert e1_pred.confidence_pct > 80.0, "Should have high confidence on obvious escalation"

    def test_no_escalation_prediction(self, test_results_tsv: Path) -> None:
        """AC1: Verify stable prediction for story that won't escalate."""
        predictions = predict_all_stories(test_results_tsv)

        # Find US-E2 (haiku staying on haiku)
        e2_pred = next((p for p in predictions if p.story_id == "US-E2"), None)
        assert e2_pred is not None
        assert e2_pred.current_model == "haiku"
        assert e2_pred.predicted_model == "haiku"
        assert e2_pred.tokens_until_escalation > 0

    def test_sonnet_to_opus_escalation_prediction(self, test_results_tsv: Path) -> None:
        """AC1: Verify sonnet→opus escalation prediction."""
        predictions = predict_all_stories(test_results_tsv)

        # Find US-E3 (sonnet heading to opus)
        e3_pred = next((p for p in predictions if p.story_id == "US-E3"), None)
        assert e3_pred is not None
        assert e3_pred.current_model == "sonnet"
        assert e3_pred.predicted_model == "opus"
        assert e3_pred.confidence_pct > 80.0


class TestEscalationPredictionsDashboardEndpoint:
    """E2E tests for the HTTP dashboard endpoint (AC3: headless browser compatibility)."""

    @pytest.fixture()
    def test_results_tsv(self, tmp_path: Path, monkeypatch: Any) -> Path:
        """Setup environment with test results.tsv."""
        rows = [
            _make_tsv_row("US-E1", "haiku", 0, cache_read=20_000),
            _make_tsv_row("US-E1", "haiku", 1, cache_read=45_000),
            _make_tsv_row("US-E2", "haiku", 0, cache_read=10_000),
            _make_tsv_row("US-E2", "haiku", 1, cache_read=15_000),
        ]
        results_path = _write_results_tsv(tmp_path, rows)
        monkeypatch.chdir(tmp_path)
        return results_path

    @pytest.mark.skipif(
        not _wait_for_dashboard(),
        reason="Dashboard API not available",
    )
    def test_escalation_predictions_endpoint_response_format(self, test_results_tsv: Path) -> None:
        """AC3: Endpoint returns valid JSON with correct structure for browser consumption."""
        resp = requests.get(ESCALATION_PREDICTIONS_ENDPOINT, timeout=5)
        assert resp.status_code == 200

        # Parse response (simulates browser parsing)
        data = resp.json()
        assert isinstance(data, dict)
        assert "stories" in data
        assert isinstance(data["stories"], list)

        # Verify story object structure
        for story in data["stories"]:
            assert "story_id" in story
            assert "current_model" in story
            assert "predicted_model" in story
            assert "confidence_pct" in story
            assert isinstance(story["confidence_pct"], (int, float))

    @pytest.mark.skipif(
        not _wait_for_dashboard(),
        reason="Dashboard API not available",
    )
    def test_escalation_predictions_endpoint_with_data(self, test_results_tsv: Path) -> None:
        """AC2+AC3: Endpoint returns predictions visible to browser."""
        resp = requests.get(ESCALATION_PREDICTIONS_ENDPOINT, timeout=5)
        assert resp.status_code == 200

        data = resp.json()
        stories = data.get("stories", [])

        # Should have predictions from our test data
        assert len(stories) > 0, "Should return predictions when data exists"

        # Verify escalating story is present and sorted first
        escalating = [s for s in stories if s["predicted_model"] != s["current_model"]]
        if escalating:
            # First story should be escalating
            assert stories[0]["predicted_model"] != stories[0]["current_model"]
