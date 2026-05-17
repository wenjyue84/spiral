"""Mock Claude CLI pytest fixture for intercepting subprocess.run calls.

Provides a reusable fixture that patches subprocess.run so any call with
'claude' as the first argument returns canned JSON responses loaded from
tests/data/mock_claude_responses.json.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _load_canned_responses() -> dict[str, Any]:
    """Load canned responses from tests/data/mock_claude_responses.json."""
    data_file = Path(__file__).parent.parent / "data" / "mock_claude_responses.json"
    with open(data_file, encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
    return result


def _make_completed_process(response: dict[str, Any], args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Build a CompletedProcess from a canned response dict."""
    stdout_text = response.get("stdout", "")
    stdout = stdout_text.encode("utf-8") if isinstance(stdout_text, str) else stdout_text
    return subprocess.CompletedProcess(
        args=args,
        returncode=response.get("returncode", 0),
        stdout=stdout,
        stderr=b"",
    )


@pytest.fixture
def mock_claude_cli() -> MagicMock:
    """Pytest fixture: intercept subprocess.run calls to the 'claude' CLI.

    All subprocess.run calls whose first argument is 'claude' are intercepted
    and return the test-fix pass_response from mock_claude_responses.json.
    Non-claude calls are passed through to the real subprocess.run.

    Usage::

        def test_something(mock_claude_cli):
            import subprocess
            result = subprocess.run(["claude", "--story", "my story"], capture_output=True)
            assert result.returncode == 0

    Returns:
        MagicMock wrapping the patched subprocess.run
    """
    responses = _load_canned_responses()
    default_response: dict[str, Any] = responses.get("test-fix", {}).get(
        "pass_response", {"returncode": 0, "stdout": ""}
    )

    # Save the original before patching to avoid recursion on non-claude calls
    _original_run = subprocess.run

    def _side_effect(args: Any, *pargs: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if isinstance(args, (list, tuple)) and args and str(args[0]) == "claude":
            return _make_completed_process(default_response, list(args))
        return _original_run(args, *pargs, **kwargs)

    with patch("subprocess.run", side_effect=_side_effect) as mock:
        yield mock
