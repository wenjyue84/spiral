"""Tests for find_cycles() cycle detection (US-1047)."""

import pytest

from lib.federation.cycle_detector import find_cycles


class TestFindCycles:
  """Tests for find_cycles() that detects all circular dependencies."""

  def test_no_cycles(self) -> None:
    """Linear dependency chain has no cycles."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Story 1",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": [],
            },
            {
                "id": "US-002",
                "title": "Story 2",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-001"],
            },
            {
                "id": "US-003",
                "title": "Story 3",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-002"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 0

  def test_simple_two_node_cycle(self) -> None:
    """Two-node cycle: A -> B -> A."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Story A",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-002"],
            },
            {
                "id": "US-002",
                "title": "Story B",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-001"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 1
    cycle = cycles[0]
    # Cycle should be [A, B, A] or [B, A, B]
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == {"US-001", "US-002"}

  def test_three_node_cycle(self) -> None:
    """Three-node cycle: A -> B -> C -> A."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "PROJ1-001",
                "title": "Story A",
                "sub_project": "proj1",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ2-005"],
            },
            {
                "id": "PROJ2-005",
                "title": "Story B",
                "sub_project": "proj2",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ1-003"],
            },
            {
                "id": "PROJ1-003",
                "title": "Story C",
                "sub_project": "proj1",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ1-001"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 1
    cycle = cycles[0]
    # Cycle should close: first element equals last
    assert cycle[0] == cycle[-1]
    # Should contain all three IDs
    assert set(cycle[:-1]) == {"PROJ1-001", "PROJ2-005", "PROJ1-003"}

  def test_two_separate_cycles(self) -> None:
    """Two separate cycles in different sub-projects (AC requirement)."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            # Cycle 1: PROJ1-001 -> PROJ1-002 -> PROJ1-001
            {
                "id": "PROJ1-001",
                "title": "Proj1 Story A",
                "sub_project": "proj1",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ1-002"],
            },
            {
                "id": "PROJ1-002",
                "title": "Proj1 Story B",
                "sub_project": "proj1",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ1-001"],
            },
            # Cycle 2: PROJ2-001 -> PROJ2-002 -> PROJ2-003 -> PROJ2-001
            {
                "id": "PROJ2-001",
                "title": "Proj2 Story A",
                "sub_project": "proj2",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ2-002"],
            },
            {
                "id": "PROJ2-002",
                "title": "Proj2 Story B",
                "sub_project": "proj2",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ2-003"],
            },
            {
                "id": "PROJ2-003",
                "title": "Proj2 Story C",
                "sub_project": "proj2",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["PROJ2-001"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 2

    # Each cycle should be a closed loop
    for cycle in cycles:
      assert cycle[0] == cycle[-1]

    # Extract the story IDs from each cycle (excluding the closing duplicate)
    cycle_sets = [set(c[:-1]) for c in cycles]

    # One cycle should have PROJ1 stories
    assert {"PROJ1-001", "PROJ1-002"} in cycle_sets
    # One cycle should have PROJ2 stories
    assert {"PROJ2-001", "PROJ2-002", "PROJ2-003"} in cycle_sets

  def test_cycle_with_external_deps(self) -> None:
    """Cycle A->B->A with unrelated story C that depends on A."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Story A (cycle)",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-002"],
            },
            {
                "id": "US-002",
                "title": "Story B (cycle)",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-001"],
            },
            {
                "id": "US-003",
                "title": "Story C (external)",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-001"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    # Should still detect exactly 1 cycle (A->B->A)
    # External dep from C to A doesn't create new cycle
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle[0] == cycle[-1]
    assert set(cycle[:-1]) == {"US-001", "US-002"}

  def test_self_loop(self) -> None:
    """Story depends on itself."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Self-referential story",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["US-001"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 1
    cycle = cycles[0]
    assert cycle == ["US-001", "US-001"]

  def test_empty_prd(self) -> None:
    """Empty PRD with no stories."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 0

  def test_prd_with_missing_user_stories(self) -> None:
    """PRD missing userStories key."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 0

  def test_complex_multiple_cycles(self) -> None:
    """Complex graph with 3 separate cycles and acyclic parts."""
    prd_dict = {
        "productName": "Test",
        "branchName": "main",
        "userStories": [
            # Cycle 1: A -> B -> A
            {
                "id": "A",
                "title": "Story A",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["B"],
            },
            {
                "id": "B",
                "title": "Story B",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["A"],
            },
            # Cycle 2: C -> D -> E -> C
            {
                "id": "C",
                "title": "Story C",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["D"],
            },
            {
                "id": "D",
                "title": "Story D",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["E"],
            },
            {
                "id": "E",
                "title": "Story E",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["C"],
            },
            # Acyclic: F -> A
            {
                "id": "F",
                "title": "Story F",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": ["A"],
            },
        ],
    }
    cycles = find_cycles(prd_dict)
    assert len(cycles) == 2
    cycle_sets = [set(c[:-1]) for c in cycles]
    assert {"A", "B"} in cycle_sets
    assert {"C", "D", "E"} in cycle_sets
