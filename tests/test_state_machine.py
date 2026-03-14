"""Unit and property-based tests for the SPIRAL state machine."""
import os
import sys
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from state_machine import (
    SpiralPhaseStateMachine, StoryLifecycle, InvalidTransition,
    validate_story_states,
)

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


class TestCheckpointPhaseDurations:
    """Validate phaseDurations field in checkpoint (US-046)."""

    def _base_checkpoint(self, **overrides):
        ckpt = {"iter": 1, "phase": "R", "ts": "2026-03-13T00:00:00Z", "spiralVersion": "v1.0.0"}
        ckpt.update(overrides)
        return ckpt

    def test_checkpoint_valid_without_phase_durations(self):
        """phaseDurations is optional — checkpoint without it is still valid."""
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint())
        assert errors == []

    def test_checkpoint_valid_with_phase_durations(self):
        sm = SpiralPhaseStateMachine()
        durations = {"R": 10, "T": 5, "M": 3, "I": 120, "V": 30, "C": 2}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert errors == []

    def test_phase_durations_zero_values_valid(self):
        sm = SpiralPhaseStateMachine()
        durations = {"R": 0, "T": 0, "M": 0, "I": 0, "V": 0, "C": 0}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert errors == []

    def test_phase_durations_invalid_type(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations="not a dict"))
        assert any("must be an object" in e for e in errors)

    def test_phase_durations_invalid_phase_key(self):
        sm = SpiralPhaseStateMachine()
        durations = {"R": 10, "X": 5}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert any("'X' is not a valid phase" in e for e in errors)

    def test_phase_durations_negative_value(self):
        sm = SpiralPhaseStateMachine()
        durations = {"R": -1}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert any("non-negative" in e for e in errors)

    def test_phase_durations_non_numeric_value(self):
        sm = SpiralPhaseStateMachine()
        durations = {"R": "ten"}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert any("must be a number" in e for e in errors)

    def test_phase_durations_partial_phases_valid(self):
        """Only some phases reported is fine (e.g., mid-iteration checkpoint)."""
        sm = SpiralPhaseStateMachine()
        durations = {"R": 10, "T": 5}
        errors = sm.validate_checkpoint(self._base_checkpoint(phaseDurations=durations))
        assert errors == []


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

    def test_failed_retry_to_implementing_to_passed(self):
        """failed_retry initial state can transition implementing->passed."""
        sl = StoryLifecycle("US-001", initial_state="failed_retry")
        sl.start_implementing()
        assert sl.state == "implementing"
        sl.mark_passed()
        assert sl.state == "passed"

    def test_decompose_from_failed_retry(self):
        """decompose() is valid from failed_retry state."""
        sl = StoryLifecycle("US-001", initial_state="failed_retry")
        sl.decompose(["US-010", "US-011"])
        assert sl.state == "decomposed"
        assert sl.children == ["US-010", "US-011"]

    def test_decomposed_is_terminal(self):
        """No further transitions are allowed once in decomposed state."""
        sl = StoryLifecycle("US-001")
        sl.decompose(["US-010"])
        with pytest.raises(InvalidTransition):
            sl.start_implementing()
        with pytest.raises(InvalidTransition):
            sl.mark_passed()
        with pytest.raises(InvalidTransition):
            sl.mark_failed()

    def test_passed_cannot_transition_to_implementing(self):
        """passed->implementing raises InvalidTransition."""
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        sl.mark_passed()
        with pytest.raises(InvalidTransition):
            sl.start_implementing()

    def test_passed_cannot_be_decomposed(self):
        """passed->decomposed raises InvalidTransition."""
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        sl.mark_passed()
        with pytest.raises(InvalidTransition):
            sl.decompose(["US-010"])

    def test_implementing_cannot_decompose(self):
        """decompose() from implementing state raises InvalidTransition."""
        sl = StoryLifecycle("US-001")
        sl.start_implementing()
        with pytest.raises(InvalidTransition):
            sl.decompose(["US-010"])


class TestCheckpointSpiralVersion:
    """Tests for spiralVersion field in checkpoint (US-075)."""

    def _base_checkpoint(self, **overrides):
        ckpt = {"iter": 1, "phase": "R", "ts": "2026-03-13T00:00:00Z"}
        ckpt.update(overrides)
        return ckpt

    def test_checkpoint_valid_with_spiral_version(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint(spiralVersion="v1.2.3"))
        assert errors == []

    def test_checkpoint_valid_without_spiral_version(self):
        """spiralVersion is optional for backwards compatibility."""
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint())
        assert errors == []

    def test_checkpoint_valid_with_unknown_version(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint(spiralVersion="unknown"))
        assert errors == []

    def test_checkpoint_with_git_describe_version(self):
        """Accept git describe output format like 'v1.0.0-3-gabcdef1'."""
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(self._base_checkpoint(spiralVersion="v1.0.0-3-gabcdef1"))
        assert errors == []


class TestValidateCheckpoint:
    """Tests for validate_checkpoint() covering valid, missing-ts, and invalid-phase inputs."""

    def test_valid_checkpoint(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint({"iter": 1, "phase": "R", "ts": "2026-03-13T00:00:00Z", "spiralVersion": "v1.0.0"})
        assert errors == []

    def test_missing_ts_reports_error(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint({"iter": 1, "phase": "R"})
        assert any("ts" in e for e in errors)

    def test_invalid_phase_reports_error(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint({"iter": 1, "phase": "Z", "ts": "2026-03-13T00:00:00Z"})
        assert any("Z" in e for e in errors)

    def test_invalid_iter_reports_error(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint({"iter": 0, "phase": "R", "ts": "2026-03-13T00:00:00Z"})
        assert any("iter" in e for e in errors)

    def test_non_numeric_iter_reports_error(self):
        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint({"iter": "one", "phase": "R", "ts": "2026-03-13T00:00:00Z"})
        assert any("iter" in e for e in errors)


class TestValidateStoryStates:
    """Tests for validate_story_states() PRD-level consistency checks."""

    def _prd(self, stories):
        return {"userStories": stories}

    def test_valid_prd_no_errors(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": ["US-001"]},
        ])
        assert validate_story_states(prd) == []

    def test_passed_story_with_unpassed_dependency_is_error(self):
        prd = self._prd([
            {"id": "US-001", "passes": False, "dependencies": []},
            {"id": "US-002", "passes": True, "dependencies": ["US-001"]},
        ])
        errors = validate_story_states(prd)
        assert any("US-002" in e and "US-001" in e for e in errors)

    def test_decomposed_and_passes_both_true_is_error(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "_decomposed": True, "_decomposedInto": ["US-010"]},
            {"id": "US-010", "passes": True, "dependencies": []},
        ])
        errors = validate_story_states(prd)
        assert any("US-001" in e and ("_decomposed" in e or "passes=true" in e) for e in errors)

    def test_decomposed_without_decomposed_into_is_error(self):
        prd = self._prd([
            {"id": "US-001", "_decomposed": True, "passes": False},
        ])
        errors = validate_story_states(prd)
        assert any("US-001" in e and "_decomposedInto" in e for e in errors)

    def test_decomposed_into_missing_child_is_error(self):
        prd = self._prd([
            {"id": "US-001", "_decomposed": True, "passes": False, "_decomposedInto": ["US-999"]},
        ])
        errors = validate_story_states(prd)
        assert any("US-999" in e for e in errors)
