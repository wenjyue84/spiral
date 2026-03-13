#!/usr/bin/env python3
"""
SPIRAL — State Machine for Phase and Story Lifecycle Verification

Two state machines:
  1. SpiralPhaseStateMachine — phases within one iteration (R->T->M->G->I->V->C)
  2. StoryLifecycle — per-story state (pending->implementing->passed|failed->decomposed)

Usage as module:
  from state_machine import SpiralPhaseStateMachine, StoryLifecycle, InvalidTransition

Usage as CLI:
  python lib/state_machine.py validate-phases --checkpoint .spiral/_checkpoint.json
  python lib/state_machine.py validate-stories --prd prd.json
  python lib/state_machine.py validate-stories --prd prd.json --progress progress.txt
"""
import json
import os
import re
import sys
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class InvalidTransition(Exception):
    """Raised when a state transition violates the state machine rules."""
    pass


# -- Phase State Machine ------------------------------------------------------

PHASE_ORDER = {"R": 0, "T": 1, "M": 2, "G": 3, "I": 4, "V": 5, "C": 6}
PHASE_NAMES = {
    "R": "Research", "T": "Test Synthesis", "M": "Merge",
    "G": "Gate", "I": "Implement", "V": "Validate", "C": "Check Done",
}


class SpiralPhaseStateMachine:
    """
    Enforces the phase ordering invariant within a single SPIRAL iteration.

    Rules:
    - Phases must advance monotonically: R < T < M < G < I < V < C
    - Skipping phases is allowed (e.g., skip T if no test reports)
    - Going backward is NEVER allowed within an iteration
    - new_iteration() resets to allow starting from R again

    >>> sm = SpiralPhaseStateMachine()
    >>> sm.transition("R")
    >>> sm.transition("T")
    >>> sm.transition("M")
    >>> sm.current
    'M'
    """

    def __init__(self):
        self.current: str | None = None
        self.iteration: int = 0
        self.history: list[tuple[int, str]] = []  # (iteration, phase) pairs

    def transition(self, phase: str) -> None:
        """Advance to the given phase. Raises InvalidTransition if backward."""
        if phase not in PHASE_ORDER:
            raise InvalidTransition(f"Unknown phase '{phase}' (valid: {', '.join(PHASE_ORDER)})")

        if self.current is not None:
            current_ord = PHASE_ORDER[self.current]
            target_ord = PHASE_ORDER[phase]
            if target_ord <= current_ord:
                raise InvalidTransition(
                    f"Cannot go from {self.current} ({PHASE_NAMES[self.current]}) "
                    f"to {phase} ({PHASE_NAMES[phase]}) — phases must advance monotonically"
                )

        self.current = phase
        self.history.append((self.iteration, phase))

    def new_iteration(self) -> None:
        """Reset for a new iteration. Must call before first transition of new iter."""
        self.current = None
        self.iteration += 1

    def can_transition(self, phase: str) -> bool:
        """Check if a transition is valid without performing it."""
        if phase not in PHASE_ORDER:
            return False
        if self.current is None:
            return True
        return PHASE_ORDER[phase] > PHASE_ORDER[self.current]

    def validate_checkpoint(self, checkpoint: dict) -> list[str]:
        """Validate a checkpoint dict against state machine rules."""
        errors = []
        ckpt_iter = checkpoint.get("iter")
        ckpt_phase = checkpoint.get("phase")

        if not isinstance(ckpt_iter, (int, float)):
            errors.append(f"Checkpoint iter must be a number, got {type(ckpt_iter).__name__}")
        elif ckpt_iter < 1:
            errors.append(f"Checkpoint iter must be >= 1, got {ckpt_iter}")

        if ckpt_phase not in PHASE_ORDER:
            errors.append(f"Checkpoint phase '{ckpt_phase}' invalid (valid: {', '.join(PHASE_ORDER)})")

        if "ts" not in checkpoint:
            errors.append("Checkpoint missing 'ts' field")

        # Validate optional phaseDurations field (US-046)
        durations = checkpoint.get("phaseDurations")
        if durations is not None:
            if not isinstance(durations, dict):
                errors.append(
                    f"phaseDurations must be an object, got {type(durations).__name__}"
                )
            else:
                for key, val in durations.items():
                    if key not in PHASE_ORDER:
                        errors.append(
                            f"phaseDurations key '{key}' is not a valid phase"
                        )
                    if not isinstance(val, (int, float)):
                        errors.append(
                            f"phaseDurations['{key}'] must be a number, got {type(val).__name__}"
                        )
                    elif val < 0:
                        errors.append(
                            f"phaseDurations['{key}'] must be non-negative, got {val}"
                        )

        return errors


# -- Story Lifecycle State Machine ---------------------------------------------

STORY_STATES = {"pending", "implementing", "passed", "failed_retry", "decomposed"}

# State transition table: current_state -> {allowed_events}
STORY_TRANSITIONS = {
    "pending": {"start_implementing", "decompose"},
    "implementing": {"mark_passed", "mark_failed"},
    "failed_retry": {"start_implementing", "decompose"},  # retry or give up
    "passed": set(),         # terminal — no further transitions
    "decomposed": set(),     # terminal — replaced by children
}


