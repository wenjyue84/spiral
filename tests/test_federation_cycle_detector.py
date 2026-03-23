"""Tests for federation cycle detection (US-1047)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from federation.cycle_detector import find_cycles


def test_find_cycles_no_cycles() -> None:
    """Test detection returns empty list when no cycles exist."""
    prd = {
        "userStories": [
            {"id": "US-100", "dependencies": []},
            {"id": "US-101", "dependencies": ["US-100"]},
            {"id": "US-102", "dependencies": ["US-101"]},
        ]
    }
    cycles = find_cycles(prd)
    assert cycles == []


def test_find_cycles_simple_cycle() -> None:
    """Test detection of a simple 2-story cycle."""
    prd = {
        "userStories": [
            {"id": "US-100", "dependencies": ["US-101"]},
            {"id": "US-101", "dependencies": ["US-100"]},
        ]
    }
    cycles = find_cycles(prd)
    assert len(cycles) == 1
    cycle = cycles[0]
    # Cycle should be [a, b, a] where a->b->a
    assert len(cycle) == 3
    assert cycle[0] == cycle[2]  # Ends with same ID


def test_find_cycles_three_story_cycle() -> None:
    """Test detection of a 3-story cycle."""
    prd = {
        "userStories": [
            {"id": "US-100", "dependencies": ["US-101"]},
            {"id": "US-101", "dependencies": ["US-102"]},
            {"id": "US-102", "dependencies": ["US-100"]},
        ]
    }
    cycles = find_cycles(prd)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert len(cycle) == 4  # [a, b, c, a]
    assert cycle[0] == cycle[3]


def test_find_cycles_multiple_cycles() -> None:
    """Test detection of multiple separate cycles in different sub-projects."""
    prd = {
        "userStories": [
            # Cycle 1: US-100 <-> US-101
            {"id": "US-100", "dependencies": ["US-101"]},
            {"id": "US-101", "dependencies": ["US-100"]},
            # Cycle 2: US-200 <-> US-201
            {"id": "US-200", "dependencies": ["US-201"]},
            {"id": "US-201", "dependencies": ["US-200"]},
        ]
    }
    cycles = find_cycles(prd)
    assert len(cycles) == 2


def test_find_cycles_cycle_with_non_existent_dependency() -> None:
    """Test that cycles ignore dependencies on non-existent stories."""
    prd = {
        "userStories": [
            {"id": "US-100", "dependencies": ["US-999"]},  # US-999 doesn't exist
            {"id": "US-101", "dependencies": ["US-100"]},
        ]
    }
    cycles = find_cycles(prd)
    # US-100 -> US-999 link is ignored, so no cycle
    assert cycles == []


def test_find_cycles_missing_dependencies_field() -> None:
    """Test that missing dependencies field is handled gracefully."""
    prd = {
        "userStories": [
            {"id": "US-100"},  # No dependencies field
            {"id": "US-101", "dependencies": ["US-100"]},
        ]
    }
    cycles = find_cycles(prd)
    assert cycles == []


def test_find_cycles_empty_stories() -> None:
    """Test that empty PRD returns no cycles."""
    prd = {"userStories": []}
    cycles = find_cycles(prd)
    assert cycles == []


def test_find_cycles_single_story_self_loop() -> None:
    """Test detection of a story depending on itself."""
    prd = {
        "userStories": [
            {"id": "US-100", "dependencies": ["US-100"]},
        ]
    }
    cycles = find_cycles(prd)
    assert len(cycles) == 1
    assert cycles[0] == ["US-100", "US-100"]


def test_find_cycles_complex_graph() -> None:
    """Test federated prd.json with 2 cycles in different sub-projects."""
    prd = {
        "userStories": [
            # Cycle 1 in sub-project A
            {"id": "US-100", "sub_project": "A", "dependencies": ["US-101"]},
            {"id": "US-101", "sub_project": "A", "dependencies": ["US-100"]},
            # Independent chain in sub-project B
            {"id": "US-200", "sub_project": "B", "dependencies": ["US-201"]},
            {"id": "US-201", "sub_project": "B", "dependencies": []},
            # Cycle 2 in sub-project B
            {"id": "US-202", "sub_project": "B", "dependencies": ["US-203"]},
            {"id": "US-203", "sub_project": "B", "dependencies": ["US-202"]},
        ]
    }
    cycles = find_cycles(prd)
    # Should find exactly 2 cycles
    assert len(cycles) == 2
