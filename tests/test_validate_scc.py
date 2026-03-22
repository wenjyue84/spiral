"""Integration tests for validate_scc.py — Tarjan's SCC cycle detection (US-725)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from validate_scc import build_graph, find_cycles, tarjan_scc  # noqa: E402

# ---------------------------------------------------------------------------
# Unit tests for the core library
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_empty_stories(self) -> None:
        graph = build_graph([])
        assert graph == {}

    def test_no_dependencies(self) -> None:
        stories = [{"id": "US-001"}, {"id": "US-002"}]
        graph = build_graph(stories)
        assert graph == {"US-001": [], "US-002": []}

    def test_known_dep_included(self) -> None:
        stories = [
            {"id": "US-001", "_dependencies": ["US-002"]},
            {"id": "US-002"},
        ]
        graph = build_graph(stories)
        assert graph["US-001"] == ["US-002"]
        assert graph["US-002"] == []

    def test_unknown_dep_excluded(self) -> None:
        """Dependencies pointing to unknown story IDs are ignored."""
        stories = [{"id": "US-001", "_dependencies": ["UNKNOWN-999"]}]
        graph = build_graph(stories)
        assert graph["US-001"] == []


class TestTarjanSCC:
    def test_empty_graph(self) -> None:
        sccs = tarjan_scc({})
        assert sccs == []

    def test_no_edges(self) -> None:
        graph = {"A": [], "B": [], "C": []}
        sccs = tarjan_scc(graph)
        # All trivial SCCs
        assert len(sccs) == 3
        for scc in sccs:
            assert len(scc) == 1

    def test_simple_cycle(self) -> None:
        graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
        sccs = tarjan_scc(graph)
        cycle_sccs = [s for s in sccs if len(s) > 1]
        assert len(cycle_sccs) == 1
        assert set(cycle_sccs[0]) == {"A", "B", "C"}

    def test_self_loop(self) -> None:
        graph = {"A": ["A"]}
        sccs = tarjan_scc(graph)
        assert len(sccs) == 1
        assert sccs[0] == ["A"]


class TestFindCycles:
    def test_empty_prd(self) -> None:
        result = find_cycles({})
        assert result["acyclic"] is True
        assert result["cycles"] == []
        assert result["cycle_paths"] == []

    def test_linear_dag_no_cycles(self) -> None:
        """Linear chain: US-201 → US-202 → US-203 has no cycles."""
        prd = {
            "userStories": [
                {"id": "US-201"},
                {"id": "US-202", "_dependencies": ["US-201"]},
                {"id": "US-203", "_dependencies": ["US-202"]},
            ]
        }
        result = find_cycles(prd)
        assert result["acyclic"] is True
        assert result["cycles"] == []
        assert result["cycle_paths"] == []

    def test_three_story_cycle(self) -> None:
        """US-101 → US-103, US-102 → US-101, US-103 → US-102 forms a cycle."""
        prd = {
            "userStories": [
                {"id": "US-101", "_dependencies": ["US-103"]},
                {"id": "US-102", "_dependencies": ["US-101"]},
                {"id": "US-103", "_dependencies": ["US-102"]},
            ]
        }
        result = find_cycles(prd)
        assert result["acyclic"] is False
        assert len(result["cycles"]) == 1
        cycle_members = set(result["cycles"][0])
        assert cycle_members == {"US-101", "US-102", "US-103"}
        # Cycle path should mention all three stories and close back to the start
        assert len(result["cycle_paths"]) == 1
        path = result["cycle_paths"][0]
        assert "US-101" in path
        assert "US-102" in path
        assert "US-103" in path
        # Path must close the loop (start == end)
        parts = path.split(" → ")
        assert parts[0] == parts[-1], f"Cycle path must close: {path}"

    def test_self_loop_cycle(self) -> None:
        """A story that depends on itself is a cycle."""
        prd = {
            "userStories": [
                {"id": "US-001", "_dependencies": ["US-001"]},
            ]
        }
        result = find_cycles(prd)
        assert result["acyclic"] is False
        assert len(result["cycles"]) == 1
        assert result["cycles"][0] == ["US-001"]
        assert result["cycle_paths"][0] == "US-001 → US-001"

    def test_two_node_mutual_cycle(self) -> None:
        prd = {
            "userStories": [
                {"id": "US-A", "_dependencies": ["US-B"]},
                {"id": "US-B", "_dependencies": ["US-A"]},
            ]
        }
        result = find_cycles(prd)
        assert result["acyclic"] is False
        assert len(result["cycles"]) == 1
        assert set(result["cycles"][0]) == {"US-A", "US-B"}

    def test_ignores_dependencies_field(self) -> None:
        """Only _dependencies is read; story.dependencies is ignored."""
        prd = {
            "userStories": [
                {"id": "US-X", "dependencies": ["US-Y"]},  # old field — ignored
                {"id": "US-Y", "dependencies": ["US-X"]},  # old field — ignored
            ]
        }
        result = find_cycles(prd)
        # No _dependencies set, so no cycles
        assert result["acyclic"] is True

    def test_unknown_deps_do_not_cause_cycles(self) -> None:
        prd = {
            "userStories": [
                {"id": "US-001", "_dependencies": ["UNKNOWN-999"]},
            ]
        }
        result = find_cycles(prd)
        assert result["acyclic"] is True


# ---------------------------------------------------------------------------
# CLI integration tests (subprocess)
# ---------------------------------------------------------------------------


def _write_prd(stories: list[dict]) -> str:
    """Write a temp prd.json and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"userStories": stories}, tmp)
    tmp.flush()
    tmp.close()
    return tmp.name


class TestCLI:
    def test_cli_acyclic_exits_0(self) -> None:
        prd_path = _write_prd(
            [
                {"id": "US-201"},
                {"id": "US-202", "_dependencies": ["US-201"]},
            ]
        )
        try:
            result = subprocess.run(
                [sys.executable, "main.py", "validate-scc-cycles", prd_path],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent),
            )
            assert result.returncode == 0, f"Expected exit 0; stderr: {result.stderr}"
            data = json.loads(result.stdout)
            assert data["acyclic"] is True
            assert data["cycles"] == []
        finally:
            os.unlink(prd_path)

    def test_cli_cycle_exits_1(self) -> None:
        prd_path = _write_prd(
            [
                {"id": "US-101", "_dependencies": ["US-103"]},
                {"id": "US-102", "_dependencies": ["US-101"]},
                {"id": "US-103", "_dependencies": ["US-102"]},
            ]
        )
        try:
            result = subprocess.run(
                [sys.executable, "main.py", "validate-scc-cycles", prd_path],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent.parent),
            )
            assert result.returncode == 1, f"Expected exit 1; got {result.returncode}"
            data = json.loads(result.stdout)
            assert data["acyclic"] is False
            assert len(data["cycles"]) == 1
            assert set(data["cycles"][0]) == {"US-101", "US-102", "US-103"}
            # stderr should mention cycle path
            assert "cycle:" in result.stderr
        finally:
            os.unlink(prd_path)

    def test_cli_missing_file_exits_1(self) -> None:
        result = subprocess.run(
            [sys.executable, "main.py", "validate-scc-cycles", "nonexistent_prd.json"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 1