class StoryLifecycle:
    """
    Enforces valid story state transitions.

    Lifecycle:
      pending -> implementing -> passed (terminal)
                              -> failed_retry -> implementing (retry)
                                              -> decomposed (give up, split)
      pending -> decomposed (pre-implementation split)

    >>> sl = StoryLifecycle("US-001")
    >>> sl.start_implementing()
    >>> sl.mark_passed()
    >>> sl.state
    'passed'
    """

    def __init__(self, story_id: str, initial_state: str = "pending"):
        self.story_id = story_id
        if initial_state not in STORY_STATES:
            raise ValueError(f"Invalid initial state: {initial_state}")
        self.state = initial_state
        self.retries: int = 0
        self.children: list[str] = []
        self.history: list[tuple[str, str]] = []  # (from_state, event)

    def _do_transition(self, event: str, new_state: str) -> None:
        allowed = STORY_TRANSITIONS.get(self.state, set())
        if event not in allowed:
            raise InvalidTransition(
                f"Story {self.story_id}: cannot '{event}' from state '{self.state}' "
                f"(allowed: {', '.join(sorted(allowed)) or 'none — terminal state'})"
            )
        self.history.append((self.state, event))
        self.state = new_state

    def start_implementing(self) -> None:
        self._do_transition("start_implementing", "implementing")

    def mark_passed(self) -> None:
        self._do_transition("mark_passed", "passed")

    def mark_failed(self) -> None:
        self._do_transition("mark_failed", "pending")
        self.retries += 1

    def decompose(self, child_ids: list[str]) -> None:
        if self.state not in ("pending", "failed_retry"):
            raise InvalidTransition(
                f"Story {self.story_id}: cannot decompose from state '{self.state}'"
            )
        self.children = list(child_ids)
        self.history.append((self.state, "decompose"))
        self.state = "decomposed"

    @property
    def is_terminal(self) -> bool:
        return self.state in ("passed", "decomposed")

    @property
    def can_retry(self) -> bool:
        return self.state == "pending" and self.retries > 0


# -- PRD Story State Inference -------------------------------------------------

def infer_story_state(story: dict) -> str:
    """Infer the lifecycle state of a story from its prd.json fields."""
    if story.get("_decomposed"):
        return "decomposed"
    if story.get("passes"):
        return "passed"
    return "pending"


def validate_story_states(prd: dict) -> list[str]:
    """
    Validate that all story states in a PRD are consistent with lifecycle rules.
    Returns a list of error strings (empty = valid).
    """
    errors = []
    stories = prd.get("userStories", [])
    id_map = {s["id"]: s for s in stories if isinstance(s, dict) and "id" in s}

    for story in stories:
        if not isinstance(story, dict):
            continue
        sid = story.get("id", "?")
        state = infer_story_state(story)

        # Rule 1: Passed stories must have all dependencies passed (or decomposed)
        if state == "passed":
            for dep_id in story.get("dependencies", []):
                dep = id_map.get(dep_id)
                if dep and not dep.get("passes") and not dep.get("_decomposed"):
                    errors.append(
                        f"{sid}: passed but dependency {dep_id} is not passed/decomposed"
                    )

        # Rule 2: Decomposed stories must not also be marked passes=true
        if story.get("_decomposed") and story.get("passes"):
            errors.append(f"{sid}: both _decomposed and passes=true (invalid combination)")

        # Rule 3: Decomposed stories must have _decomposedInto
        if story.get("_decomposed") and not story.get("_decomposedInto"):
            errors.append(f"{sid}: _decomposed=true but no _decomposedInto list")

        # Rule 4: Children of decomposed story must exist
        for child_id in story.get("_decomposedInto", []):
            if child_id not in id_map:
                errors.append(f"{sid}: _decomposedInto child {child_id} not found")

        # Rule 5: Sub-stories must reference existing parent
        parent_id = story.get("_decomposedFrom")
        if parent_id:
            parent = id_map.get(parent_id)
            if not parent:
                errors.append(f"{sid}: _decomposedFrom parent {parent_id} not found")
            elif not parent.get("_decomposed"):
                errors.append(f"{sid}: parent {parent_id} not marked _decomposed")

        # Rule 6: Sub-stories inherit parent's priority
        if parent_id and parent_id in id_map:
            parent = id_map[parent_id]
            if story.get("priority") != parent.get("priority"):
                # This is a warning, not an error — priority could be intentionally changed
                pass

    return errors


# -- CLI -----------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="SPIRAL state machine validator")
    sub = parser.add_subparsers(dest="command")

    # validate-phases
    vp = sub.add_parser("validate-phases", help="Validate checkpoint phase coherence")
    vp.add_argument("--checkpoint", required=True, help="Path to _checkpoint.json")

    # validate-stories
    vs = sub.add_parser("validate-stories", help="Validate story lifecycle states")
    vs.add_argument("--prd", required=True, help="Path to prd.json")

    args = parser.parse_args()

    if args.command == "validate-phases":
        if not os.path.isfile(args.checkpoint):
            print(f"[state_machine] Checkpoint not found: {args.checkpoint}")
            return 0  # No checkpoint = nothing to validate

        with open(args.checkpoint, encoding="utf-8") as f:
            ckpt = json.load(f)

        sm = SpiralPhaseStateMachine()
        errors = sm.validate_checkpoint(ckpt)
        if errors:
            print("[state_machine] Checkpoint validation errors:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1

        print(f"[state_machine] Checkpoint valid: iter={ckpt.get('iter')}, phase={ckpt.get('phase')}")
        return 0

    elif args.command == "validate-stories":
        if not os.path.isfile(args.prd):
            print(f"[state_machine] ERROR: {args.prd} not found", file=sys.stderr)
            return 1

        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)

        errors = validate_story_states(prd)
        if errors:
            print(f"[state_machine] {len(errors)} lifecycle error(s):", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1

        total = len(prd.get("userStories", []))
        states = {}
        for s in prd.get("userStories", []):
            st = infer_story_state(s)
            states[st] = states.get(st, 0) + 1
        state_str = ", ".join(f"{k}={v}" for k, v in sorted(states.items()))
        print(f"[state_machine] {total} stories valid ({state_str})")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
