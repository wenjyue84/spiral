"""
tests/test_otel_spans.py — Unit tests for lib/otel_spans.py (US-184)

Tests confirm:
1. begin-run outputs a valid W3C TRACEPARENT
2. State file is created in scratch dir
3. end-phase silently no-ops without OTEL_EXPORTER_OTLP_ENDPOINT
4. end-phase sets correct GenAI semconv attributes
5. end-run silently no-ops without OTEL_EXPORTER_OTLP_ENDPOINT
6. Unknown errors in OTel machinery never crash with non-zero exit
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure lib/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import otel_spans  # noqa: E402


# ── Regex for W3C TRACEPARENT ─────────────────────────────────────────────────
_TRACEPARENT_RE = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)


class TestBeginRun:
    def test_outputs_valid_traceparent(self, tmp_path, capsys):
        """begin-run prints a W3C traceparent to stdout."""
        args = MagicMock()
        args.run_id = "test-run-abc"
        args.scratch_dir = str(tmp_path)

        otel_spans.cmd_begin_run(args)

        captured = capsys.readouterr()
        tp = captured.out.strip()
        assert _TRACEPARENT_RE.match(tp), f"Not a valid TRACEPARENT: {tp!r}"

    def test_creates_state_file(self, tmp_path, capsys):
        """begin-run saves otel_run_context.json to scratch dir."""
        args = MagicMock()
        args.run_id = "run-42"
        args.scratch_dir = str(tmp_path)

        otel_spans.cmd_begin_run(args)

        state_file = tmp_path / "otel_run_context.json"
        assert state_file.exists(), "State file not created"
        state = json.loads(state_file.read_text())
        assert state["run_id"] == "run-42"
        assert len(state["trace_id"]) == 32
        assert len(state["root_span_id"]) == 16
        assert state["start_time_ns"] > 0

    def test_state_file_trace_matches_traceparent(self, tmp_path, capsys):
        """TRACEPARENT trace_id/span_id matches what's saved in state file."""
        args = MagicMock()
        args.run_id = "run-xyz"
        args.scratch_dir = str(tmp_path)

        otel_spans.cmd_begin_run(args)

        tp = capsys.readouterr().out.strip()
        state = json.loads((tmp_path / "otel_run_context.json").read_text())
        _, tp_trace, tp_span, _ = tp.split("-", 3)
        assert tp_trace == state["trace_id"]
        assert tp_span == state["root_span_id"]

    def test_unique_trace_ids(self, tmp_path, capsys):
        """Each begin-run call generates a unique trace_id."""
        ids = set()
        for i in range(5):
            args = MagicMock()
            args.run_id = f"run-{i}"
            args.scratch_dir = str(tmp_path)
            otel_spans.cmd_begin_run(args)
            tp = capsys.readouterr().out.strip()
            ids.add(tp.split("-")[1])
        assert len(ids) == 5


class TestEndPhaseNoOp:
    def test_noop_without_otlp_endpoint(self, monkeypatch):
        """end-phase silently returns when OTEL_EXPORTER_OTLP_ENDPOINT is unset."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setenv(
            "TRACEPARENT", "00-abcd1234abcd1234abcd1234abcd1234-1234567890abcdef-01"
        )
        args = MagicMock()
        args.phase = "R"
        args.duration_s = 10.0
        args.input_tokens = 100
        args.output_tokens = 50
        args.story_id = "US-001"
        args.iteration = 1

        # Must not raise
        otel_spans.cmd_end_phase(args)

    def test_noop_without_traceparent(self, monkeypatch):
        """end-phase silently returns when TRACEPARENT is unset (no root span context)."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.delenv("TRACEPARENT", raising=False)
        args = MagicMock()
        args.phase = "T"
        args.duration_s = 5.0
        args.input_tokens = None
        args.output_tokens = None
        args.story_id = None
        args.iteration = None

        # Must not raise
        otel_spans.cmd_end_phase(args)


class TestEndRunNoOp:
    def test_noop_without_otlp_endpoint(self, tmp_path, monkeypatch):
        """end-run silently returns when OTEL_EXPORTER_OTLP_ENDPOINT is unset."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setenv("SPIRAL_SCRATCH_DIR", str(tmp_path))

        # Create a valid state file
        state = {"trace_id": "a" * 32, "root_span_id": "b" * 16, "start_time_ns": 1}
        (tmp_path / "otel_run_context.json").write_text(json.dumps(state))

        args = MagicMock()
        args.passes = 5
        args.story_count = 10

        otel_spans.cmd_end_run(args)  # must not raise

    def test_noop_missing_state_file(self, tmp_path, monkeypatch):
        """end-run silently no-ops when otel_run_context.json is missing."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.setenv("SPIRAL_SCRATCH_DIR", str(tmp_path))

        args = MagicMock()
        args.passes = 0
        args.story_count = 0

        otel_spans.cmd_end_run(args)  # must not raise


