"""Integration tests: Phase S rejects federated stories with circular dependencies.

Story US-673: Validates that Phase S catches circular dependency chains across
federated sub-projects and halts Phase M merge until the cycle is resolved.

Acceptance criteria:
1. tests/test_phase_s_circular_deps.py creates prd.json with stories:
   US-100 (proj-a) -> US-101 (proj-b) -> US-100, runs Phase S validation
2. Phase S returns ValidationResult with CIRCULAR_DEPENDENCY error and
   cycle_path = ['US-100', 'US-101', 'US-100']
3. Integration test asserts SPIRAL logs cycle and halts Phase M merge
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from phase_s_dep_check import detect_circular_deps, validate_prd_for_merge


def _make_prd(stories: list[dict]) -> dict:  # type: ignore[type-arg]
    return {"goals": ["test goal"], "userStories": stories}


class TestCircularDepDetection:
    """Phase S detects circular dependency chains in federated story sets."""

    def test_two_story_mutual_cycle_detected(self) -> None:
        """US-100 (proj-a) -> US-101 (proj-b) -> US-100 forms a cycle."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"]},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
        ]
        result = detect_circular_deps(stories)
        assert result.error == "CIRCULAR_DEPENDENCY"
        assert "US-100" in result.cycle_path
        assert "US-101" in result.cycle_path

    def test_cycle_path_is_closed(self) -> None:
        """cycle_path starts and ends with the same node showing the loop closes."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"]},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
        ]
        result = detect_circular_deps(stories)
        assert result.error == "CIRCULAR_DEPENDENCY"
        # cycle_path = ['US-100', 'US-101', 'US-100']
        assert len(result.cycle_path) == 3
        assert result.cycle_path[0] == result.cycle_path[-1]

    def test_cycle_path_contains_both_nodes(self) -> None:
        """cycle_path contains both US-100 and US-101 in the two-node cycle."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"]},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
        ]
        result = detect_circular_deps(stories)
        assert result.error == "CIRCULAR_DEPENDENCY"
        # 3 elements: start -> other -> start (cycle closes)
        assert len(result.cycle_path) == 3
        assert result.cycle_path[0] == result.cycle_path[-1]
        # Both nodes appear in the cycle
        assert set(result.cycle_path) == {"US-100", "US-101"}

    def test_valid_linear_dep_chain_returns_no_error(self) -> None:
        """Linear dependency A -> B has no cycle."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": []},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
        ]
        result = detect_circular_deps(stories)
        assert result.error is None
        assert result.cycle_path == []
        assert not result.has_error

    def test_three_node_cross_project_cycle_detected(self) -> None:
        """A -> B -> C -> A across three sub-projects is a cycle."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": ["US-102"]},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
            {"id": "US-102", "_project": "proj-c", "dependencies": ["US-101"]},
        ]
        result = detect_circular_deps(stories)
        assert result.error == "CIRCULAR_DEPENDENCY"
        for sid in ("US-100", "US-101", "US-102"):
            assert sid in result.cycle_path

    def test_empty_stories_returns_no_error(self) -> None:
        """Empty story list has no cycles."""
        result = detect_circular_deps([])
        assert result.error is None
        assert not result.has_error

    def test_validation_result_message_contains_cycle_info(self) -> None:
        """ValidationResult.message includes CIRCULAR_DEPENDENCY and node IDs."""
        stories = [
            {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"]},
            {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"]},
        ]
        result = detect_circular_deps(stories)
        assert "CIRCULAR_DEPENDENCY" in result.message
        assert "US-100" in result.message
        assert "US-101" in result.message


class TestPrdForMerge:
    """validate_prd_for_merge halts Phase M when dependency cycles are present."""

    def test_prd_with_cycle_halts_merge(self) -> None:
        """Phase S returns CIRCULAR_DEPENDENCY when prd.json has a cycle."""
        prd = _make_prd(
            [
                {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"], "passes": False},
                {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"], "passes": False},
            ]
        )
        result = validate_prd_for_merge(prd)
        assert result.has_error
        assert result.error == "CIRCULAR_DEPENDENCY"
        assert "US-100" in result.cycle_path
        assert "US-101" in result.cycle_path

    def test_prd_without_cycle_allows_merge(self) -> None:
        """Phase S returns no error for a valid dependency graph."""
        prd = _make_prd(
            [
                {"id": "US-100", "_project": "proj-a", "dependencies": [], "passes": False},
                {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"], "passes": False},
            ]
        )
        result = validate_prd_for_merge(prd)
        assert not result.has_error
        assert result.error is None

    def test_prd_with_cycle_logs_halt_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        """SPIRAL logs 'Phase M merge HALTED' and the cycle path when a cycle is found."""
        prd = _make_prd(
            [
                {"id": "US-100", "_project": "proj-a", "dependencies": ["US-101"], "passes": False},
                {"id": "US-101", "_project": "proj-b", "dependencies": ["US-100"], "passes": False},
            ]
        )
        validate_prd_for_merge(prd)
        captured = capsys.readouterr()
        assert "CIRCULAR_DEPENDENCY" in captured.out
        assert "Phase M" in captured.out
        assert "US-100" in captured.out
        assert "US-101" in captured.out
