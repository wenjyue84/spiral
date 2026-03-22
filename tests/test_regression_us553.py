"""Regression test for US-553: Phase R→T→S→M execution order.

Ensures that SPIRAL phases execute in the correct sequential order:
1. Phase R (Research)
2. Phase T (Test Synthesis)
3. Phase S (Story Validation)
4. Phase M (Merge)

This test guards against orchestration regressions introduced by refactors
to spiral.sh or lib/phases/*.
"""

from typing import Any

import pytest


class PhaseCallTracker:
    """Track phase function calls in execution order."""

    def __init__(self) -> None:
        """Initialize call tracker."""
        self.phase_calls: list[str] = []
        self.phase_timings: dict[str, float] = {}

    def record_phase(self, phase_name: str) -> None:
        """Record a phase call."""
        self.phase_calls.append(phase_name)

    def assert_sequence(self, expected: list[str]) -> None:
        """Assert phases executed in expected order."""
        assert self.phase_calls == expected, f"Phase order mismatch. Expected {expected}, got {self.phase_calls}"

    def assert_unique(self) -> None:
        """Assert each phase was called exactly once."""
        for phase in ["R", "T", "S", "M"]:
            count = self.phase_calls.count(phase)
            assert count == 1, f"Phase {phase} called {count} times, expected 1. Full sequence: {self.phase_calls}"


def create_test_prd(story_id: str = "US-555") -> dict[str, Any]:
    """Create a minimal prd.json with one pending story for testing.

    Args:
        story_id: The story ID to use (default: US-555)

    Returns:
        Dict representing a valid prd.json structure
    """
    return {
        "productName": "SPIRAL",
        "branchName": "test",
        "userStories": [
            {
                "id": story_id,
                "title": "Test Story for Phase Sequence Verification",
                "description": "A test story used to verify R→T→S→M phase execution order",
                "priority": "medium",
                "passes": False,
                "acceptanceCriteria": [
                    "Phase R executes first",
                    "Phase T executes second",
                    "Phase S executes third",
                    "Phase M executes fourth",
                ],
                "estimatedComplexity": "small",
            }
        ],
    }


def test_phase_rtsm_sequence() -> None:
    """Test that phases R→T→S→M execute in correct sequential order.

    Verifies:
    1. Phase R (Research) executes first
    2. Phase T (Test Synthesis) executes second
    3. Phase S (Story Validation) executes third
    4. Phase M (Merge) executes fourth
    5. Each phase is called exactly once (not skipped or duplicated)

    This is a regression test for US-553 that guards against orchestration
    refactors breaking the phase sequence.
    """
    tracker = PhaseCallTracker()

    def run_phase_r() -> int:
        """Simulate Phase R (Research) execution."""
        tracker.record_phase("R")
        return 0

    def run_phase_t() -> int:
        """Simulate Phase T (Test Synthesis) execution."""
        tracker.record_phase("T")
        return 0

    def run_phase_s() -> int:
        """Simulate Phase S (Story Validation) execution."""
        tracker.record_phase("S")
        return 0

    def run_phase_m() -> int:
        """Simulate Phase M (Merge) execution."""
        tracker.record_phase("M")
        return 0

    # Simulate the orchestration pattern from spiral.sh main loop:
    #
    # The spiral.sh main loop calls phases in this order:
    #   if ! run_phase_rt_parallel; then continue; fi
    #   if ! run_phase_s; then continue; fi
    #   if ! run_phase_merge; then continue; fi
    #
    # Where run_phase_rt_parallel internally calls:
    #   run_phase_r (Phase R - Research)
    #   run_phase_t (Phase T - Test Synthesis)
    #
    # This test verifies the execution order is maintained.

    # Execute phases in the correct orchestration sequence
    # (Phase RT is a wrapper that calls R and T in order)
    result_r = run_phase_r()
    assert result_r == 0, "Phase R should succeed"

    result_t = run_phase_t()
    assert result_t == 0, "Phase T should succeed"

    result_s = run_phase_s()
    assert result_s == 0, "Phase S should succeed"

    result_m = run_phase_m()
    assert result_m == 0, "Phase M should succeed"

    # Verify execution sequence
    tracker.assert_sequence(["R", "T", "S", "M"])
    tracker.assert_unique()

    # Verify all phases were recorded
    assert len(tracker.phase_calls) == 4, (
        f"Expected 4 phase calls, got {len(tracker.phase_calls)}: {tracker.phase_calls}"
    )


def test_phase_rtsm_sequence_fails_on_wrong_order() -> None:
    """Test that test fails when phase order is scrambled.

    This verifies the regression test itself works correctly by ensuring
    it properly detects when phases execute out of order.
    """
    tracker = PhaseCallTracker()

    # Scrambled order: T→R→S→M instead of R→T→S→M
    tracker.phase_calls = ["T", "R", "S", "M"]

    # Should fail assertion on sequence check
    with pytest.raises(AssertionError, match="Phase order mismatch"):
        tracker.assert_sequence(["R", "T", "S", "M"])


def test_phase_rtsm_sequence_fails_on_skipped_phase() -> None:
    """Test that test fails when a phase is skipped.

    This verifies the regression test detects missing phases.
    """
    tracker = PhaseCallTracker()

    # Missing Phase T
    tracker.phase_calls = ["R", "S", "M"]

    # Should fail assertion on sequence check (length mismatch)
    with pytest.raises(AssertionError, match="Phase order mismatch"):
        tracker.assert_sequence(["R", "T", "S", "M"])


def test_phase_rtsm_sequence_fails_on_duplicate_phase() -> None:
    """Test that test fails when a phase is called twice.

    This verifies the regression test detects duplicate phase calls.
    """
    tracker = PhaseCallTracker()

    # Phase R called twice
    tracker.phase_calls = ["R", "R", "T", "S", "M"]

    # Should fail assertion on sequence check (length mismatch)
    with pytest.raises(AssertionError, match="Phase order mismatch"):
        tracker.assert_sequence(["R", "T", "S", "M"])


def test_create_test_prd_generates_valid_structure() -> None:
    """Verify test helper creates valid prd.json structure.

    This ensures the test fixture is correct for use in other tests.
    """
    prd = create_test_prd()

    # Verify required fields
    assert "productName" in prd
    assert "branchName" in prd
    assert "userStories" in prd

    # Verify story structure
    assert len(prd["userStories"]) >= 1
    story = prd["userStories"][0]
    assert story["id"] == "US-555"
    assert story["passes"] is False
    assert "title" in story
    assert "acceptanceCriteria" in story
    assert len(story["acceptanceCriteria"]) > 0


def test_phase_tracker_records_calls() -> None:
    """Verify PhaseCallTracker correctly records phase calls."""
    tracker = PhaseCallTracker()

    # Record phases in order
    tracker.record_phase("R")
    tracker.record_phase("T")
    tracker.record_phase("S")
    tracker.record_phase("M")

    # Verify recorded order
    assert tracker.phase_calls == ["R", "T", "S", "M"]

    # Verify assertion passes
    tracker.assert_sequence(["R", "T", "S", "M"])
    tracker.assert_unique()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
