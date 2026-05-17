"""Tests for the mock_claude_cli pytest fixture (US-1360)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.fixtures.mock_claude_cli import _load_canned_responses, mock_claude_cli  # noqa: F401


class TestCannedResponsesFile:
    """Tests for tests/data/mock_claude_responses.json structure."""

    def test_file_exists(self) -> None:
        """Canned responses JSON file must exist."""
        data_file = Path(__file__).parent / "data" / "mock_claude_responses.json"
        assert data_file.exists(), f"Expected {data_file} to exist"

    def test_has_required_top_level_keys(self) -> None:
        """JSON must have test-fix, research, and ai-example keys."""
        responses = _load_canned_responses()
        for key in ("test-fix", "research", "ai-example"):
            assert key in responses, f"Expected top-level key '{key}' in mock_claude_responses.json"

    def test_each_key_has_pass_and_fail(self) -> None:
        """Each story-type key must have pass_response and fail_response."""
        responses = _load_canned_responses()
        for key in ("test-fix", "research", "ai-example"):
            entry = responses[key]
            assert "pass_response" in entry, f"'{key}' missing pass_response"
            assert "fail_response" in entry, f"'{key}' missing fail_response"

    def test_pass_response_returncode_zero(self) -> None:
        """pass_response entries must have returncode 0."""
        responses = _load_canned_responses()
        for key in ("test-fix", "research", "ai-example"):
            assert responses[key]["pass_response"]["returncode"] == 0

    def test_fail_response_nonzero_returncode(self) -> None:
        """fail_response entries must have non-zero returncode."""
        responses = _load_canned_responses()
        for key in ("test-fix", "research", "ai-example"):
            assert responses[key]["fail_response"]["returncode"] != 0


class TestMockClaudeCliFixture:
    """Tests for the mock_claude_cli fixture behaviour."""

    def test_claude_calls_intercepted(self, mock_claude_cli: MagicMock) -> None:
        """subprocess.run calls to 'claude' are intercepted and return canned response."""
        result = subprocess.run(["claude", "--story", "test story"], capture_output=True)
        assert result.returncode == 0
        assert mock_claude_cli.called

    def test_claude_stdout_is_bytes(self, mock_claude_cli: MagicMock) -> None:
        """Intercepted claude calls return stdout as bytes."""
        result = subprocess.run(["claude", "implement"], capture_output=True)
        assert isinstance(result.stdout, bytes)

    def test_mock_is_magic_mock(self, mock_claude_cli: MagicMock) -> None:
        """The fixture yields a MagicMock instance."""
        assert isinstance(mock_claude_cli, MagicMock)

    def test_fixture_importable_from_conftest(self) -> None:
        """mock_claude_cli must be importable from tests.fixtures.mock_claude_cli."""
        from tests.fixtures.mock_claude_cli import mock_claude_cli as _fixture  # noqa: F401

        assert callable(_fixture)
