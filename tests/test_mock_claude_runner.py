"""Unit tests for tests/fixtures/mock_claude.py — MockClaudeRunner class."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.mock_claude import MockClaudeRunner


def test_phase_a_fixture_loads() -> None:
    """MockClaudeRunner loads phase_a_responses.json and returns correct response."""
    fixture_dir = Path(__file__).parent / "fixtures"
    runner = MockClaudeRunner(fixture_dir)

    # Call runner with phase key "a"
    result = runner(["claude", "api", "a"], capture_output=True)

    assert result.returncode == 0
    assert result.stdout is not None

    # Parse response and verify structure
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) > 0
    assert "id" in data[0]
    assert "title" in data[0]


def test_unknown_phase_raises() -> None:
    """Calling MockClaudeRunner with unrecognized phase key raises ValueError."""
    fixture_dir = Path(__file__).parent / "fixtures"
    runner = MockClaudeRunner(fixture_dir)

    with pytest.raises(ValueError) as excinfo:
        runner(["claude", "api", "unknown_phase"])

    assert "Unknown phase key" in str(excinfo.value)


def test_fixture_dir_does_not_exist() -> None:
    """MockClaudeRunner raises ValueError if fixture directory does not exist."""
    with pytest.raises(ValueError) as excinfo:
        MockClaudeRunner(Path("/nonexistent/directory"))

    assert "Fixture directory does not exist" in str(excinfo.value)


def test_phase_r_fixture_loads() -> None:
    """MockClaudeRunner loads phase_r_research.json and returns correct response."""
    fixture_dir = Path(__file__).parent / "fixtures"
    runner = MockClaudeRunner(fixture_dir)

    result = runner(["claude", "api", "r"], capture_output=True)

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert "search_results" in data or "synthesis" in data


def test_phase_t_fixture_loads() -> None:
    """MockClaudeRunner loads phase_t_failures.json and returns correct response."""
    fixture_dir = Path(__file__).parent / "fixtures"
    runner = MockClaudeRunner(fixture_dir)

    result = runner(["claude", "api", "t"], capture_output=True)

    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)


def test_multiple_fixtures_loaded() -> None:
    """MockClaudeRunner loads all phase_*.json fixtures."""
    fixture_dir = Path(__file__).parent / "fixtures"
    runner = MockClaudeRunner(fixture_dir)

    # Verify that at least three phases are loaded (a, r, t)
    assert len(runner._fixtures) >= 3
    assert "a" in runner._fixtures
    assert "r" in runner._fixtures
    assert "t" in runner._fixtures
