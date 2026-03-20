"""tests/test_ralph_timeout.py — Integration tests for Phase I timeout resilience.

Covers US-628: Ralph subprocess timeout with partial output capture.

Acceptance criteria:
  AC1 — subprocess.TimeoutExpired is caught; partial output written to output_file
        with timeout_error annotation.
  AC2 — execute_ralph timeout handler escalates model tier (haiku→sonnet→opus)
        and returns status 'retry_escalated'.
  AC3 — Error log includes story ID, attempted model, timeout duration, and
        suggests SPIRAL_TIMEOUT_RALPH env var adjustment.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.impl.retry import _next_model, execute_ralph


class TestTimeoutOutputCapture:
    """AC1: subprocess.TimeoutExpired caught; partial output captured in output_file."""

    def test_timeout_writes_annotation_file(self) -> None:
        """On timeout, execute_ralph writes JSON with timeout_error=True to output_file."""
        with tempfile.TemporaryDirectory() as td:
            output_file = os.path.join(td, "_test_stories_output.json")

            exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=5)
            exc.stdout = "partial output line"
            exc.stderr = "partial error"

            with patch("subprocess.run", side_effect=exc):
                result = execute_ralph(
                    story_id="US-628",
                    model="haiku",
                    command=["ralph", "--story", "US-628"],
                    timeout=5,
                    output_file=output_file,
                )

            assert os.path.exists(output_file), "output_file should be created on timeout"
            with open(output_file, encoding="utf-8") as f:
                annotation = json.load(f)

            assert annotation["timeout_error"] is True
            assert annotation["story_id"] == "US-628"
            assert annotation["model"] == "haiku"
            assert annotation["timeout_seconds"] == 5
            assert "SPIRAL_TIMEOUT_RALPH" in annotation["suggestion"]
            assert annotation["partial_stdout"] == "partial output line"
            assert annotation["partial_stderr"] == "partial error"

    def test_timeout_with_bytes_partial_output(self) -> None:
        """Partial output as bytes is decoded correctly."""
        with tempfile.TemporaryDirectory() as td:
            output_file = os.path.join(td, "out.json")

            exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=10)
            exc.stdout = b"bytes stdout"
            exc.stderr = b"bytes stderr"

            with patch("subprocess.run", side_effect=exc):
                result = execute_ralph(
                    story_id="US-100",
                    model="sonnet",
                    command=["ralph"],
                    timeout=10,
                    output_file=output_file,
                )

            assert result["stdout"] == "bytes stdout"
            assert result["stderr"] == "bytes stderr"

    def test_timeout_without_output_file_does_not_crash(self) -> None:
        """Timeout without output_file still returns structured result."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=30)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
                timeout=30,
            )

        assert result["status"] == "retry_escalated"
        assert result["timeout_seconds"] == 30


class TestModelEscalation:
    """AC2: Model escalation haiku→sonnet→opus; status 'retry_escalated'."""

    def test_haiku_escalates_to_sonnet(self) -> None:
        """First timeout on haiku should escalate to sonnet."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=5)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
                timeout=5,
            )

        assert result["status"] == "retry_escalated"
        assert result["next_model"] == "sonnet"

    def test_sonnet_escalates_to_opus(self) -> None:
        """Second timeout on sonnet should escalate to opus."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=5)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="sonnet",
                command=["ralph"],
                timeout=5,
            )

        assert result["status"] == "retry_escalated"
        assert result["next_model"] == "opus"

    def test_opus_exhausted(self) -> None:
        """Timeout on opus (top of ladder) should return status 'exhausted'."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=5)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="opus",
                command=["ralph"],
                timeout=5,
            )

        assert result["status"] == "exhausted"
        assert result["next_model"] is None

    def test_next_model_helper_ladder(self) -> None:
        """_next_model follows haiku→sonnet→opus→None ladder."""
        assert _next_model("haiku") == "sonnet"
        assert _next_model("sonnet") == "opus"
        assert _next_model("opus") is None

    def test_unknown_model_escalates_to_sonnet(self) -> None:
        """Unknown model names escalate to sonnet as safe default."""
        assert _next_model("gpt-4") == "sonnet"

    def test_status_retry_escalated_not_failed(self) -> None:
        """Timeout result status must be 'retry_escalated', not 'failed'."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=5)
        exc.stdout = None
        exc.stderr = None

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-999",
                model="haiku",
                command=["ralph"],
                timeout=5,
            )

        assert result["status"] == "retry_escalated"
        assert result["status"] != "failed"


