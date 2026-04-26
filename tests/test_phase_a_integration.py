"""Integration tests for Phase A with mocked Claude API."""

import json
import os
import subprocess

import pytest

from tests.fixtures.mock_claude import mock_claude_env


def test_phase_a_with_mock_responses() -> None:
    """Test Phase A with mocked successful Claude API response.

    Verifies that the mock returns valid JSON and can be parsed.
    """
    with mock_claude_env():
        os.environ["CLAUDE_MOCK_SCENARIO"] = "success"

        # Simulate Phase A calling claude CLI
        result = subprocess.run(
            ["claude", "api", "research", "--prd", "prd.json"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert result.stdout

        # Parse response as JSON
        response = json.loads(result.stdout)
        assert "stories" in response
        assert len(response["stories"]) > 0
        assert response["stories"][0]["id"] == "US-100"


def test_phase_a_timeout_simulation() -> None:
    """Test Phase A timeout handling with mocked TimeoutExpired.

    Verifies that the mock raises TimeoutExpired when scenario is set to 'timeout'.
    """
    with mock_claude_env():
        os.environ["CLAUDE_MOCK_SCENARIO"] = "timeout"

        # Simulate Phase A calling claude CLI
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                ["claude", "api", "research", "--prd", "prd.json"],
                capture_output=True,
                text=True,
                timeout=30,
            )


def test_phase_a_malformed_json() -> None:
    """Test Phase A with malformed JSON response.

    Verifies that the mock returns invalid JSON when scenario is set to 'malformed_json'.
    """
    with mock_claude_env():
        os.environ["CLAUDE_MOCK_SCENARIO"] = "malformed_json"

        # Simulate Phase A calling claude CLI
        result = subprocess.run(
            ["claude", "api", "research", "--prd", "prd.json"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Attempt to parse as JSON should fail
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)


def test_mock_claude_api_import() -> None:
    """Test that MockClaudeAPI and mock_claude_env can be imported.

    Satisfies acceptance criterion: can import from tests.fixtures.mock_claude
    """
    from tests.fixtures.mock_claude import MockClaudeAPI, mock_claude_env

    assert MockClaudeAPI is not None
    assert mock_claude_env is not None
