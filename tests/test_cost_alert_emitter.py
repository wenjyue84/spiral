#!/usr/bin/env python3
"""
tests/test_cost_alert_emitter.py — Tests for cost alert emission
"""

import json
import os

# Add lib to path
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from cost_alert_emitter import check_and_emit_cost_alerts, emit_cost_alert


class TestEmitCostAlert:
    """Test alert emission to queue file."""

    def test_emit_alert_warning(self, tmp_path):
        """Test emitting a warning alert."""
        with patch("cost_alert_emitter.get_alerts_queue_path") as mock_path:
            queue_file = tmp_path / "alerts.jsonl"
            mock_path.return_value = queue_file

            result = emit_cost_alert(current_cost=85.0, ceiling=100.0, severity="warning")

            assert result is True
            assert queue_file.exists()

            # Parse alert from file
            with open(queue_file, "r") as f:
                alert = json.loads(f.read().strip())

            assert alert["type"] == "cost_alert"
            assert alert["severity"] == "warning"
            assert alert["current_cost"] == 85.0
            assert alert["ceiling"] == 100.0
            assert alert["percent_used"] == 85.0
            assert "timestamp" in alert

    def test_emit_alert_critical(self, tmp_path):
        """Test emitting a critical alert."""
        with patch("cost_alert_emitter.get_alerts_queue_path") as mock_path:
            queue_file = tmp_path / "alerts.jsonl"
            mock_path.return_value = queue_file

            result = emit_cost_alert(current_cost=97.5, ceiling=100.0, severity="critical")

            assert result is True

            with open(queue_file, "r") as f:
                alert = json.loads(f.read().strip())

            assert alert["severity"] == "critical"
            assert alert["percent_used"] == 97.5

    def test_emit_alert_zero_ceiling(self):
        """Test that alerts are not emitted for zero ceiling."""
        result = emit_cost_alert(current_cost=50.0, ceiling=0.0, severity="warning")
        assert result is False

    def test_emit_alert_rounding(self, tmp_path):
        """Test that costs are properly rounded."""
        with patch("cost_alert_emitter.get_alerts_queue_path") as mock_path:
            queue_file = tmp_path / "alerts.jsonl"
            mock_path.return_value = queue_file

            emit_cost_alert(current_cost=123.456789, ceiling=200.123456, severity="warning")

            with open(queue_file, "r") as f:
                alert = json.loads(f.read().strip())

            assert alert["current_cost"] == 123.4568
            assert alert["ceiling"] == 200.1235


class TestCheckAndEmitCostAlerts:
    """Test cost threshold checking and alert emission."""

    @patch("cost_alert_emitter.calculate_current_spend")
    @patch("cost_alert_emitter.get_alerts_queue_path")
    def test_check_below_threshold(self, mock_path, mock_spend, tmp_path):
        """Test that no alert is emitted below 80% threshold."""
        queue_file = tmp_path / "alerts.jsonl"
        mock_path.return_value = queue_file
        mock_spend.return_value = {"total_cost_usd": 50.0, "by_model": {}, "row_count": 0}

        result = check_and_emit_cost_alerts(ceiling_usd=100.0)

        assert result["current_cost"] == 50.0
        assert result["ceiling"] == 100.0
        assert result["percent_used"] == 50.0
        assert result["alerts_emitted"] == []
        assert not queue_file.exists()

    @patch("cost_alert_emitter.calculate_current_spend")
    @patch("cost_alert_emitter.get_alerts_queue_path")
    def test_check_warning_threshold(self, mock_path, mock_spend, tmp_path):
        """Test that warning alert is emitted at 80%."""
        queue_file = tmp_path / "alerts.jsonl"
        mock_path.return_value = queue_file
        mock_spend.return_value = {"total_cost_usd": 82.5, "by_model": {}, "row_count": 5}

        result = check_and_emit_cost_alerts(ceiling_usd=100.0)

        assert result["alerts_emitted"] == ["warning"]
        assert result["percent_used"] == 82.5

        with open(queue_file, "r") as f:
            alert = json.loads(f.read().strip())
            assert alert["severity"] == "warning"

    @patch("cost_alert_emitter.calculate_current_spend")
    @patch("cost_alert_emitter.get_alerts_queue_path")
    def test_check_critical_threshold(self, mock_path, mock_spend, tmp_path):
        """Test that critical alert is emitted at 95%."""
        queue_file = tmp_path / "alerts.jsonl"
        mock_path.return_value = queue_file
        mock_spend.return_value = {"total_cost_usd": 96.0, "by_model": {}, "row_count": 10}

        result = check_and_emit_cost_alerts(ceiling_usd=100.0)

        assert result["alerts_emitted"] == ["critical"]
        assert result["percent_used"] == 96.0

    @patch("cost_alert_emitter.calculate_current_spend")
    def test_check_no_ceiling_from_env(self, mock_spend):
        """Test graceful handling when SPIRAL_COST_CEILING is not set."""
        mock_spend.return_value = {"total_cost_usd": 50.0, "by_model": {}, "row_count": 0}

        with patch.dict(os.environ, {}, clear=True):
            result = check_and_emit_cost_alerts()

        assert result["ceiling"] == 0.0
        assert "error" in result
        assert result["alerts_emitted"] == []

    @patch("cost_alert_emitter.calculate_current_spend")
    @patch("cost_alert_emitter.get_alerts_queue_path")
    def test_alert_format(self, mock_path, mock_spend, tmp_path):
        """Test that emitted alert has correct JSON schema."""
        queue_file = tmp_path / "alerts.jsonl"
        mock_path.return_value = queue_file
        mock_spend.return_value = {"total_cost_usd": 81.0, "by_model": {}, "row_count": 3}

        check_and_emit_cost_alerts(ceiling_usd=100.0)

        with open(queue_file, "r") as f:
            alert = json.loads(f.read().strip())

        # Verify all required fields
        assert "type" in alert
        assert "severity" in alert
        assert "current_cost" in alert
        assert "ceiling" in alert
        assert "percent_used" in alert
        assert "timestamp" in alert

        # Verify types
        assert alert["type"] == "cost_alert"
        assert isinstance(alert["severity"], str)
        assert isinstance(alert["current_cost"], (int, float))
        assert isinstance(alert["ceiling"], (int, float))
        assert isinstance(alert["percent_used"], (int, float))
