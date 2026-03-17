#!/usr/bin/env python3
"""
tests/test_otel_content_events.py — Tests for OTel content Events (US-397)

Tests gen_ai.content.prompt and gen_ai.content.completion event emission,
redaction, and local audit trail logging.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Import the module under test
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from otel_content_events import (
    _should_redact,
    _otlp_endpoint,
    _scratch_dir,
    _content_events_path,
    cmd_emit_prompt,
    cmd_emit_completion,
)


class TestRedactionFlag:
    """Tests for SPIRAL_OTEL_REDACT_CONTENT flag handling."""

    def test_redaction_disabled_by_default(self) -> None:
        """Redaction should be false when env var not set."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "SPIRAL_OTEL_REDACT_CONTENT" in os.environ:
                del os.environ["SPIRAL_OTEL_REDACT_CONTENT"]
            assert _should_redact() is False

    def test_redaction_enabled_when_true(self) -> None:
        """Redaction should be true when SPIRAL_OTEL_REDACT_CONTENT=true."""
        with mock.patch.dict(os.environ, {"SPIRAL_OTEL_REDACT_CONTENT": "true"}):
            assert _should_redact() is True

    def test_redaction_case_insensitive(self) -> None:
        """Redaction check should be case-insensitive."""
        with mock.patch.dict(os.environ, {"SPIRAL_OTEL_REDACT_CONTENT": "TRUE"}):
            assert _should_redact() is True
        with mock.patch.dict(os.environ, {"SPIRAL_OTEL_REDACT_CONTENT": "True"}):
            assert _should_redact() is True

    def test_redaction_disabled_for_false_value(self) -> None:
        """Redaction should be false when explicitly set to false."""
        with mock.patch.dict(os.environ, {"SPIRAL_OTEL_REDACT_CONTENT": "false"}):
            assert _should_redact() is False


class TestOTLPEndpoint:
    """Tests for OTLP endpoint detection."""

    def test_no_endpoint_by_default(self) -> None:
        """OTLP endpoint should be None when not set."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "OTEL_EXPORTER_OTLP_ENDPOINT" in os.environ:
                del os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]
            assert _otlp_endpoint() is None

    def test_endpoint_from_env(self) -> None:
        """OTLP endpoint should be read from environment."""
        with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            assert _otlp_endpoint() == "http://localhost:4317"

    def test_empty_endpoint_treated_as_none(self) -> None:
        """Empty string endpoint should be treated as None."""
        with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": ""}):
            assert _otlp_endpoint() is None

    def test_whitespace_only_endpoint_treated_as_none(self) -> None:
        """Whitespace-only endpoint should be treated as None."""
        with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "   "}):
            assert _otlp_endpoint() is None


class TestScratchDir:
    """Tests for scratch directory handling."""

    def test_default_scratch_dir(self) -> None:
        """Default scratch dir should be .spiral."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "SPIRAL_SCRATCH_DIR" in os.environ:
                del os.environ["SPIRAL_SCRATCH_DIR"]
            assert _scratch_dir() == ".spiral"

    def test_custom_scratch_dir(self) -> None:
        """Should respect SPIRAL_SCRATCH_DIR env var."""
        with mock.patch.dict(os.environ, {"SPIRAL_SCRATCH_DIR": "/tmp/custom"}):
            assert _scratch_dir() == "/tmp/custom"


