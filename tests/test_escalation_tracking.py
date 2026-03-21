"""Tests for US-646: Model Escalation Explainability Report."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "impl"))

from escalation_tracker import (
    EscalationReason,
    detect_reason_code,
    write_escalation,
)


class TestDetectReasonCode:
    """Test reason code detection from Ralph stderr."""

    def test_detect_token_limit(self) -> None:
        """Token limit should be detected from context-related errors."""
        stderr = "Error: context window exceeded. Input tokens: 95000"
        reason = detect_reason_code(stderr)
        assert reason == EscalationReason.TOKEN_LIMIT

    def test_detect_syntax_error(self) -> None:
        """Syntax error should be detected from parse errors."""
        stderr = "SyntaxError: invalid syntax at line 42"
        reason = detect_reason_code(stderr)
        assert reason == EscalationReason.SYNTAX_ERROR

    def test_detect_timeout(self) -> None:
        """Timeout should be detected from timeout-related messages."""
        stderr = "Error: Request timed out after 300 seconds"
        reason = detect_reason_code(stderr)
        assert reason == EscalationReason.TIMEOUT

    def test_detect_api_error(self) -> None:
        """API error should be detected from rate limit and auth errors."""
        stderr = "Error: API rate limit exceeded"
        reason = detect_reason_code(stderr)
        assert reason == EscalationReason.API_ERROR

    def test_default_to_api_error(self) -> None:
        """Unknown errors should default to api_error."""
        stderr = "Some unknown error occurred"
        reason = detect_reason_code(stderr)
        assert reason == EscalationReason.API_ERROR

    def test_empty_stderr(self) -> None:
        """Empty stderr should default to api_error."""
        reason = detect_reason_code("")
        assert reason == EscalationReason.API_ERROR


class TestWriteEscalation:
    """Test writing escalation entries to escalations.json."""

    def test_write_single_escalation(self) -> None:
        """Single escalation should be written to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            escalations_file = str(Path(tmpdir) / "escalations.json")

            success = write_escalation(
                story_id="US-001",
                attempt=1,
                model_used="claude-haiku-4-5-20251001",
                reason=EscalationReason.TOKEN_LIMIT,
                retry_model="claude-sonnet-4-6",
                tokens_used=95000,
                escalations_file=escalations_file,
            )

            assert success
            assert Path(escalations_file).exists()

            with open(escalations_file) as f:
                entries = json.load(f)
            assert len(entries) == 1
            assert entries[0]["story"] == "US-001"
            assert entries[0]["attempt"] == 1
            assert entries[0]["reason"] == EscalationReason.TOKEN_LIMIT
            assert entries[0]["tokens_used"] == 95000

    def test_write_multiple_escalations(self) -> None:
        """Multiple escalations should append to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            escalations_file = str(Path(tmpdir) / "escalations.json")

            # Write first escalation
            write_escalation(
                story_id="US-001",
                attempt=1,
                model_used="haiku",
                reason=EscalationReason.TOKEN_LIMIT,
                retry_model="sonnet",
                escalations_file=escalations_file,
            )

            # Write second escalation
            write_escalation(
                story_id="US-002",
                attempt=1,
                model_used="haiku",
                reason=EscalationReason.SYNTAX_ERROR,
                retry_model="sonnet",
                escalations_file=escalations_file,
            )

            # Write third escalation
            write_escalation(
                story_id="US-003",
                attempt=1,
                model_used="sonnet",
                reason=EscalationReason.TIMEOUT,
                retry_model="opus",
                escalations_file=escalations_file,
            )

            with open(escalations_file) as f:
                entries = json.load(f)

            assert len(entries) == 3
            assert entries[0]["story"] == "US-001"
            assert entries[0]["reason"] == EscalationReason.TOKEN_LIMIT
            assert entries[1]["story"] == "US-002"
            assert entries[1]["reason"] == EscalationReason.SYNTAX_ERROR
            assert entries[2]["story"] == "US-003"
            assert entries[2]["reason"] == EscalationReason.TIMEOUT

    def test_escalation_has_timestamp(self) -> None:
        """Each escalation entry should have a timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            escalations_file = str(Path(tmpdir) / "escalations.json")

            write_escalation(
                story_id="US-001",
                attempt=1,
                model_used="haiku",
                reason=EscalationReason.TOKEN_LIMIT,
                retry_model="sonnet",
                escalations_file=escalations_file,
            )

            with open(escalations_file) as f:
                entries = json.load(f)

            assert "timestamp" in entries[0]
            assert "Z" in entries[0]["timestamp"]  # ISO8601 UTC format


class TestEscalationBreakdown:
    """Test escalation breakdown counting (dashboard endpoint behavior)."""

    def test_count_by_reason_code(self) -> None:
        """Escalations should be counted by reason code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            escalations_file = str(Path(tmpdir) / "escalations.json")

            # Write 3 mock failures with different reason codes
            write_escalation(
                story_id="US-001",
                attempt=1,
                model_used="haiku",
                reason=EscalationReason.TOKEN_LIMIT,
                retry_model="sonnet",
                escalations_file=escalations_file,
            )

            write_escalation(
                story_id="US-002",
                attempt=1,
                model_used="haiku",
                reason=EscalationReason.SYNTAX_ERROR,
                retry_model="sonnet",
                escalations_file=escalations_file,
            )

            write_escalation(
                story_id="US-003",
                attempt=1,
                model_used="sonnet",
                reason=EscalationReason.TIMEOUT,
                retry_model="opus",
                escalations_file=escalations_file,
            )

            # Count escalations by reason (simulating dashboard logic)
            with open(escalations_file) as f:
                entries = json.load(f)

            breakdown = {
                "token_limit": 0,
                "syntax_error": 0,
                "timeout": 0,
                "api_error": 0,
            }

            for entry in entries:
                reason = entry["reason"]
                if reason in breakdown:
                    breakdown[reason] += 1

            assert breakdown["token_limit"] == 1
            assert breakdown["syntax_error"] == 1
            assert breakdown["timeout"] == 1
            assert breakdown["api_error"] == 0
            assert sum(breakdown.values()) == 3
