#!/usr/bin/env python3
"""Tests for lib/llm_router.py calibration features (US-1093)."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from llm_router import (
    TIER_TO_MODEL,
    CalibrationMetric,
    LlmRouter,
    ModelTier,
    compute_calibration,
    load_calibration,
    save_calibration,
)


class TestComputeCalibration:
    """Test compute_calibration() with mock results.tsv data."""

    def test_compute_with_50_mock_entries(self, tmp_path: Path) -> None:
        """Test compute_calibration with 50 mock results.tsv entries (AC2)."""
        results_path = tmp_path / "results.tsv"

        # Generate 50 mock entries: varied models, complexities, statuses, costs
        models = ["haiku", "sonnet", "opus"]
        complexities = ["small", "medium", "large"]
        rows = [
            {
                "model": models[i % 3],
                "status": "pass" if (i % 3) == 0 else "reject",  # ~33% pass rate
                "estimatedComplexity": complexities[i % 3],
                "cache_read_tokens": str((i + 1) * 1000),
                "cache_creation_tokens": str((i + 1) * 500),
            }
            for i in range(50)
        ]

        # Write TSV
        with open(results_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

        # Compute calibration
        metrics = compute_calibration(str(results_path))

        # Verify structure and content
        assert len(metrics) > 0, "Should have computed some metrics"
        assert all(isinstance(m, CalibrationMetric) for m in metrics.values())

        # Each metric should have sensible values
        for (model, complexity), metric in metrics.items():
            assert metric.model == model
            assert metric.complexity == complexity
            assert metric.total_count > 0
            assert 0 <= metric.success_count <= metric.total_count
            assert metric.avg_cost_per_pass >= 0

    def test_compute_with_empty_file(self, tmp_path: Path) -> None:
        """Test compute_calibration with empty/headerless TSV."""
        results_path = tmp_path / "empty.tsv"
        results_path.write_text("")

        metrics = compute_calibration(str(results_path))
        assert metrics == {}

    def test_compute_missing_file(self, tmp_path: Path) -> None:
        """Test compute_calibration with missing results.tsv (AC3)."""
        metrics = compute_calibration(str(tmp_path / "nonexistent.tsv"))
        assert metrics == {}


class TestLoadAndSaveCalibration:
    """Test load_calibration() and save_calibration() persistence."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Test save → load roundtrip preserves metrics."""
        calib_path = tmp_path / "routing_calibration.json"

        # Create test metrics
        metrics = {
            ("haiku", "small"): CalibrationMetric(
                model="haiku",
                complexity="small",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1500.0,
            ),
            ("sonnet", "medium"): CalibrationMetric(
                model="sonnet",
                complexity="medium",
                success_count=35,
                total_count=50,
                avg_cost_per_pass=3500.0,
            ),
        }

        # Save
        save_calibration(metrics, str(calib_path))
        assert calib_path.exists()

        # Load
        loaded = load_calibration(str(calib_path))
        assert loaded is not None
        assert len(loaded) == len(metrics)

        # Verify keys and values
        for key, original_metric in metrics.items():
            assert key in loaded
            loaded_metric = loaded[key]
            assert loaded_metric.model == original_metric.model
            assert loaded_metric.success_count == original_metric.success_count
            assert loaded_metric.avg_cost_per_pass == original_metric.avg_cost_per_pass

    def test_load_nonexistent_file(self) -> None:
        """Test load_calibration with missing file returns None."""
        result = load_calibration("/nonexistent/path/routing_calibration.json")
        assert result is None

    def test_load_malformed_json(self, tmp_path: Path) -> None:
        """Test load_calibration with malformed JSON returns None."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json")

        result = load_calibration(str(bad_json))
        assert result is None


class TestCalibratedRouting:
    """Test that calibrated routing affects tier selection."""

    def test_calibrated_routing_differs_from_static(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that calibrated routing can produce different tier than static routing (AC4)."""
        # Set up calibration: sonnet is 2x cost for <10% quality gain over haiku in medium complexity
        # This should cause the router to skip sonnet and return haiku on retry 0
        metrics = {
            ("haiku", "medium"): CalibrationMetric(
                model="haiku",
                complexity="medium",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
            ("sonnet", "medium"): CalibrationMetric(
                model="sonnet",
                complexity="medium",
                success_count=41,  # Only 2% better
                total_count=50,
                avg_cost_per_pass=2100.0,  # 2.1x cost
            ),
        }

        # Save calibration to temp path
        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))

        # Point router to calibration file
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        # Create medium complexity story
        story = {
            "id": "US-999",
            "estimatedComplexity": "medium",
            "_retryCount": 0,
        }

        # Route with calibration
        router = LlmRouter()
        result = router.route_context(story)
        routed_model = result["model"]

        # Should be haiku (utility) because sonnet is too expensive for 2% gain
        assert routed_model == TIER_TO_MODEL[ModelTier.UTILITY]

    def test_static_routing_with_no_calibration(self) -> None:
        """Test that static routing is used when no calibration is available."""
        story = {
            "id": "US-000",
            "estimatedComplexity": "medium",
            "_retryCount": 0,
        }

        router = LlmRouter()
        result = router.route_context(story)

        # Medium complexity at retry 0 should be sonnet (production tier)
        assert result["model"] == TIER_TO_MODEL[ModelTier.PRODUCTION]
        assert result["tier"] == "production"

    def test_calibration_respects_cost_threshold(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that tiers with poor cost/quality are skipped."""
        # Scenario: haiku 80% pass, sonnet 85% pass (5% gain), but 2.5x cost → should skip sonnet
        metrics = {
            ("haiku", "small"): CalibrationMetric(
                model="haiku",
                complexity="small",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
            ("sonnet", "small"): CalibrationMetric(
                model="sonnet",
                complexity="small",
                success_count=42,  # 84% vs 80% = 4% gain
                total_count=50,
                avg_cost_per_pass=2600.0,  # 2.6x cost
            ),
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        story = {"id": "US-001", "estimatedComplexity": "small", "_retryCount": 0}

        router = LlmRouter()
        result = router.route_context(story)

        # Should use haiku because sonnet's cost doesn't justify quality gain
        assert result["model"] == TIER_TO_MODEL[ModelTier.UTILITY]

    def test_calibration_uses_good_cost_ratio(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that tiers with good cost/quality ratio ARE used."""
        # Scenario: haiku 70% pass, sonnet 95% pass (25% gain), only 1.5x cost → should use sonnet
        metrics = {
            ("haiku", "large"): CalibrationMetric(
                model="haiku",
                complexity="large",
                success_count=35,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
            ("sonnet", "large"): CalibrationMetric(
                model="sonnet",
                complexity="large",
                success_count=47,  # 94% vs 70% = 24% gain
                total_count=50,
                avg_cost_per_pass=1450.0,  # 1.45x cost
            ),
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        story = {"id": "US-002", "estimatedComplexity": "large", "_retryCount": 0}

        router = LlmRouter()
        result = router.route_context(story)

        # Should use sonnet because cost/quality ratio is good
        assert result["model"] == TIER_TO_MODEL[ModelTier.PRODUCTION]


class TestCalibrationIntegration:
    """Integration tests for calibration with llm_router full flow."""

    def test_calibration_with_context_window_upgrade(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that context-window upgrade works with calibration enabled."""
        # Set up calibration with haiku being good for medium
        metrics = {
            ("haiku", "medium"): CalibrationMetric(
                model="haiku",
                complexity="medium",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))
        monkeypatch.setenv("SPIRAL_CONTEXT_WINDOW_MARGIN", "0.85")

        story = {"id": "US-003", "estimatedComplexity": "medium", "_retryCount": 0}

        router = LlmRouter()
        # High token count should trigger upgrade(s)
        result = router.route_context(story, prompt_tokens=175000)

        # Should be upgraded from haiku due to context window. Final tier will be determined by upgrade chain
        assert result["model"] in [TIER_TO_MODEL[ModelTier.PRODUCTION], TIER_TO_MODEL[ModelTier.FRONTIER]]
        assert result["context_window_upgrade"] is True

    def test_calibration_reload_on_new_instance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that each router instance loads calibration lazily."""
        metrics = {
            ("haiku", "small"): CalibrationMetric(
                model="haiku",
                complexity="small",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        # First router instance
        router1 = LlmRouter()
        story = {"id": "US-004", "estimatedComplexity": "small", "_retryCount": 0}
        result1 = router1.route_context(story)

        # Second router instance (should also load calibration)
        router2 = LlmRouter()
        result2 = router2.route_context(story)

        # Both should produce same result
        assert result1["model"] == result2["model"]


class TestCalibrationEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_success_count(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test metric with zero successes doesn't crash."""
        metrics = {
            ("haiku", "medium"): CalibrationMetric(
                model="haiku",
                complexity="medium",
                success_count=0,  # No successes
                total_count=50,
                avg_cost_per_pass=0.0,
            ),
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        story = {"id": "US-005", "estimatedComplexity": "medium", "_retryCount": 0}
        router = LlmRouter()
        # Should fall back to base tier
        result = router.route_context(story)
        assert result["model"] == TIER_TO_MODEL[ModelTier.PRODUCTION]

    def test_missing_model_in_calibration(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test missing model in calibration falls back to static."""
        metrics = {
            ("haiku", "medium"): CalibrationMetric(
                model="haiku",
                complexity="medium",
                success_count=40,
                total_count=50,
                avg_cost_per_pass=1000.0,
            ),
            # sonnet missing
        }

        calib_path = tmp_path / "routing_calibration.json"
        save_calibration(metrics, str(calib_path))
        monkeypatch.setenv("SPIRAL_ROUTING_CALIBRATION", str(calib_path))

        story = {"id": "US-006", "estimatedComplexity": "medium", "_retryCount": 0}
        router = LlmRouter()
        # Should use base (sonnet) even though calibration is partial
        result = router.route_context(story)
        assert result["model"] == TIER_TO_MODEL[ModelTier.PRODUCTION]

    def test_cli_calibrate_command(self, tmp_path: Path) -> None:
        """Test --calibrate CLI command flow."""
        # Create mock results.tsv
        results_path = tmp_path / "results.tsv"
        rows = [
            {
                "model": "haiku",
                "status": "pass",
                "estimatedComplexity": "small",
                "cache_read_tokens": "1000",
                "cache_creation_tokens": "500",
            },
            {
                "model": "sonnet",
                "status": "reject",
                "estimatedComplexity": "medium",
                "cache_read_tokens": "2000",
                "cache_creation_tokens": "1000",
            },
        ]
        with open(results_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

        # Run calibration
        from llm_router import main

        calib_path = tmp_path / "routing_calibration.json"
        old_env = os.environ.get("SPIRAL_ROUTING_CALIBRATION")
        try:
            os.environ["SPIRAL_ROUTING_CALIBRATION"] = str(calib_path)
            main(["--calibrate", str(results_path)])
            assert calib_path.exists()
            data = json.loads(calib_path.read_text())
            assert len(data) > 0
        finally:
            if old_env:
                os.environ["SPIRAL_ROUTING_CALIBRATION"] = old_env
            else:
                os.environ.pop("SPIRAL_ROUTING_CALIBRATION", None)
