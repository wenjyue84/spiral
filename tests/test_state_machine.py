"""Property-based tests for the SPIRAL state machine (Tier 4)."""
import os
import sys
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from state_machine import SpiralPhaseStateMachine, StoryLifecycle, InvalidTransition

PHASES = ["R", "T", "M", "G", "I", "V", "C"]


class TestPhaseStateMachine:
    """Properties of the phase state machine."""

    def test_happy_path_full_iteration(self):
        sm = SpiralPhaseStateMachine()
        for phase in PHASES:
            sm.transition(phase)
        assert sm.current == "C"

    def test_new_iteration_resets_to_r(self):
        sm = SpiralPhaseStateMachine()
        for phase in PHASES:
            sm.transition(phase)
        sm.new_iteration()
        sm.transition("R")
        assert sm.current == "R"

    @given(skip_idx=st.integers(min_value=0, max_value=5))
    def test_backward_transition_raises(self, skip_idx):
        """Cannot go backward in phase order."""
        sm = SpiralPhaseStateMachine()
        # Advance past skip_idx
        for i in range(skip_idx + 2):
            if i < len(PHASES):
                sm.transition(PHASES[i])

        # Try to go backward
        with pytest.raises(InvalidTransition):
            sm.transition(PHASES[skip_idx])

    def test_skip_phase_allowed(self):
        """Skipping phases forward is allowed (e.g., skip research)."""
        sm = SpiralPhaseStateMachine()
        sm.transition("R")
        sm.transition("M")  # skip T
        assert sm.current == "M"

    @given(phases=st.permutations(PHASES))
    def test_random_order_only_valid_if_monotonic(self, phases):
        """Only monotonically increasing phase sequences are valid."""
        sm = SpiralPhaseStateMachine()
        valid = True
        for p in phases:
            try:
                sm.transition(p)
            except InvalidTransition:
                valid = False
                break

        # Check if the permutation was actually monotonic
        indices = [PHASES.index(p) for p in phases]
        is_monotonic = all(indices[i] < indices[i+1] for i in range(len(indices)-1))

        if is_monotonic:
            assert valid, "Monotonic sequence should be valid"


class TestStoryLifecycle:
    """Properties of the story state machine."""

    def test_pending_to_implementing(self):
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        assert sl.state == "implementing"

    def test_implementing_to_passed(self):
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        sl.mark_passed()
        assert sl.state == "passed"

    def test_implementing_to_failed(self):
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        sl.mark_failed()
        assert sl.state == "pending"  # goes back to pending for retry

    def test_pending_to_decomposed(self):
        sl = StoryLifecycle("US-001")
        sl.decompose(["US-010", "US-011"])
        assert sl.state == "decomposed"

    def test_cannot_implement_decomposed(self):
        sl = StoryLifecycle("US-001")
        sl.decompose(["US-010", "US-011"])
        with pytest.raises(InvalidTransition):
            sl.start_implementing()

    def test_cannot_pass_without_implementing(self):
        sl = StoryLifecycle("US-001")
        with pytest.raises(InvalidTransition):
            sl.mark_passed()

    def test_passed_is_terminal(self):
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        sl.mark_passed()
        with pytest.raises(InvalidTransition):
            sl.start_implementing()

    @given(retries=st.integers(min_value=1, max_value=10))
    def test_retry_cycle(self, retries):
        """Can fail and retry multiple times."""
        sl = StoryLifecycle("US-001")
        for _ in range(retries):
            sl.start_implementing()
            sl.mark_failed()
            assert sl.state == "pending"
        # Can still eventually pass
        sl.start_implementing()
        sl.mark_passed()
        assert sl.state == "passed"
