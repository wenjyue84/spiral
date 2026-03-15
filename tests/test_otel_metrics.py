"""
tests/test_otel_metrics.py — Unit tests for lib/otel_metrics.py (US-189)

Tests confirm:
1. record-tokens appends a valid JSONL record to token_metrics.jsonl
2. record-tokens no-ops on OTLP when endpoint is not set
3. serve-prometheus endpoint responds with 200 and Prometheus text format
4. Token aggregation in Prometheus output is correct
5. record-tokens handles zero/missing tokens gracefully
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure lib/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import otel_metrics  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_args(**kwargs):
    args = MagicMock()
    args.story_id = kwargs.get("story_id", "US-042")
    args.phase = kwargs.get("phase", "I")
    args.input_tokens = kwargs.get("input_tokens", 100)
    args.output_tokens = kwargs.get("output_tokens", 200)
    args.duration_ms = kwargs.get("duration_ms", 5000.0)
    args.scratch_dir = kwargs.get("scratch_dir", "/tmp/test_spiral")
    return args


# ── TestRecordTokens ──────────────────────────────────────────────────────────

class TestRecordTokens:
    def test_creates_jsonl_file(self, tmp_path):
        """record-tokens creates token_metrics.jsonl in scratch dir."""
        args = _make_args(scratch_dir=str(tmp_path))
        otel_metrics.cmd_record_tokens(args)
        assert (tmp_path / "token_metrics.jsonl").exists()

    def test_jsonl_record_fields(self, tmp_path):
        """record-tokens writes correct fields to the JSONL record."""
        args = _make_args(
            scratch_dir=str(tmp_path),
            story_id="US-099",
            phase="I",
            input_tokens=500,
            output_tokens=1500,
            duration_ms=3000.0,
        )
        otel_metrics.cmd_record_tokens(args)

        records = [
            json.loads(line)
            for line in (tmp_path / "token_metrics.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(records) == 1
        rec = records[0]
        assert rec["story_id"] == "US-099"
        assert rec["phase"] == "I"
        assert rec["input_tokens"] == 500
        assert rec["output_tokens"] == 1500
        assert rec["total_tokens"] == 2000
        assert rec["duration_ms"] == 3000.0
        assert "ts" in rec

    def test_multiple_calls_append(self, tmp_path):
        """Multiple record-tokens calls append separate JSONL lines."""
        for i in range(3):
            otel_metrics.cmd_record_tokens(
                _make_args(scratch_dir=str(tmp_path), story_id=f"US-{i:03d}", input_tokens=i * 10)
            )
        lines = [
            l for l in (tmp_path / "token_metrics.jsonl").read_text().splitlines() if l.strip()
        ]
        assert len(lines) == 3

    def test_zero_tokens_recorded(self, tmp_path):
        """record-tokens with zero tokens still writes a valid record."""
        args = _make_args(scratch_dir=str(tmp_path), input_tokens=0, output_tokens=0, duration_ms=0)
        otel_metrics.cmd_record_tokens(args)
        lines = [
            l for l in (tmp_path / "token_metrics.jsonl").read_text().splitlines() if l.strip()
        ]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["total_tokens"] == 0

    def test_no_otlp_export_without_endpoint(self, tmp_path):
        """record-tokens silently skips OTLP when endpoint is not configured."""
        args = _make_args(scratch_dir=str(tmp_path))
        # Should not raise — no endpoint configured
        env = {k: v for k, v in os.environ.items() if k != "OTEL_EXPORTER_OTLP_ENDPOINT"}
        with patch.dict(os.environ, env, clear=True):
            otel_metrics.cmd_record_tokens(args)
        # JSONL still written
        assert (tmp_path / "token_metrics.jsonl").exists()

    def test_negative_tokens_clamped_to_zero(self, tmp_path):
        """Negative token counts are clamped to 0."""
        args = _make_args(scratch_dir=str(tmp_path), input_tokens=-50, output_tokens=-100)
        otel_metrics.cmd_record_tokens(args)
        rec = json.loads(
            (tmp_path / "token_metrics.jsonl").read_text().strip().splitlines()[-1]
        )
        assert rec["input_tokens"] == 0
        assert rec["output_tokens"] == 0

    def test_scratch_dir_created_if_missing(self, tmp_path):
        """record-tokens creates missing scratch dir."""
        scratch = tmp_path / "nested" / "spiral"
        args = _make_args(scratch_dir=str(scratch))
        otel_metrics.cmd_record_tokens(args)
        assert (scratch / "token_metrics.jsonl").exists()


# ── TestBuildPrometheusText ───────────────────────────────────────────────────

class TestBuildPrometheusText:
    def test_empty_returns_placeholder(self, tmp_path):
        """_build_prometheus_text returns placeholder when no records exist."""
        text = otel_metrics._build_prometheus_text(str(tmp_path))
        assert "No token metrics" in text

    def test_prometheus_format_contains_metric_names(self, tmp_path):
        """Prometheus output contains expected metric names."""
        args = _make_args(scratch_dir=str(tmp_path), story_id="US-001", input_tokens=100, output_tokens=200)
        otel_metrics.cmd_record_tokens(args)
        text = otel_metrics._build_prometheus_text(str(tmp_path))
        assert "gen_ai_client_token_usage_total" in text
        assert "gen_ai_client_operation_duration_ms_total" in text

    def test_prometheus_labels_contain_story_id(self, tmp_path):
        """Prometheus output includes story_id label."""
        args = _make_args(scratch_dir=str(tmp_path), story_id="US-007")
        otel_metrics.cmd_record_tokens(args)
        text = otel_metrics._build_prometheus_text(str(tmp_path))
        assert 'story_id="US-007"' in text

    def test_token_counts_aggregated_correctly(self, tmp_path):
        """Token counts for the same story are summed."""
        for _ in range(3):
            otel_metrics.cmd_record_tokens(
                _make_args(scratch_dir=str(tmp_path), story_id="US-X", input_tokens=100, output_tokens=50)
            )
        text = otel_metrics._build_prometheus_text(str(tmp_path))
        # 3 × 100 = 300 input
        assert "300" in text
        # 3 × 50 = 150 output
        assert "150" in text

    def test_type_help_lines_present(self, tmp_path):
        """# HELP and # TYPE lines are present in output."""
        args = _make_args(scratch_dir=str(tmp_path))
        otel_metrics.cmd_record_tokens(args)
        text = otel_metrics._build_prometheus_text(str(tmp_path))
        assert "# HELP" in text
        assert "# TYPE" in text


