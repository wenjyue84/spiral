"""tests/test_story_reorder.py — Tests for topological story sorting (US-698)."""

from __future__ import annotations

from typing import Any

import pytest

from lib.story_reorder import build_dep_graph, topological_sort


def _story(sid: str, deps: list[str] | None = None) -> dict[str, Any]:
    """Helper to create a story dict."""
    return {
        "id": sid,
        "title": f"Story {sid}",
        "dependencies": deps or [],
    }


class TestBuildDepGraph:
    """Test dependency graph building."""

    def test_empty_stories(self) -> None:
        """Empty list produces empty graph."""
        result = build_dep_graph([])
        assert result == {}

    def test_no_dependencies(self) -> None:
        """Stories with no deps have empty edges."""
        stories = [_story("US-001"), _story("US-002")]
        graph = build_dep_graph(stories)
        assert graph == {"US-001": [], "US-002": []}

    def test_with_dependencies(self) -> None:
        """Dependencies are preserved."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-001"]),
            _story("US-003", ["US-001", "US-002"]),
        ]
        graph = build_dep_graph(stories)
        assert graph["US-001"] == []
        assert graph["US-002"] == ["US-001"]
        assert graph["US-003"] == ["US-001", "US-002"]

    def test_orphan_dependencies_ignored(self) -> None:
        """Missing dependency refs are ignored."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-001", "MISSING-001"]),
        ]
        graph = build_dep_graph(stories)
        assert graph["US-002"] == ["US-001"]

    def test_story_without_id_skipped(self) -> None:
        """Stories without id are skipped."""
        stories: list[dict[str, Any]] = [
            _story("US-001"),
            {"title": "No ID Story"},
            _story("US-002"),
        ]
        graph = build_dep_graph(stories)
        assert "US-001" in graph
        assert "US-002" in graph
        assert len(graph) == 2


class TestTopologicalSort:
    """Test Kahn's algorithm topological sort."""

    def test_empty_stories(self) -> None:
        """Empty list returns empty result."""
        result = topological_sort([], {})
        assert result == []

    def test_single_story(self) -> None:
        """Single story returns unchanged."""
        stories = [_story("US-001")]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        assert len(result) == 1
        assert result[0]["id"] == "US-001"

    def test_no_dependencies(self) -> None:
        """Stories without deps return in any valid order."""
        stories = [_story("US-001"), _story("US-002")]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        assert len(result) == 2
        assert {s["id"] for s in result} == {"US-001", "US-002"}

    def test_linear_chain(self) -> None:
        """A -> B -> C produces correct order."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-001"]),
            _story("US-003", ["US-002"]),
        ]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        ids = [s["id"] for s in result]
        # US-001 before US-002 before US-003
        assert ids.index("US-001") < ids.index("US-002")
        assert ids.index("US-002") < ids.index("US-003")

    def test_diamond_dependency(self) -> None:
        """Diamond A<-B,C; B,C<-D: D before B,C before A."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-001"]),
            _story("US-003", ["US-001"]),
            _story("US-004", ["US-002", "US-003"]),
        ]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        ids = [s["id"] for s in result]
        # US-001 must come first
        assert ids.index("US-001") < ids.index("US-002")
        assert ids.index("US-001") < ids.index("US-003")
        # US-002 and US-003 must come before US-004
        assert ids.index("US-002") < ids.index("US-004")
        assert ids.index("US-003") < ids.index("US-004")

    def test_cycle_placed_at_end(self) -> None:
        """Cyclic stories placed at end in original order."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-003"]),
            _story("US-003", ["US-002"]),
        ]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        ids = [s["id"] for s in result]
        # US-001 has no deps, comes first
        assert ids[0] == "US-001"
        # US-002 and US-003 (cycle) come after, in original order
        assert ids[1] == "US-002"
        assert ids[2] == "US-003"

    def test_complex_dag(self) -> None:
        """Multi-level DAG with multiple paths."""
        stories = [
            _story("US-001"),
            _story("US-002", ["US-001"]),
            _story("US-003", ["US-001"]),
            _story("US-004", ["US-002"]),
            _story("US-005", ["US-002", "US-003"]),
        ]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        ids = [s["id"] for s in result]
        # Verify all dep ordering constraints
        for i, sid in enumerate(ids):
            story = next(s for s in stories if s["id"] == sid)
            for dep in story.get("dependencies", []):
                dep_idx = ids.index(dep)
                assert dep_idx < i, f"{dep} should come before {sid}"

    def test_all_fields_preserved(self) -> None:
        """Sort preserves all story fields."""
        stories: list[dict[str, Any]] = [
            {
                "id": "US-001",
                "title": "First",
                "description": "Desc",
                "dependencies": [],
                "passes": False,
            },
            {"id": "US-002", "title": "Second", "dependencies": ["US-001"]},
        ]
        graph = build_dep_graph(stories)
        result = topological_sort(stories, graph)
        # Check all fields preserved
        first = next(s for s in result if s["id"] == "US-001")
        assert first["title"] == "First"
        assert first["description"] == "Desc"
        assert first["passes"] is False