class TestPromptEventEmission:
    """Tests for gen_ai.content.prompt event emission."""

    def test_emit_prompt_without_redaction(self) -> None:
        """Prompt event should contain full prompt when redaction disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                args = mock.MagicMock()
                args.system_prompt = "You are a helpful assistant."
                args.user_prompt = "Implement feature X."
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                # Check local audit trail
                audit_file = Path(tmpdir) / "content_events.jsonl"
                assert audit_file.exists()
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 1
                assert records[0]["event_type"] == "gen_ai.content.prompt"
                assert records[0]["model"] == "claude-opus-4-6"
                assert records[0]["redacted"] is False
                assert "prompt" in records[0]
                assert "You are a helpful assistant." in records[0]["prompt"]
                assert "Implement feature X." in records[0]["prompt"]

    def test_emit_prompt_with_redaction(self) -> None:
        """Prompt content should be suppressed when redaction enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "true",
                },
            ):
                args = mock.MagicMock()
                args.system_prompt = "You are a helpful assistant."
                args.user_prompt = "Implement feature X."
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                # Check local audit trail
                audit_file = Path(tmpdir) / "content_events.jsonl"
                assert audit_file.exists()
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 1
                assert records[0]["event_type"] == "gen_ai.content.prompt"
                assert records[0]["redacted"] is True
                assert "prompt" not in records[0]
                # But metadata should still be present
                assert "prompt_length_chars" in records[0]
                assert records[0]["system_prompt_length"] > 0
                assert records[0]["user_prompt_length"] > 0

    def test_emit_prompt_tracks_lengths(self) -> None:
        """Prompt event should track prompt length even when redacted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "true",
                },
            ):
                args = mock.MagicMock()
                args.system_prompt = "System prompt (25 chars)"
                args.user_prompt = "User prompt (12 chars)"
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert records[0]["system_prompt_length"] == len("System prompt (25 chars)")
                assert records[0]["user_prompt_length"] == len("User prompt (12 chars)")

    def test_emit_prompt_formats_correctly(self) -> None:
        """Prompt event should format system and user prompts together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                args = mock.MagicMock()
                args.system_prompt = "System instructions"
                args.user_prompt = "User request"
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                prompt = records[0]["prompt"]
                assert "[SYSTEM]" in prompt
                assert "[USER]" in prompt
                assert "System instructions" in prompt
                assert "User request" in prompt


class TestCompletionEventEmission:
    """Tests for gen_ai.content.completion event emission."""

    def test_emit_completion_without_redaction(self) -> None:
        """Completion event should contain full response when redaction disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                args = mock.MagicMock()
                args.completion = "Here is the implementation of feature X."
                args.model = "claude-opus-4-6"

                cmd_emit_completion(args)

                # Check local audit trail
                audit_file = Path(tmpdir) / "content_events.jsonl"
                assert audit_file.exists()
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 1
                assert records[0]["event_type"] == "gen_ai.content.completion"
                assert records[0]["model"] == "claude-opus-4-6"
                assert records[0]["redacted"] is False
                assert "completion" in records[0]
                assert records[0]["completion"] == "Here is the implementation of feature X."

    def test_emit_completion_with_redaction(self) -> None:
        """Completion content should be suppressed when redaction enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "true",
                },
            ):
                args = mock.MagicMock()
                args.completion = "Here is the implementation of feature X."
                args.model = "claude-opus-4-6"

                cmd_emit_completion(args)

                # Check local audit trail
                audit_file = Path(tmpdir) / "content_events.jsonl"
                assert audit_file.exists()
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 1
                assert records[0]["event_type"] == "gen_ai.content.completion"
                assert records[0]["redacted"] is True
                assert "completion" not in records[0]
                # But metadata should still be present
                assert "completion_length_chars" in records[0]
                assert records[0]["completion_length_chars"] > 0

    def test_emit_completion_tracks_length(self) -> None:
        """Completion event should track length even when redacted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "true",
                },
            ):
                args = mock.MagicMock()
                completion_text = "x" * 1000
                args.completion = completion_text
                args.model = "claude-opus-4-6"

                cmd_emit_completion(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert records[0]["completion_length_chars"] == 1000


class TestEventOrdering:
    """Tests for prompt/completion event ordering in audit trail."""

    def test_prompt_and_completion_in_sequence(self) -> None:
        """Prompt and completion events should appear in correct order in audit trail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                # Emit prompt first
                prompt_args = mock.MagicMock()
                prompt_args.system_prompt = "System"
                prompt_args.user_prompt = "User"
                prompt_args.model = "claude-opus-4-6"
                cmd_emit_prompt(prompt_args)

                # Then emit completion
                completion_args = mock.MagicMock()
                completion_args.completion = "Response"
                completion_args.model = "claude-opus-4-6"
                cmd_emit_completion(completion_args)

                # Check order in audit trail
                audit_file = Path(tmpdir) / "content_events.jsonl"
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 2
                assert records[0]["event_type"] == "gen_ai.content.prompt"
                assert records[1]["event_type"] == "gen_ai.content.completion"


