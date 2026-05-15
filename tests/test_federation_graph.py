"""Tests for US-1327: federation_graph module (DAG builder and cycle detector)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from federation_graph import build_dag, detect_cycles


class TestBuildDAG:
    """Test build_dag() function."""

    def test_build_dag_with_cycle(self) -> None:
        """Test build_dag with cyclic dependencies (A→B→C→A)."""
        fixture_path = "tests/fixtures/multi-project-prd/project-a/prd.json"
        dag = build_dag(fixture_path)

        # Should return a non-empty dict
        assert isinstance(dag, dict)
        assert len(dag) > 0

        # All keys should be absolute paths
        for key in dag.keys():
            assert os.path.isabs(key), f"Expected absolute path, got {key}"

        # Should have entries for all three projects
        abs_paths = set(key for key in dag.keys())
        assert len(abs_paths) >= 3, f"Expected at least 3 projects, got {len(abs_paths)}"

    def test_build_dag_returns_reachable_projects(self) -> None:
        """Test that build_dag includes all reachable projects."""
        fixture_path = "tests/fixtures/multi-project-prd/project-a/prd.json"
        dag = build_dag(fixture_path)

        # Convert to relative paths for easier assertion
        abs_root = str(Path(fixture_path).resolve())
        prd_a = abs_root
        prd_b = str(Path("tests/fixtures/multi-project-prd/project-b/prd.json").resolve())
        prd_c = str(Path("tests/fixtures/multi-project-prd/project-c/prd.json").resolve())

        # All three should be in the DAG
        assert prd_a in dag
        assert prd_b in dag
        assert prd_c in dag

    def test_build_dag_edges(self) -> None:
        """Test that edges in DAG are correct."""
        fixture_path = "tests/fixtures/multi-project-prd/project-a/prd.json"
        dag = build_dag(fixture_path)

        abs_root = str(Path(fixture_path).resolve())
        prd_a = abs_root
        prd_b = str(Path("tests/fixtures/multi-project-prd/project-b/prd.json").resolve())
        prd_c = str(Path("tests/fixtures/multi-project-prd/project-c/prd.json").resolve())

        # prd_a should include prd_b
        assert len(dag[prd_a]) > 0
        assert prd_b in dag[prd_a]

        # prd_b should include prd_c
        assert len(dag[prd_b]) > 0
        assert prd_c in dag[prd_b]

        # prd_c should include prd_a (closing the cycle)
        assert len(dag[prd_c]) > 0
        assert prd_a in dag[prd_c]


class TestDetectCycles:
    """Test detect_cycles() function."""

    def test_detect_cycles_in_cyclic_graph(self) -> None:
        """Test detect_cycles detects a cycle (A→B→C→A)."""
        fixture_path = "tests/fixtures/multi-project-prd/project-a/prd.json"
        dag = build_dag(fixture_path)

        has_cycle, cycle_nodes = detect_cycles(dag)

        # Should detect the cycle
        assert has_cycle is True
        assert len(cycle_nodes) > 0

        # Cycle should contain all three nodes
        prd_a = str(Path(fixture_path).resolve())
        prd_b = str(Path("tests/fixtures/multi-project-prd/project-b/prd.json").resolve())
        prd_c = str(Path("tests/fixtures/multi-project-prd/project-c/prd.json").resolve())

        cycle_set = set(cycle_nodes)
        assert prd_a in cycle_set or prd_b in cycle_set or prd_c in cycle_set

    def test_detect_cycles_linear_graph(self) -> None:
        """Test detect_cycles on a linear acyclic graph (A→B→C)."""
        # Create a simple linear graph
        graph: dict[str, list[str]] = {
            "A": ["B"],
            "B": ["C"],
            "C": [],
        }

        has_cycle, cycle_nodes = detect_cycles(graph)

        # Should not detect a cycle
        assert has_cycle is False
        assert cycle_nodes == []

    def test_detect_cycles_empty_graph(self) -> None:
        """Test detect_cycles on an empty graph."""
        graph: dict[str, list[str]] = {}

        has_cycle, cycle_nodes = detect_cycles(graph)

        assert has_cycle is False
        assert cycle_nodes == []

    def test_detect_cycles_single_node(self) -> None:
        """Test detect_cycles with a single isolated node."""
        graph: dict[str, list[str]] = {
            "A": [],
        }

        has_cycle, cycle_nodes = detect_cycles(graph)

        assert has_cycle is False
        assert cycle_nodes == []

    def test_detect_cycles_self_loop(self) -> None:
        """Test detect_cycles detects a self-loop (A→A)."""
        graph: dict[str, list[str]] = {
            "A": ["A"],
        }

        has_cycle, cycle_nodes = detect_cycles(graph)

        assert has_cycle is True
        assert "A" in cycle_nodes

    def test_detect_cycles_two_node_cycle(self) -> None:
        """Test detect_cycles detects a two-node cycle (A→B→A)."""
        graph: dict[str, list[str]] = {
            "A": ["B"],
            "B": ["A"],
        }

        has_cycle, cycle_nodes = detect_cycles(graph)

        assert has_cycle is True
        assert "A" in cycle_nodes
        assert "B" in cycle_nodes

    def test_detect_cycles_complex_graph(self) -> None:
        """Test detect_cycles on a complex graph with acyclic and cyclic parts."""
        # D→E (acyclic), A→B→C→A (cyclic)
        graph: dict[str, list[str]] = {
            "A": ["B"],
            "B": ["C"],
            "C": ["A"],
            "D": ["E"],
            "E": [],
        }

        has_cycle, cycle_nodes = detect_cycles(graph)

        assert has_cycle is True
        # Should contain nodes from the cycle
        assert "A" in cycle_nodes
        assert "B" in cycle_nodes
        assert "C" in cycle_nodes
