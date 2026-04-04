"""Tests for lib.dag_validator."""

from __future__ import annotations

import pytest

from lib.dag_validator import (
    detect_cycles,
    detect_orphans,
    format_cycle_chain,
    get_deadlock_ratio,
    validate_all,
)


def test_detect_cycles_finds_circular_dependency() -> None:
    """AC1: Detect cycles via topological sort."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": ["C"]},
        {"id": "C", "dependencies": ["A"]},
    ]
    cycles = detect_cycles(stories)
    assert len(cycles) == 1
    cycle = cycles[0]
    # Cycle should be A->B->C->A (or equivalent rotation)
    assert cycle[-1] == cycle[0], "Cycle should end with start node"
    assert set(cycle[:-1]) == {"A", "B", "C"}


def test_detect_cycles_clean_dag_passes() -> None:
    """AC1: Clean DAG has no cycles."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": []},
        {"id": "C", "dependencies": ["B"]},
    ]
    cycles = detect_cycles(stories)
    assert cycles == []


def test_detect_cycles_multiple_independent_cycles() -> None:
    """Detect multiple separate cycles."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": ["A"]},
        {"id": "C", "dependencies": ["D"]},
        {"id": "D", "dependencies": ["C"]},
    ]
    cycles = detect_cycles(stories)
    assert len(cycles) == 2
    # Each cycle should have 3 nodes (start + path + start)
    assert all(len(c) == 3 for c in cycles)


def test_detect_orphans_finds_missing_dependency() -> None:
    """AC2: Detect stories depending on non-existent IDs."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": ["NONEXISTENT"]},
    ]
    orphans = detect_orphans(stories)
    assert ("B", "NONEXISTENT") in orphans


def test_detect_orphans_clean_dependencies() -> None:
    """Clean dependencies have no orphans."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": ["C"]},
        {"id": "C", "dependencies": []},
    ]
    orphans = detect_orphans(stories)
    assert orphans == []


def test_detect_orphans_empty_dependencies() -> None:
    """Empty or missing dependencies is OK."""
    stories = [
        {"id": "A"},
        {"id": "B", "dependencies": []},
        {"id": "C", "dependencies": None},
    ]
    orphans = detect_orphans(stories)
    assert orphans == []


def test_deadlock_ratio_threshold_20_percent() -> None:
    """AC3: Deadlock ratio > 20% triggers skip."""
    # 10 stories: 3 pending, 1 in cycle = 33% deadlocked
    stories = [
        {"id": "A", "dependencies": ["B"], "passes": False},
        {"id": "B", "dependencies": ["A"], "passes": False},  # In cycle
        {"id": "C", "dependencies": [], "passes": False},
        {"id": "D", "dependencies": [], "passes": True},
    ]
    ratio = get_deadlock_ratio(stories)
    # Pending: A (in cycle), B (in cycle), C (clean) = 3
    # Deadlocked: A, B = 2 out of 3 = 66%
    assert ratio > 0.2
    assert ratio == pytest.approx(2 / 3)


def test_deadlock_ratio_zero_when_no_deadlocks() -> None:
    """Clean DAG has 0.0 deadlock ratio."""
    stories = [
        {"id": "A", "dependencies": ["B"], "passes": False},
        {"id": "B", "dependencies": [], "passes": False},
    ]
    ratio = get_deadlock_ratio(stories)
    assert ratio == 0.0


def test_deadlock_ratio_zero_when_no_pending() -> None:
    """All passed stories: 0.0 deadlock ratio."""
    stories = [
        {"id": "A", "dependencies": ["B"], "passes": True},
        {"id": "B", "dependencies": ["A"], "passes": True},
    ]
    ratio = get_deadlock_ratio(stories)
    assert ratio == 0.0


def test_validate_all_returns_tuple() -> None:
    """AC3: validate_all() returns (has_issues, cycles, orphans, ratio)."""
    stories = [
        {"id": "A", "dependencies": ["B"]},
        {"id": "B", "dependencies": ["A"]},
    ]
    has_issues, cycles, orphans, ratio = validate_all(stories)
    assert has_issues is True
    assert len(cycles) == 1
    assert orphans == []
    assert ratio >= 0.0


def test_format_cycle_chain() -> None:
    """AC1: Format cycle as A->B->C->A."""
    cycle = ["A", "B", "C", "A"]
    formatted = format_cycle_chain(cycle)
    assert formatted == "A->B->C->A"


def test_detect_cycles_self_loop() -> None:
    """Detect self-loop (A depends on A)."""
    stories = [
        {"id": "A", "dependencies": ["A"]},
    ]
    cycles = detect_cycles(stories)
    assert len(cycles) == 1
    assert "A" in cycles[0]


def test_deadlock_ratio_with_orphans() -> None:
    """Orphaned dependencies count toward deadlock ratio."""
    stories = [
        {"id": "A", "dependencies": ["MISSING"], "passes": False},
        {"id": "B", "dependencies": [], "passes": False},
    ]
    ratio = get_deadlock_ratio(stories)
    # Pending: A (orphaned), B (clean) = 2
    # Deadlocked: A = 1 out of 2 = 50%
    assert ratio == pytest.approx(0.5)
