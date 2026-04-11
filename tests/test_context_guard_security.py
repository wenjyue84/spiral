"""Security tests for lib/context_guard.py — US-1252.

Verifies that trim_prompt_sections does not expose sensitive data in trimmed
output and that estimate_phase_i_tokens rejects invalid inputs.

Run with: uv run pytest tests/test_context_guard_security.py -v
       or: uv run pytest tests/ -k us_529 -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.context_guard import estimate_phase_i_tokens, trim_prompt_sections

FAKE_KEY = "sk-ant-FAKEKEY123"


def test_no_sensitive_data_in_trim_us_529() -> None:
    """Sensitive data placed in an example section must not appear in trimmed output."""
    prompt = (
        "## Story Title\n"
        "Fix authentication bug\n"
        "\n"
        "## Example Code\n"
        f'def authenticate():\n    api_key = "{FAKE_KEY}"\n    return api_key\n'
        "\n"
        "## Requirements\n"
        "Implement the feature.\n"
    )
    # Use _token_limit=10 to force trimming regardless of prompt length
    result = trim_prompt_sections(prompt, model="haiku", _token_limit=10)
    assert FAKE_KEY not in result


def test_invalid_input_raises_us_529() -> None:
    """estimate_phase_i_tokens must raise ValueError for non-string and None inputs."""
    with pytest.raises(ValueError):
        estimate_phase_i_tokens(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        estimate_phase_i_tokens(12345)  # type: ignore[arg-type]
