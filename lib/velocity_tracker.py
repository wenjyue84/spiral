#!/usr/bin/env python3
"""lib/velocity_tracker.py — Iteration velocity trend detection and stall alerting.

Computes rolling velocity (stories_passed/iteration) from results.tsv and detects
when velocity drops below 0.5 stories/iter for 3+ consecutive iterations.
Emits structured warning events to spiral_events.jsonl with actionable suggestions.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class VelocitySnapshot:
    """Single iteration's velocity snapshot."""

    iteration: int
    stories_passed: int
    velocity: float  # stories_passed per iteration


def compute_rolling_velocity(results_tsv_path: str) -> list[VelocitySnapshot]:
    """Compute velocity (stories_passed/iter) from results.tsv.

    Args:
        results_tsv_path: Path to results.tsv

    Returns:
        List of VelocitySnapshot ordered by iteration (oldest first).
    """
    path = Path(results_tsv_path)
    if not path.exists():
        return []

    # Track both all iterations and passes by iteration
    iter_passes: dict[int, int] = defaultdict(int)
    all_iters: set[int] = set()

    try:
        with open(path, encoding="utf-8") as f:
            header = f.readline().strip()
            if not header:
                return []

            # Find column indices
            cols = header.split("\t")
            iter_idx = cols.index("spiral_iter")
            status_idx = cols.index("status")

            for line in f:
                parts = line.strip().split("\t")
                if len(parts) > max(iter_idx, status_idx):
                    try:
                        iter_num = int(parts[iter_idx])
                        status = parts[status_idx]
                        all_iters.add(iter_num)
                        if status == "pass":
                            iter_passes[iter_num] += 1
                    except (ValueError, IndexError):
                        continue
    except (IOError, OSError, ValueError):
        return []

    # Build velocity snapshots for all iterations (including 0-pass iterations)
    snapshots = []
    for iter_num in sorted(all_iters):
        passed = iter_passes.get(iter_num, 0)
        velocity = float(passed)  # 1 iter = 1 unit of time in this context
        snapshots.append(VelocitySnapshot(iteration=iter_num, stories_passed=passed, velocity=velocity))

    return snapshots


def detect_stall(velocity_history: list[VelocitySnapshot]) -> tuple[bool, Optional[int]]:
    """Detect if velocity has stalled (<0.5 for 3+ consecutive iterations).

    Args:
        velocity_history: List of VelocitySnapshot ordered by iteration.

    Returns:
        (is_stalled, stall_start_iteration) — True if stalled, False otherwise.
        stall_start_iteration is the first iteration of the stall sequence if stalled.
    """
    if len(velocity_history) < 3:
        return False, None

    # Scan for 3+ consecutive iterations with velocity < 0.5
    for i in range(len(velocity_history) - 2):
        if (
            velocity_history[i].velocity < 0.5
            and velocity_history[i + 1].velocity < 0.5
            and velocity_history[i + 2].velocity < 0.5
        ):
            return True, velocity_history[i].iteration

    return False, None


def generate_suggestions(prd_path: str) -> list[str]:
    """Generate actionable suggestions for stalled velocity.

    Args:
        prd_path: Path to prd.json

    Returns:
        List of suggestion strings.
    """
    suggestions = []
    path = Path(prd_path)

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                prd = json.load(f)
                stories = prd.get("userStories", [])

                # Find largest pending story
                pending = [s for s in stories if not s.get("passes", False)]
                if pending:
                    largest = max(pending, key=lambda s: len(s.get("description", "")))
                    suggestions.append(f"decompose story {largest.get('id', '?')}: {largest.get('title', '')[:50]}")

                # Count pending by category
                complex_pending = [s for s in pending if s.get("estimatedComplexity") == "large"]
                if complex_pending:
                    suggestions.append(f"escalate model tier (currently handling {len(complex_pending)} large stories)")

                # Low-priority strategy
                low_priority = [
                    s for s in pending if s.get("priority") in ("low", "trivial") and s.get("_source") == "ai-example"
                ]
                if low_priority:
                    suggestions.append(f"skip {len(low_priority)} low-priority ai-example stories")
        except (IOError, json.JSONDecodeError):
            pass

    # Add fallback suggestions if none found
    if not suggestions:
        suggestions = [
            "Check .spiral/phase_i_implement.sh logs for retry patterns",
            "Review error categories in results.tsv for root cause",
            "Consider reducing story complexity or scope",
        ]

    return suggestions


def emit_stall_warning(
    iteration: int,
    velocity_history: list[VelocitySnapshot],
    suggestions: list[str],
    events_file: str = ".spiral/spiral_events.jsonl",
) -> None:
    """Emit structured stall_warning event to spiral_events.jsonl.

    Args:
        iteration: Current iteration number.
        velocity_history: List of VelocitySnapshot for context.
        suggestions: List of actionable suggestion strings.
        events_file: Path to spiral_events.jsonl (default .spiral/spiral_events.jsonl).
    """
    import datetime

    path = Path(events_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Use timezone-aware UTC datetime (Python 3.11+)
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    # Ensure Z suffix for consistency with ISO 8601
    ts = ts.replace("+00:00", "Z")

    event = {
        "event": "stall_warning",
        "iteration": iteration,
        "timestamp": ts,
        "velocity_samples": [
            {"iteration": v.iteration, "stories_passed": v.stories_passed, "velocity": v.velocity}
            for v in velocity_history[-5:]
        ],
        "velocity_threshold": 0.5,
        "consecutive_below_threshold": 3,
        "suggestions": suggestions,
    }

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except (IOError, OSError):
        pass  # Graceful no-op if event log write fails


def check_and_warn(
    results_tsv_path: str, prd_path: str, iteration: int, events_file: str = ".spiral/spiral_events.jsonl"
) -> bool:
    """Convenience function: check velocity, detect stall, emit warning if needed.

    Args:
        results_tsv_path: Path to results.tsv.
        prd_path: Path to prd.json.
        iteration: Current iteration number.
        events_file: Path to spiral_events.jsonl.

    Returns:
        True if stall detected and warning emitted, False otherwise.
    """
    velocity_history = compute_rolling_velocity(results_tsv_path)
    is_stalled, stall_start = detect_stall(velocity_history)

    if is_stalled:
        suggestions = generate_suggestions(prd_path)
        emit_stall_warning(iteration, velocity_history, suggestions, events_file)
        return True

    return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: velocity_tracker.py <results_tsv> <prd.json> [iteration] [events_file]")
        sys.exit(1)

    results_path = sys.argv[1]
    prd_path = sys.argv[2]
    iter_num = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    events_path = sys.argv[4] if len(sys.argv) > 4 else ".spiral/spiral_events.jsonl"

    check_and_warn(results_path, prd_path, iter_num, events_path)
