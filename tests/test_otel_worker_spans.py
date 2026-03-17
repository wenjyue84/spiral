"""
Tests for lib/otel_worker_inject.py — OTel subprocess span instrumentation (US-377)
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest


class TestTraceparentParsing:
    """Test W3C TRACEPARENT parsing and formatting."""

    def test_parse_traceparent_valid(self) -> None:
        """Valid TRACEPARENT should parse correctly."""
        from otel_worker_inject import _parse_traceparent

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        trace_id, span_id = _parse_traceparent(tp)
        assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span_id == "00f067aa0ba902b7"

    def test_parse_traceparent_invalid_missing_parts(self) -> None:
        """Invalid TRACEPARENT should raise ValueError."""
        from otel_worker_inject import _parse_traceparent

        with pytest.raises(ValueError, match="Invalid TRACEPARENT"):
            _parse_traceparent("00-invalid")

    def test_build_traceparent(self) -> None:
        """Build TRACEPARENT from trace and span IDs."""
        from otel_worker_inject import _build_traceparent

        tp = _build_traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")
        assert tp == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class TestOTLPEndpointDetection:
    """Test OTEL_EXPORTER_OTLP_ENDPOINT detection."""

    def test_otlp_endpoint_set(self) -> None:
        """Should return endpoint when OTEL_EXPORTER_OTLP_ENDPOINT is set."""
        from otel_worker_inject import _otlp_endpoint

        with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            assert _otlp_endpoint() == "http://localhost:4317"

    def test_otlp_endpoint_unset(self) -> None:
        """Should return None when OTEL_EXPORTER_OTLP_ENDPOINT is unset."""
        from otel_worker_inject import _otlp_endpoint

        with mock.patch.dict(os.environ, {}, clear=True):
            assert _otlp_endpoint() is None

    def test_otlp_endpoint_whitespace(self) -> None:
        """Should return None when OTEL_EXPORTER_OTLP_ENDPOINT is whitespace."""
        from otel_worker_inject import _otlp_endpoint

        with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "   "}):
            assert _otlp_endpoint() is None


class TestWorkerSpanEmission:
    """Test ralph_worker span emission with subprocess attributes."""

    def test_cmd_emit_worker_without_endpoint(self) -> None:
        """emit_worker should no-op silently when OTEL_EXPORTER_OTLP_ENDPOINT is not set."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        with mock.patch.dict(os.environ, {}, clear=True):
            args = argparse.Namespace(
                story_id="US-123",
                worker_num=1,
                subprocess_command="bash script.sh",
                subprocess_pid=12345,
                subprocess_returncode=0,
            )
            # Should not raise; should return None silently
            result = cmd_emit_worker(args)
            assert result is None

    def test_cmd_emit_worker_without_traceparent(self) -> None:
        """emit_worker should no-op when TRACEPARENT env var is not set."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        with mock.patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}, clear=True
        ):
            args = argparse.Namespace(
                story_id="US-123",
                worker_num=1,
                subprocess_command="bash script.sh",
                subprocess_pid=12345,
                subprocess_returncode=0,
            )
            # Should not raise; should return None silently
            result = cmd_emit_worker(args)
            assert result is None

    def test_cmd_emit_worker_invalid_traceparent(self) -> None:
        """emit_worker should no-op when TRACEPARENT is malformed."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": "invalid-format",
            },
        ):
            args = argparse.Namespace(
                story_id="US-123",
                worker_num=1,
                subprocess_command="bash script.sh",
                subprocess_pid=12345,
                subprocess_returncode=0,
            )
            # Should not raise; should return None silently
            result = cmd_emit_worker(args)
            assert result is None

    @mock.patch("otel_worker_inject._emit_completed_span")
    def test_cmd_emit_worker_success_span(self, mock_emit: mock.Mock) -> None:
        """emit_worker should emit span with OK status when returncode is 0."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        # Valid TRACEPARENT format
        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": tp,
            },
        ):
            args = argparse.Namespace(
                story_id="US-123",
                worker_num=1,
                subprocess_command="bash /path/to/ralph.sh 10 --prd prd.json",
                subprocess_pid=12345,
                subprocess_returncode=0,
            )
            cmd_emit_worker(args)

        # Verify span was emitted
        assert mock_emit.called
        call_kwargs = mock_emit.call_args[1]

        # Verify span name
        assert call_kwargs["name"] == "ralph_worker US-123"

        # Verify context linkage
        assert call_kwargs["trace_id_hex"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert call_kwargs["parent_span_id_hex"] == "00f067aa0ba902b7"

        # Verify span kind
        assert call_kwargs["span_kind_override"] == "INTERNAL"

        # Verify status is OK
        assert call_kwargs["status_code"] == "OK"

        # Verify attributes
        attributes = call_kwargs["attributes"]
        assert attributes["gen_ai.agent.name"] == "spiral"
        assert attributes["gen_ai.system"] == "anthropic"
        assert attributes["subprocess.command"] == "bash /path/to/ralph.sh 10 --prd prd.json"
        assert attributes["subprocess.pid"] == 12345
        assert attributes["subprocess.returncode"] == 0
        assert attributes["spiral.story_id"] == "US-123"
        assert attributes["spiral.worker_num"] == 1
        assert attributes["subprocess.executable"] == "bash"

    @mock.patch("otel_worker_inject._emit_completed_span")
    def test_cmd_emit_worker_failure_span(self, mock_emit: mock.Mock) -> None:
        """emit_worker should emit span with ERROR status when returncode != 0."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": tp,
            },
        ):
            args = argparse.Namespace(
                story_id="US-124",
                worker_num=2,
                subprocess_command="bash /path/to/ralph.sh 10 --prd prd.json",
                subprocess_pid=54321,
                subprocess_returncode=1,
            )
            cmd_emit_worker(args)

        # Verify span was emitted
        assert mock_emit.called
        call_kwargs = mock_emit.call_args[1]

        # Verify status is ERROR when returncode != 0
        assert call_kwargs["status_code"] == "ERROR"

        # Verify returncode is captured in attributes
        attributes = call_kwargs["attributes"]
        assert attributes["subprocess.returncode"] == 1

    @mock.patch("otel_worker_inject._emit_completed_span")
    def test_cmd_emit_worker_timeout_exit_code(self, mock_emit: mock.Mock) -> None:
        """emit_worker should mark timeout exit code (124) as ERROR."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": tp,
            },
        ):
            args = argparse.Namespace(
                story_id="US-125",
                worker_num=3,
                subprocess_command="bash /path/to/ralph.sh 10 --prd prd.json",
                subprocess_pid=99999,
                subprocess_returncode=124,  # timeout exit code
            )
            cmd_emit_worker(args)

        # Verify span was emitted
        assert mock_emit.called
        call_kwargs = mock_emit.call_args[1]

        # Verify status is ERROR
        assert call_kwargs["status_code"] == "ERROR"

        # Verify returncode is captured
        attributes = call_kwargs["attributes"]
        assert attributes["subprocess.returncode"] == 124

    @mock.patch("otel_worker_inject._emit_completed_span")
    def test_cmd_emit_worker_executable_extraction(self, mock_emit: mock.Mock) -> None:
        """emit_worker should extract executable from command string."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": tp,
            },
        ):
            args = argparse.Namespace(
                story_id="US-126",
                worker_num=4,
                subprocess_command="/usr/bin/python3 -m module --arg1 val1",
                subprocess_pid=11111,
                subprocess_returncode=0,
            )
            cmd_emit_worker(args)

        # Verify executable was extracted correctly
        assert mock_emit.called
        call_kwargs = mock_emit.call_args[1]
        attributes = call_kwargs["attributes"]
        assert attributes["subprocess.executable"] == "/usr/bin/python3"

    @mock.patch("otel_worker_inject._emit_completed_span")
    def test_cmd_emit_worker_empty_command(self, mock_emit: mock.Mock) -> None:
        """emit_worker should handle empty command gracefully."""
        from otel_worker_inject import cmd_emit_worker
        import argparse

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with mock.patch.dict(
            os.environ,
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "TRACEPARENT": tp,
            },
        ):
            args = argparse.Namespace(
                story_id="US-127",
                worker_num=5,
                subprocess_command="",  # Empty command
                subprocess_pid=22222,
                subprocess_returncode=0,
            )
            cmd_emit_worker(args)

        # Verify span was emitted (no crash)
        assert mock_emit.called
        call_kwargs = mock_emit.call_args[1]
        attributes = call_kwargs["attributes"]
        # executable should not be in attributes if command is empty
        assert "subprocess.executable" not in attributes or attributes.get("subprocess.executable") == ""