class TestErrorLogContent:
    """AC3: Error log includes story ID, model, timeout duration, SPIRAL_TIMEOUT_RALPH hint."""

    def test_error_log_contains_required_fields(self, caplog: object) -> None:
        """Logger.error message must include story_id, model, timeout, and env var hint."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=42)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            import logging as _logging

            with _logging.getLogger("lib.impl.retry").propagate and _capture_log(
                "lib.impl.retry", _logging.ERROR
            ) as log_records:
                execute_ralph(
                    story_id="US-628",
                    model="haiku",
                    command=["ralph"],
                    timeout=42,
                )

        assert log_records, "At least one error log record expected"
        msg = log_records[0].getMessage()
        assert "US-628" in msg, "story_id missing from log"
        assert "haiku" in msg, "model missing from log"
        assert "42" in msg, "timeout duration missing from log"
        assert "SPIRAL_TIMEOUT_RALPH" in msg, "env var hint missing from log"

    def test_error_message_in_result(self) -> None:
        """Result dict 'error' field contains story_id, model, and timeout hint."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=60)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="sonnet",
                command=["ralph"],
                timeout=60,
            )

        assert "error" in result
        error = result["error"]
        assert "US-628" in error
        assert "sonnet" in error
        assert "60" in error
        assert "SPIRAL_TIMEOUT_RALPH" in error

    def test_timeout_seconds_in_result(self) -> None:
        """Result dict must contain 'timeout_seconds' with the actual timeout used."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=120)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
                timeout=120,
            )

        assert result.get("timeout_seconds") == 120


class TestNonTimeoutBehavior:
    """Regression: non-timeout paths still work correctly."""

    def test_success_returns_passed(self) -> None:
        """Successful ralph run returns status='passed'."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "all good"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
                timeout=30,
            )

        assert result["status"] == "passed"
        assert result["next_model"] is None

    def test_nonzero_exit_returns_failed(self) -> None:
        """Non-zero exit code returns status='failed' with next_model set."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error output"

        with patch("subprocess.run", return_value=mock_result):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
                timeout=30,
            )

        assert result["status"] == "failed"
        assert result["next_model"] == "sonnet"

    def test_default_timeout_from_env(self) -> None:
        """SPIRAL_TIMEOUT_RALPH env var is used when no explicit timeout given."""
        exc = subprocess.TimeoutExpired(cmd=["ralph"], timeout=999)
        exc.stdout = ""
        exc.stderr = ""

        with patch("subprocess.run", side_effect=exc), patch.dict(os.environ, {"SPIRAL_TIMEOUT_RALPH": "999"}):
            result = execute_ralph(
                story_id="US-628",
                model="haiku",
                command=["ralph"],
            )

        assert result["timeout_seconds"] == 999


# ─── Helpers ──────────────────────────────────────────────────────────────────

import contextlib
import subprocess  # noqa: E402 (re-import needed at module level for patching)


@contextlib.contextmanager  # type: ignore[misc]
def _capture_log(logger_name: str, level: int) -> "contextlib.AbstractContextManager[list[logging.LogRecord]]":
    """Context manager that captures log records from a named logger."""
    import logging

    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= level:
                records.append(record)

    handler = _Handler()
    log = logging.getLogger(logger_name)
    log.addHandler(handler)
    try:
        yield records
    finally:
        log.removeHandler(handler)