# ── TestServePrometheus ───────────────────────────────────────────────────────

class TestServePrometheus:
    def test_metrics_endpoint_returns_200(self, tmp_path):
        """serve-prometheus serves /metrics with 200 OK."""
        # Write some test data
        args_rec = _make_args(scratch_dir=str(tmp_path), story_id="US-001", input_tokens=42, output_tokens=88)
        otel_metrics.cmd_record_tokens(args_rec)

        # Start server in a background thread
        port = 19876
        args_srv = MagicMock()
        args_srv.port = port
        args_srv.scratch_dir = str(tmp_path)

        t = threading.Thread(target=otel_metrics.cmd_serve_prometheus, args=(args_srv,), daemon=True)
        t.start()

        # Give server time to start
        time.sleep(0.3)

        try:
            with urllib.request.urlopen(f"http://localhost:{port}/metrics", timeout=3) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
                assert "gen_ai_client_token_usage_total" in body
                assert "US-001" in body
        finally:
            # Thread is daemon — it will be killed when the test ends
            pass

    def test_metrics_endpoint_404_for_unknown_path(self, tmp_path):
        """serve-prometheus returns 404 for non-/metrics paths."""
        port = 19877
        args_srv = MagicMock()
        args_srv.port = port
        args_srv.scratch_dir = str(tmp_path)

        t = threading.Thread(target=otel_metrics.cmd_serve_prometheus, args=(args_srv,), daemon=True)
        t.start()
        time.sleep(0.3)

        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://localhost:{port}/unknown", timeout=3)
            assert exc_info.value.code == 404
        finally:
            pass
