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


class MockClaudeRunner:
    """Fixture-based mock runner that loads phase responses from JSON files.

    Loads JSON fixture files from a fixture directory and returns
    subprocess.CompletedProcess with fixture data for recognized phases.

    Usage:
        runner = MockClaudeRunner(Path("tests/fixtures"))
        result = runner(["claude", "api", ...], capture_output=True)
    """

    def __init__(self, fixture_dir: Path) -> None:
        """Initialize with fixture directory.

        Args:
            fixture_dir: Directory containing phase_*.json fixture files

        Raises:
            ValueError: If fixture_dir does not exist
        """
        if not isinstance(fixture_dir, Path):
            fixture_dir = Path(fixture_dir)
        if not fixture_dir.exists():
            raise ValueError(f"Fixture directory does not exist: {fixture_dir}")

        self.fixture_dir = fixture_dir
        self._fixtures: dict[str, Any] = {}
        self._load_fixtures()

    def _load_fixtures(self) -> None:
        """Load all phase_*.json fixture files from fixture directory."""
        for fixture_file in self.fixture_dir.glob("phase_*.json"):
            phase_key = fixture_file.stem.replace("phase_", "").replace("_responses", "").replace("_failures", "").replace("_research", "")
            with open(fixture_file, encoding="utf-8") as f:
                self._fixtures[phase_key] = json.load(f)

    def __call__(self, cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Mock subprocess.run call.

        Args:
            cmd: Command list (e.g., ['claude', 'api', ...])
            *args: Additional positional args (ignored)
            **kwargs: Additional keyword args (ignored)

        Returns:
            subprocess.CompletedProcess with mocked stdout

        Raises:
            ValueError: If phase key is not found in fixtures
        """
        if not cmd or not isinstance(cmd, list):
            raise TypeError(f"Expected list, got {type(cmd)}")

        # Extract phase key from command (assume it's in the command args)
        # For now, we'll look for a phase-like argument in the command
        phase_key = None
        for arg in cmd:
            if isinstance(arg, str) and arg in self._fixtures:
                phase_key = arg
                break

        # If no phase key found in args, check the first argument after 'claude'
        if phase_key is None:
            # Default to first available phase for testing
            phase_key = next(iter(self._fixtures)) if self._fixtures else None

        if phase_key is None or phase_key not in self._fixtures:
            raise ValueError(f"Unknown phase key: {phase_key}. Available phases: {list(self._fixtures.keys())}")

        fixture_data = self._fixtures[phase_key]

        # Return mock CompletedProcess with JSON stdout
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps(fixture_data) if not isinstance(fixture_data, str) else fixture_data,
            stderr="",
        )
