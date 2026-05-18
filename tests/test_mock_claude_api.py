"""Unit tests for tests/fixtures/mock_claude_api.py — MockClaudeAPI class."""

from __future__ import annotations

import subprocess
from typing import Any

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
        mock.inject_response("I", "US-test", {})
        result = subprocess.run(["claude", "--phase", "I", "--story", "US-test"], capture_output=True)
        assert result.returncode == 0
        assert len(mock.call_log) == 1
        assert mock.call_log[0][0] == "claude"


def test_inject_response_returned_as_stdout() -> None:
    """inject_response JSON is returned as subprocess stdout."""
    import json

    with MockClaudeAPI() as mock:
        mock.inject_response("I", "US-042", {"status": "pass"})
        result = subprocess.run(["claude", "--phase", "I", "--story", "US-042"], capture_output=True)
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed == {"status": "pass"}


def test_inject_failure_returncode_exits_nonzero() -> None:
    """inject_failure('returncode') causes subprocess to return exit code 1."""
    with MockClaudeAPI() as mock:
        mock.inject_failure("I", "returncode")
        result = subprocess.run(["claude", "--phase", "I", "--story", "US-001"], capture_output=True)
        assert result.returncode == 1


def test_non_claude_calls_pass_through() -> None:
    """Non-claude subprocess calls are not intercepted."""
    with MockClaudeAPI() as _mock:
        result = subprocess.run(["python", "--version"], capture_output=True)
        assert result.returncode == 0


def test_multiple_responses_independent() -> None:
    """Multiple inject_response calls are stored independently."""
    mock = MockClaudeAPI()
    mock.inject_response("I", "US-001", {"a": 1})
    mock.inject_response("V", "US-002", {"b": 2})
    assert mock.get_response("I", "US-001") == {"a": 1}
    assert mock.get_response("V", "US-002") == {"b": 2}
    assert mock.get_response("I", "US-002") is None


def test_intercept_success() -> None:
    """MockClaudeAPI.intercept returns injected success response when called."""
    import json

    with MockClaudeAPI() as mock:
        mock.inject_response("I", "US-100", {"status": "success", "data": 42})
        result = subprocess.run(["claude", "--phase", "I", "--story", "US-100"], capture_output=True)
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed == {"status": "success", "data": 42}


def test_inject_failure() -> None:
    """MockClaudeAPI raises configured exception type when non-returncode failure is injected."""
    with MockClaudeAPI() as mock:
        mock.inject_failure("R", "timeout")
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.run(["claude", "--phase", "R"], capture_output=True)


def test_unmatched_raises() -> None:
    """MockClaudeAPI raises AssertionError for calls not matching any injected pattern."""
    with MockClaudeAPI() as mock:
        mock.inject_response("I", "US-001", {"ok": True})
        with pytest.raises(AssertionError, match="Unmatched claude call"):
            subprocess.run(["claude", "--phase", "I", "--story", "US-999"], capture_output=True)


def test_mock_api_repo_fixture_exercisable_in_isolation(mock_api_repo: tuple[MockClaudeAPI, Any]) -> None:
    """Verify mock_api_repo fixture can be exercised independently: wiring, git repo, and API active."""
    mock_api, repo_path = mock_api_repo

    # Confirm fixture yields (MockClaudeAPI, Path) tuple
    assert isinstance(mock_api, MockClaudeAPI)
    assert repo_path.exists()
    assert (repo_path / ".git").exists(), "Git repo should be initialized"

    # Confirm required fixture files exist
    assert (repo_path / "constitution.md").exists()
    assert (repo_path / "prd.json").exists()

    # Confirm MockClaudeAPI can be used: inject and call without error
    mock_api.inject_response("I", "US-TEST", {"status": "ok"})
    result = subprocess.run(["claude", "--phase", "I", "--story", "US-TEST"], capture_output=True)
    assert result.returncode == 0


def test_intercept_no_real_call() -> None:
    """MockClaudeAPI.intercept(responses=[...]) patches subprocess so no real CLI call is made."""
    import json

    mock = MockClaudeAPI()
    mock.intercept(
        responses=[
            {"phase": "I", "story_id": "US-001", "status": "ok"},
        ]
    )

    try:
        # Call subprocess - should be intercepted, not make real API call
        result = subprocess.run(
            ["claude", "--phase", "I", "--story", "US-001"],
            capture_output=True,
            timeout=5,  # Short timeout proves no network
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed == {"status": "ok"}
    finally:
        mock.stop()


def test_call_log() -> None:
    """MockClaudeAPI can be instantiated with no arguments and records all intercepted calls in .call_log."""
    mock = MockClaudeAPI()

    # call_log should be empty initially
    assert mock.call_log == []

    # Use context manager to patch subprocess
    with mock:
        mock.inject_response("I", "US-log-test-1", {"logged": True})
        mock.inject_response("V", "US-log-test-2", {"result": "verify"})
        subprocess.run(["claude", "--phase", "I", "--story", "US-log-test-1"], capture_output=True)
        subprocess.run(["claude", "--phase", "V", "--story", "US-log-test-2"], capture_output=True)

    # After context exit, call_log should have 2 entries
    assert len(mock.call_log) == 2
    assert mock.call_log[0] == ["claude", "--phase", "I", "--story", "US-log-test-1"]
    assert mock.call_log[1] == ["claude", "--phase", "V", "--story", "US-log-test-2"]


@pytest.mark.us_1365
def test_mock_api_prevents_network_calls_us_1365() -> None:
    """Verify MockClaudeAPI intercepts subprocess calls and prevents real network calls.

    This test ensures that when using MockClaudeAPI, Claude CLI calls are
    intercepted and return injected responses without making actual network calls.
    This is essential for US-1365: enabling mock API mode for integration tests.

    Criterion: uv run pytest tests/ -k us_1365 -v runs without network calls
    """
    with MockClaudeAPI() as mock:
        # Inject a response for phase I
        mock.inject_response("I", "US-NETWORK-TEST", {"result": "mocked"})

        # Call subprocess with claude command - should be intercepted
        result = subprocess.run(
            ["claude", "--phase", "I", "--story", "US-NETWORK-TEST"],
            capture_output=True,
            timeout=5,  # Short timeout - proves no network wait
        )

        # Verify the response came from mock, not network
        assert result.returncode == 0
        import json

        parsed = json.loads(result.stdout.decode("utf-8"))
        assert parsed == {"result": "mocked"}

        # Verify the call was logged (intercepted)
        assert len(mock.call_log) == 1
        assert "claude" in str(mock.call_log[0][0])