class TestSpanAttributes:
    def test_phase_attributes_passed_to_emit(self, monkeypatch):
        """end-phase builds correct attributes dict including GenAI semconv keys."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.setenv(
            "TRACEPARENT", "00-abcd1234abcd1234abcd1234abcd1234-1234567890abcdef-01"
        )
        captured_attrs: dict = {}

        def fake_emit(*, name, trace_id_hex, parent_span_id_hex, span_id_hex,
                      start_time_ns, end_time_ns, attributes, is_root=False):
            captured_attrs.update(attributes)
            captured_attrs["_name"] = name

        monkeypatch.setattr(otel_spans, "_emit_completed_span", fake_emit)

        args = MagicMock()
        args.phase = "R"
        args.duration_s = 30.0
        args.input_tokens = 1000
        args.output_tokens = 500
        args.story_id = "US-042"
        args.iteration = 3

        otel_spans.cmd_end_phase(args)

        assert captured_attrs["gen_ai.agent.name"] == "spiral"
        assert captured_attrs["gen_ai.operation.name"] == "research"
        assert captured_attrs["gen_ai.system"] == "anthropic"
        assert captured_attrs["gen_ai.usage.input_tokens"] == 1000
        assert captured_attrs["gen_ai.usage.output_tokens"] == 500
        assert captured_attrs["spiral.story_id"] == "US-042"
        assert captured_attrs["spiral.iteration"] == 3
        assert captured_attrs["_name"] == "invoke_agent spiral/R"

    def test_root_run_attributes(self, tmp_path, monkeypatch):
        """end-run builds correct root span attributes."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.setenv("SPIRAL_SCRATCH_DIR", str(tmp_path))

        state = {
            "run_id": "run-007",
            "trace_id": "a" * 32,
            "root_span_id": "b" * 16,
            "start_time_ns": 1_000_000,
        }
        (tmp_path / "otel_run_context.json").write_text(json.dumps(state))

        captured_attrs: dict = {}

        def fake_emit(*, name, **kwargs):
            captured_attrs.update(kwargs.get("attributes", {}))
            captured_attrs["_name"] = name

        monkeypatch.setattr(otel_spans, "_emit_completed_span", fake_emit)

        args = MagicMock()
        args.passes = 10
        args.story_count = 20

        otel_spans.cmd_end_run(args)

        assert captured_attrs["gen_ai.agent.name"] == "spiral"
        assert captured_attrs["gen_ai.agent.id"] == "run-007"
        assert captured_attrs["gen_ai.operation.name"] == "invoke_agent"
        assert captured_attrs["gen_ai.system"] == "anthropic"
        assert captured_attrs["spiral.stories_passed"] == 10
        assert captured_attrs["spiral.story_count"] == 20
        assert captured_attrs["_name"] == "invoke_agent spiral"

    def test_optional_token_counts_omitted_when_none(self, monkeypatch):
        """Token attributes are omitted when not provided."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.setenv(
            "TRACEPARENT", "00-abcd1234abcd1234abcd1234abcd1234-1234567890abcdef-01"
        )
        captured_attrs: dict = {}

        def fake_emit(*, attributes, **kwargs):
            captured_attrs.update(attributes)

        monkeypatch.setattr(otel_spans, "_emit_completed_span", fake_emit)

        args = MagicMock()
        args.phase = "V"
        args.duration_s = 10.0
        args.input_tokens = None
        args.output_tokens = None
        args.story_id = None
        args.iteration = None

        otel_spans.cmd_end_phase(args)

        assert "gen_ai.usage.input_tokens" not in captured_attrs
        assert "gen_ai.usage.output_tokens" not in captured_attrs


class TestCLI:
    """Integration-level CLI tests via subprocess."""

    def test_begin_run_cli(self, tmp_path):
        """CLI begin-run prints valid TRACEPARENT."""
        result = subprocess.run(
            [sys.executable, "lib/otel_spans.py", "begin-run",
             "--run-id", "cli-test", "--scratch-dir", str(tmp_path)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
        tp = result.stdout.strip()
        assert _TRACEPARENT_RE.match(tp), f"Invalid TRACEPARENT: {tp!r}"

    def test_end_phase_noop_no_env(self, tmp_path):
        """CLI end-phase exits 0 without OTLP endpoint."""
        env = {**os.environ}
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        result = subprocess.run(
            [sys.executable, "lib/otel_spans.py", "end-phase",
             "--phase", "R", "--duration-s", "5"],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0

    def test_end_run_noop_no_env(self, tmp_path):
        """CLI end-run exits 0 without OTLP endpoint."""
        env = {**os.environ}
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        result = subprocess.run(
            [sys.executable, "lib/otel_spans.py", "end-run"],
            capture_output=True, text=True, env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0