class TestAuditTrailPersistence:
    """Tests for local JSONL audit trail persistence."""

    def test_audit_trail_created_in_scratch_dir(self) -> None:
        """Local audit trail should be created in scratch directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"SPIRAL_SCRATCH_DIR": tmpdir}):
                args = mock.MagicMock()
                args.system_prompt = "System"
                args.user_prompt = "User"
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                assert audit_file.exists()

    def test_audit_trail_appends_not_overwrites(self) -> None:
        """Audit trail should append events, not overwrite previous ones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"SPIRAL_SCRATCH_DIR": tmpdir}):
                # First event
                args1 = mock.MagicMock()
                args1.system_prompt = "System1"
                args1.user_prompt = "User1"
                args1.model = "claude-opus-4-6"
                cmd_emit_prompt(args1)

                # Second event
                args2 = mock.MagicMock()
                args2.system_prompt = "System2"
                args2.user_prompt = "User2"
                args2.model = "claude-opus-4-6"
                cmd_emit_prompt(args2)

                # Both should be in the file
                audit_file = Path(tmpdir) / "content_events.jsonl"
                records = [json.loads(line) for line in audit_file.read_text().splitlines()]
                assert len(records) == 2


class TestEventAttributes:
    """Tests for OTel event attribute correctness."""

    def test_prompt_event_has_required_attributes(self) -> None:
        """Prompt event should have required attributes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                args = mock.MagicMock()
                args.system_prompt = "System"
                args.user_prompt = "User"
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                record = json.loads(audit_file.read_text().strip())
                assert "ts" in record
                assert "event_type" in record
                assert record["event_type"] == "gen_ai.content.prompt"
                assert "model" in record
                assert "redacted" in record

    def test_completion_event_has_required_attributes(self) -> None:
        """Completion event should have required attributes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(
                os.environ,
                {
                    "SPIRAL_SCRATCH_DIR": tmpdir,
                    "SPIRAL_OTEL_REDACT_CONTENT": "false",
                },
            ):
                args = mock.MagicMock()
                args.completion = "Response"
                args.model = "claude-opus-4-6"

                cmd_emit_completion(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                record = json.loads(audit_file.read_text().strip())
                assert "ts" in record
                assert "event_type" in record
                assert record["event_type"] == "gen_ai.content.completion"
                assert "model" in record
                assert "redacted" in record

    def test_timestamp_format(self) -> None:
        """Event timestamp should be in ISO 8601 format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"SPIRAL_SCRATCH_DIR": tmpdir}):
                args = mock.MagicMock()
                args.system_prompt = "System"
                args.user_prompt = "User"
                args.model = "claude-opus-4-6"

                cmd_emit_prompt(args)

                audit_file = Path(tmpdir) / "content_events.jsonl"
                record = json.loads(audit_file.read_text().strip())
                ts = record["ts"]
                # Should match ISO 8601 format: 2024-01-01T12:00:00Z
                assert ts.endswith("Z")
                assert "T" in ts
                assert len(ts) == 20  # YYYY-MM-DDTHH:MM:SSZ


class TestErrorHandling:
    """Tests for error handling in event emission."""

    def test_graceful_failure_on_write_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Event emission should fail gracefully if audit trail cannot be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            readonly_dir = Path(tmpdir) / "readonly"
            readonly_dir.mkdir()
            # Mock the open function to simulate a write error
            with mock.patch("builtins.open", side_effect=OSError("Permission denied")):
                args = mock.MagicMock()
                args.system_prompt = "System"
                args.user_prompt = "User"
                args.model = "claude-opus-4-6"

                with mock.patch.dict(os.environ, {"SPIRAL_SCRATCH_DIR": str(readonly_dir)}):
                    # Should not raise, but should log warning
                    cmd_emit_prompt(args)

                captured = capsys.readouterr()
                assert "WARNING" in captured.err
