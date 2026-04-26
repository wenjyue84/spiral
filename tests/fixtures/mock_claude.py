"""Mock Claude CLI fixture for isolated phase behavior testing."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch


class MockClaudeAPI:
    """Mock Claude CLI subprocess that returns fixture data."""

    def __init__(self) -> None:
        """Initialize mock API with sample responses from fixture file."""
        fixture_dir = Path(__file__).parent
        sample_file = fixture_dir / "sample_responses.json"
        with open(sample_file, encoding="utf-8") as f:
            self.responses: dict[str, str] = json.load(f)

    def mock_run(self, cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Mock subprocess.run that intercepts claude CLI calls.

        Args:
            cmd: Command list (e.g., ['claude', 'api', ...])
            *args: Additional positional args (ignored)
            **kwargs: Additional keyword args (ignored)

        Returns:
            subprocess.CompletedProcess with mocked stdout

        Raises:
            subprocess.TimeoutExpired: If scenario is 'timeout'
        """
        # Check if this is a claude CLI call
        if not cmd or not isinstance(cmd, list):
            raise TypeError(f"Expected list, got {type(cmd)}")

        # Get scenario from environment
        scenario = os.environ.get("CLAUDE_MOCK_SCENARIO", "success")

        # Handle timeout scenario
        if scenario == "timeout":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

        # Get response from fixture
        response_text = self.responses.get(scenario, self.responses["success"])

        # Return mock CompletedProcess
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=response_text,
            stderr="",
        )


@contextmanager
def mock_claude_env() -> Generator[MockClaudeAPI, None, None]:
    """Context manager to patch subprocess.run with MockClaudeAPI.

    Usage:
        with mock_claude_env():
            # Code that calls subprocess.run for claude CLI
            result = subprocess.run(['claude', ...])

    Yields:
        MockClaudeAPI instance
    """
    mock_api = MockClaudeAPI()

    # Save original environment
    original_mock_env = os.environ.get("CLAUDE_CLI_MOCK")

    try:
        # Enable mock mode
        os.environ["CLAUDE_CLI_MOCK"] = "true"

        with patch("subprocess.run", side_effect=mock_api.mock_run):
            yield mock_api
    finally:
        # Restore original environment
        if original_mock_env is None:
            os.environ.pop("CLAUDE_CLI_MOCK", None)
        else:
            os.environ["CLAUDE_CLI_MOCK"] = original_mock_env
