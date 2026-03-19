"""Tests for lib/impl/exhaustion_analyzer.py — retry exhaustion analysis."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "impl"))

from exhaustion_analyzer import analyze_exhausted_story


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_attempt(
    attempt_num: int = 1,
    model: str = "haiku",
    error: str = "",
    exit_code: int = 1,
    duration_seconds: float = 120.0,
) -> dict:
    return {
        "attempt_num": attempt_num,
        "model": model,
        "error": error,
        "exit_code": exit_code,
        "duration_seconds": duration_seconds,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestAnalyzeExhaustedStory:
    """Unit tests for analyze_exhausted_story()."""

    def test_returns_required_keys(self) -> None:
        """Result must contain all required fields from acceptance criteria."""
        attempts = [_make_attempt(error="some error")]
        result = analyze_exhausted_story("US-001", attempts)
        assert "root_cause" in result
        assert "error_pattern" in result
        assert "suggestion" in result
        assert "model_sequence" in result

    def test_empty_attempts_returns_unknown(self) -> None:
        result = analyze_exhausted_story("US-000", [])
        assert result["root_cause"] == "unknown"
        assert result["confidence_score"] == 0.0
        assert result["attempts_analyzed"] == 0

    def test_assertion_error_detected(self) -> None:
        """Repeated assertion failures → root_cause == assertion."""
        attempts = [
            _make_attempt(1, "haiku", "AssertionError: passes: false — test failed"),
            _make_attempt(2, "sonnet", "AssertionError: acceptance criteria not met"),
            _make_attempt(3, "opus", "assert expected value == actual, pytest test failed"),
        ]
        result = analyze_exhausted_story("US-123", attempts)
        assert result["root_cause"] == "assertion"

    def test_assertion_confidence_score(self) -> None:
        """All 3 attempts have the same error → confidence_score == 1.0."""
        attempts = [
            _make_attempt(1, "haiku", "AssertionError: test failed"),
            _make_attempt(2, "sonnet", "AssertionError: acceptance criteria not met"),
            _make_attempt(3, "opus", "assert expected passes true, pytest failed"),
        ]
        result = analyze_exhausted_story("US-123", attempts)
        assert result["confidence_score"] == 1.0

    def test_assertion_suggests_decomposed_antipattern(self) -> None:
        """Repeated assertion → suggestion mentions _decomposed and antiPattern."""
        attempts = [
            _make_attempt(1, "haiku", "AssertionError: test failed"),
            _make_attempt(2, "sonnet", "AssertionError: test failed"),
            _make_attempt(3, "opus", "AssertionError: test failed"),
        ]
        result = analyze_exhausted_story("US-123", attempts)
        assert "_decomposed" in result["suggestion"] or "antiPattern" in result["suggestion"]

    def test_timeout_detected(self) -> None:
        attempts = [
            _make_attempt(1, "haiku", "Error: operation timed out after 300s"),
            _make_attempt(2, "sonnet", "Process killed — timeout exceeded"),
        ]
        result = analyze_exhausted_story("US-200", attempts)
        assert result["root_cause"] == "timeout"

    def test_token_limit_detected(self) -> None:
        attempts = [
            _make_attempt(1, "haiku", "context length exceeded — input too long"),
            _make_attempt(2, "sonnet", "prompt too long: max_tokens exceeded"),
        ]
        result = analyze_exhausted_story("US-300", attempts)
        assert result["root_cause"] == "token_limit"

    def test_api_error_detected(self) -> None:
        attempts = [
            _make_attempt(1, "haiku", "Anthropic API error 503: overloaded"),
        ]
        result = analyze_exhausted_story("US-400", attempts)
        assert result["root_cause"] == "api_error"

    def test_model_sequence_matches_input(self) -> None:
        attempts = [
            _make_attempt(1, "haiku", "error"),
            _make_attempt(2, "sonnet", "error"),
            _make_attempt(3, "opus", "error"),
        ]
        result = analyze_exhausted_story("US-500", attempts)
        assert result["model_sequence"] == ["haiku", "sonnet", "opus"]

    def test_story_id_in_result(self) -> None:
        attempts = [_make_attempt(error="AssertionError")]
        result = analyze_exhausted_story("US-999", attempts)
        assert result["story_id"] == "US-999"

    def test_attempts_analyzed_count(self) -> None:
        attempts = [_make_attempt() for _ in range(3)]
        result = analyze_exhausted_story("US-010", attempts)
        assert result["attempts_analyzed"] == 3


class TestIntegrationAssertionExhaustion:
    """
    Integration test: story fails 3x with identical assertion errors.
    Verifies analyzer detects assertion_error root cause, computes confidence, and
    suggests _decomposed antiPattern (per acceptance criteria).
    """

    def test_integration_3x_identical_assertion(self) -> None:
        identical_error = "AssertionError: passes: false — acceptance criteria not met in pytest run"
        attempts = [
            _make_attempt(1, "haiku", identical_error),
            _make_attempt(2, "sonnet", identical_error),
            _make_attempt(3, "opus", identical_error),
        ]
        result = analyze_exhausted_story("US-123", attempts)

        # Root cause classification
        assert result["root_cause"] == "assertion"

        # Confidence should be high because all errors are identical type
        assert result["confidence_score"] >= 0.9

        # Suggestion should reference decomposition antiPattern
        suggestion_lower = result["suggestion"].lower()
        assert "_decomposed" in suggestion_lower or "antipattern" in suggestion_lower or "decompos" in suggestion_lower

        # Model sequence should reflect escalation
        assert result["model_sequence"] == ["haiku", "sonnet", "opus"]

        # Error counts
        assert result["error_counts"].get("assertion", 0) == 3

        # most_common_tokens_in_failures should be non-empty
        assert len(result["most_common_tokens_in_failures"]) > 0


class TestCLIEntrypoint:
    """Test the CLI via subprocess to ensure --story-id and --attempts flags work."""

    def test_cli_outputs_json(self, tmp_path) -> None:
        import subprocess

        attempts_data = [
            _make_attempt(1, "haiku", "AssertionError: test failed"),
            _make_attempt(2, "sonnet", "AssertionError: acceptance criteria not met"),
            _make_attempt(3, "opus", "assert expected true got false"),
        ]
        attempts_file = tmp_path / "attempts.json"
        attempts_file.write_text(json.dumps(attempts_data))

        script = os.path.join(
            os.path.dirname(__file__), "..", "lib", "impl", "exhaustion_analyzer.py"
        )
        result = subprocess.run(
            ["uv", "run", "python", script, "--story-id", "US-777", "--attempts", str(attempts_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["root_cause"] == "assertion"
        assert output["story_id"] == "US-777"

    def test_cli_writes_output_file(self, tmp_path) -> None:
        import subprocess

        attempts_data = [_make_attempt(1, "haiku", "timeout exceeded after 300s")]
        attempts_file = tmp_path / "attempts.json"
        attempts_file.write_text(json.dumps(attempts_data))
        output_file = tmp_path / "report.json"

        script = os.path.join(
            os.path.dirname(__file__), "..", "lib", "impl", "exhaustion_analyzer.py"
        )
        result = subprocess.run(
            [
                "uv", "run", "python", script,
                "--story-id", "US-888",
                "--attempts", str(attempts_file),
                "--output", str(output_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["root_cause"] == "timeout"
