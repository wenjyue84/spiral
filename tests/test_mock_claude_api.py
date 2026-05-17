"""Unit tests for tests/fixtures/mock_claude_api.py — MockClaudeAPI class."""

from __future__ import annotations

import subprocess

import pytest

from tests.fixtures.mock_claude_api import MockClaudeAPI


def test_inject_response_stored_and_retrieved() -> None:
    """inject_response stores response; get_response returns it."""
    mock = MockClaudeAPI()
    mock.inject_response("I", "US-001", {"result": "ok"})
    assert mock.get_response("I", "US-001") == {"result": "ok"}
    assert mock.get_response("I", "US-999") is None


def test_inject_failure_stored_and_retrieved() -> None:
    """inject_failure stores error_type; get_failure returns it."""
    mock = MockClaudeAPI()
    mock.inject_failure("R", "timeout")
    assert mock.get_failure("R") == "timeout"
    assert mock.get_failure("I") is None


def test_context_manager_patches_subprocess_run() -> None:
    """MockClaudeAPI as context manager intercepts claude subprocess calls."""
    with MockClaudeAPI() as mock:
        result = subprocess.run(
            ["claude", "--print", "hello"], capture_output=True
        )
        assert result.returncode == 0
        assert len(mock.call_log) == 1
        assert mock.call_log[0][0] == "claude"


def test_inject_response_returned_as_stdout() -> None:
    """inject_response JSON is returned as subprocess stdout."""
    import json

    with MockClaudeAPI() as mock:
        mock.inject_response("I", "US-042", {"status": "pass"})
        result = subprocess.run(
            ["claude", "--story", "US-042"], capture_output=True
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed == {"status": "pass"}


def test_inject_failure_returncode_exits_nonzero() -> None:
    """inject_failure('returncode') causes subprocess to return exit code 1."""
    with MockClaudeAPI() as mock:
        mock.inject_failure("I", "returncode")
        result = subprocess.run(
            ["claude", "--story", "US-001"], capture_output=True
        )
        assert result.returncode == 1


def test_non_claude_calls_pass_through() -> None:
    """Non-claude subprocess calls are not intercepted."""
    with MockClaudeAPI() as _mock:
        result = subprocess.run(
            ["python", "--version"], capture_output=True
        )
        assert result.returncode == 0


def test_multiple_responses_independent() -> None:
    """Multiple inject_response calls are stored independently."""
    mock = MockClaudeAPI()
    mock.inject_response("I", "US-001", {"a": 1})
    mock.inject_response("V", "US-002", {"b": 2})
    assert mock.get_response("I", "US-001") == {"a": 1}
    assert mock.get_response("V", "US-002") == {"b": 2}
    assert mock.get_response("I", "US-002") is None
