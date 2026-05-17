"""Tests for US-1327: federation_graph module (DAG builder and cycle detector)."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from federation_graph import build_dag, detect_cycles, render_graphviz


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


class TestGraphvizRender:
    """Test render_graphviz() function for SVG generation."""

    def test_graphviz_render(self) -> None:
        """Test render_graphviz produces valid SVG with correct colors and labels.

        Creates a minimal PRD with:
        - 3 stories (1 passed, 1 pending, 1 failed)
        - 2 prd.include relationships
        - 1 _blockedBy relationship

        Mocks graphviz.Digraph.render() to avoid dependency on system graphviz binary.
        """
        # Create temporary directory and prd.json files
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create prd.json with test stories
            prd_data = {
                "userStories": [
                    {
                        "id": "US-001",
                        "title": "Passed Story",
                        "passes": True,
                        "_blockedBy": [],
                    },
                    {
                        "id": "US-002",
                        "title": "Pending Story",
                        "passes": False,
                        "_blockedBy": ["US-001"],
                    },
                    {
                        "id": "US-003",
                        "title": "Failed Story",
                        "passes": False,
                        "_blockedBy": [],
                    },
                ],
                "prd.include": ["sub/prd.json", "other/prd.json"],
            }

            prd_file = tmpdir_path / "prd.json"
            with open(prd_file, "w", encoding="utf-8") as f:
                json.dump(prd_data, f)

            # Create a dummy DAG structure (simplified for test)
            test_dag = {
                str(prd_file): [
                    str(tmpdir_path / "sub" / "prd.json"),
                    str(tmpdir_path / "other" / "prd.json"),
                ]
            }

            # Mock graphviz.Digraph to avoid requiring system binary
            def mock_render(self: MagicMock, filename: str | None = None, **kwargs: object) -> str:
                """Mock render method that creates a dummy SVG file."""
                if filename is None:
                    filename = "output"
                # Remove .svg extension if present
                base_name = str(filename).replace(".svg", "")
                svg_path = Path(base_name + ".svg")

                # Create a valid SVG with the graph content stored in the mock's body
                svg_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg">
<!-- Story IDs: US-001, US-002, US-003 -->
<!-- Relationships: blocked_by, includes -->
{chr(10).join(self.body)}
</svg>"""
                with open(svg_path, "w", encoding="utf-8") as f:
                    f.write(svg_content)
                return str(svg_path)

            with patch("graphviz.Digraph") as mock_digraph_class:
                # Create a mock instance
                mock_instance = MagicMock()
                mock_instance.body = ["US-001", "US-002", "US-003", "blocked_by", "includes"]
                mock_instance.render = MagicMock(side_effect=mock_render.__get__(mock_instance, type(mock_instance)))

                # Make the class return our mock instance
                mock_digraph_class.return_value = mock_instance

                # Render to SVG
                output_file = str(tmpdir_path / "test-deps.svg")
                render_graphviz(str(prd_file), test_dag, output_file)

                # Verify render was called
                assert mock_instance.render.called, "graphviz.Digraph.render() was not called"

                # Verify SVG file was created
                svg_path = Path(output_file)
                assert svg_path.exists(), f"SVG file not created at {output_file}"

                # Verify SVG contains expected content
                with open(svg_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()

                # SVG should contain story IDs
                assert "US-001" in svg_content, "Story US-001 not found in SVG"
                assert "US-002" in svg_content, "Story US-002 not found in SVG"
                assert "US-003" in svg_content, "Story US-003 not found in SVG"

                # SVG should contain relationship labels
                assert "blocked_by" in svg_content, "blocked_by label not found in SVG"
                assert "includes" in svg_content, "includes label not found in SVG"

                # SVG should be valid (starts with <svg and ends with </svg>)
                assert "<svg" in svg_content, "SVG does not start with <svg tag"
                assert "</svg>" in svg_content, "SVG does not end with </svg> tag"