class TestMainEntryPoint:
    """Test the main() entry point argument parsing."""

    @mock.patch("otel_worker_inject.cmd_emit_worker")
    def test_main_emit_worker_command(self, mock_cmd: mock.Mock) -> None:
        """main() should route emit-worker subcommand correctly."""
        from otel_worker_inject import main
        import sys

        with mock.patch.object(
            sys, "argv",
            [
                "otel_worker_inject.py",
                "emit-worker",
                "--story-id",
                "US-123",
                "--worker-num",
                "1",
                "--subprocess-command",
                "bash script.sh",
                "--subprocess-pid",
                "12345",
                "--subprocess-returncode",
                "0",
            ],
        ):
            main()

        # Verify cmd_emit_worker was called
        assert mock_cmd.called
        args = mock_cmd.call_args[0][0]
        assert args.story_id == "US-123"
        assert args.worker_num == 1
        assert args.subprocess_pid == 12345
        assert args.subprocess_returncode == 0

    def test_main_exception_handling(self) -> None:
        """main() should catch exceptions and print to stderr."""
        from otel_worker_inject import main
        import sys

        # Provide invalid arguments to trigger exception
        with mock.patch.object(
            sys, "argv",
            [
                "otel_worker_inject.py",
                "emit-worker",
                # Missing required arguments
            ],
        ):
            # Should not raise; should print error and return
            try:
                main()
            except SystemExit:
                # ArgumentParser calls sys.exit() on error
                pass
