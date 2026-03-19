"""Tests for lib/show_blockers.py (US-538)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from show_blockers import _build_graph, _find_cycle, _transitive_depth  # noqa: PLC2701
from show_blockers import build_dot_graph, get_story_blockers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stories(deps_map: dict[str, list[str]]) -> list[dict]:
    """Build a minimal story list from {story_id: [dep_ids]} mapping."""
    return [
        {"id": sid, "title": f"Story {sid}", "dependencies": deps}
        for sid, deps in deps_map.items()
    ]


# ---------------------------------------------------------------------------
# _build_graph
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_empty_stories(self) -> None:
        fwd, rev = _build_graph([])
        assert fwd == {}
        assert rev == {}

    def test_isolated_stories(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": []})
        fwd, rev = _build_graph(stories)
        assert fwd["US-001"] == []
        assert fwd["US-002"] == []
        assert rev["US-001"] == []
        assert rev["US-002"] == []

    def test_direct_dependency_populates_reverse(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": ["US-001"]})
        fwd, rev = _build_graph(stories)
        assert fwd["US-002"] == ["US-001"]
        assert "US-002" in rev["US-001"]

    def test_unknown_dep_ignored(self) -> None:
        """Dependencies referencing unknown story IDs are silently ignored."""
        stories = _make_stories({"US-001": ["US-999"]})
        fwd, _ = _build_graph(stories)
        assert fwd["US-001"] == []


# ---------------------------------------------------------------------------
# _transitive_depth
# ---------------------------------------------------------------------------


class TestTransitiveDepth:
    def test_no_deps_returns_zero(self) -> None:
        fwd: dict[str, list[str]] = {"US-001": []}
        assert _transitive_depth("US-001", fwd) == 0

    def test_one_level(self) -> None:
        fwd = {"US-001": [], "US-002": ["US-001"]}
        assert _transitive_depth("US-002", fwd) == 1

    def test_chain_depth(self) -> None:
        # US-004 → US-003 → US-002 → US-001
        fwd = {
            "US-001": [],
            "US-002": ["US-001"],
            "US-003": ["US-002"],
            "US-004": ["US-003"],
        }
        assert _transitive_depth("US-004", fwd) == 3

    def test_diamond_depth(self) -> None:
        # US-003 depends on both US-001 and US-002; US-002 depends on US-001
        fwd = {
            "US-001": [],
            "US-002": ["US-001"],
            "US-003": ["US-001", "US-002"],
        }
        # Longest path: US-003 → US-002 → US-001  (depth 2)
        assert _transitive_depth("US-003", fwd) == 2


# ---------------------------------------------------------------------------
# _find_cycle
# ---------------------------------------------------------------------------


class TestFindCycle:
    def test_no_cycle_returns_none(self) -> None:
        fwd = {"US-001": [], "US-002": ["US-001"]}
        assert _find_cycle("US-002", fwd) is None

    def test_self_loop(self) -> None:
        fwd = {"US-001": ["US-001"]}
        cycle = _find_cycle("US-001", fwd)
        assert cycle is not None
        assert "US-001" in cycle

    def test_two_node_cycle(self) -> None:
        fwd = {"US-001": ["US-002"], "US-002": ["US-001"]}
        cycle = _find_cycle("US-001", fwd)
        assert cycle is not None
        assert "US-001" in cycle
        assert "US-002" in cycle
        # Path should start and end with the same node
        assert cycle[0] == cycle[-1]

    def test_three_node_cycle(self) -> None:
        fwd = {
            "US-001": ["US-003"],
            "US-002": ["US-001"],
            "US-003": ["US-002"],
        }
        cycle = _find_cycle("US-001", fwd)
        assert cycle is not None
        assert len(cycle) >= 3


# ---------------------------------------------------------------------------
# get_story_blockers
# ---------------------------------------------------------------------------


class TestGetStoryBlockers:
    def test_output_keys_present(self) -> None:
        stories = _make_stories({"US-001": []})
        result = get_story_blockers("US-001", stories)
        for key in ("story_id", "blocked_by", "blocks", "transitive_closure_depth", "circular_path"):
            assert key in result, f"missing key: {key}"

    def test_isolated_story(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": []})
        result = get_story_blockers("US-001", stories)
        assert result["story_id"] == "US-001"
        assert result["blocked_by"] == []
        assert result["blocks"] == []
        assert result["transitive_closure_depth"] == 0
        assert result["circular_path"] is None

    def test_blocked_by_populated(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": ["US-001"]})
        result = get_story_blockers("US-002", stories)
        assert "US-001" in result["blocked_by"]

    def test_blocks_populated(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": ["US-001"]})
        result = get_story_blockers("US-001", stories)
        assert "US-002" in result["blocks"]

    def test_circular_path_detected(self) -> None:
        stories = _make_stories({
            "US-001": ["US-002"],
            "US-002": ["US-001"],
        })
        result = get_story_blockers("US-001", stories)
        assert result["circular_path"] is not None

    def test_no_cycle_in_dag(self) -> None:
        stories = _make_stories({
            "US-001": [],
            "US-002": ["US-001"],
            "US-003": ["US-001", "US-002"],
        })
        result = get_story_blockers("US-003", stories)
        assert result["circular_path"] is None

    def test_large_graph_transitive_closure(self) -> None:
        """Integration test: 12+ interdependent stories, chain depth == 11."""
        # US-012 → US-011 → ... → US-001 (12 stories, depth 11)
        deps_map: dict[str, list[str]] = {f"US-{i:03d}": [] for i in range(1, 13)}
        for i in range(2, 13):
            deps_map[f"US-{i:03d}"] = [f"US-{i - 1:03d}"]
        stories = _make_stories(deps_map)
        result = get_story_blockers("US-012", stories)
        assert result["transitive_closure_depth"] == 11
        assert result["circular_path"] is None

    def test_large_graph_leaf_has_zero_depth(self) -> None:
        """Root story in large chain has depth 0."""
        deps_map: dict[str, list[str]] = {f"US-{i:03d}": [] for i in range(1, 13)}
        for i in range(2, 13):
            deps_map[f"US-{i:03d}"] = [f"US-{i - 1:03d}"]
        stories = _make_stories(deps_map)
        result = get_story_blockers("US-001", stories)
        assert result["transitive_closure_depth"] == 0
        assert len(result["blocks"]) == 1  # only US-002 directly blocks on US-001


# ---------------------------------------------------------------------------
# build_dot_graph
# ---------------------------------------------------------------------------


class TestBuildDotGraph:
    def test_empty_is_valid_dot(self) -> None:
        dot = build_dot_graph([])
        assert "digraph" in dot
        assert dot.strip().endswith("}")

    def test_contains_story_nodes(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": ["US-001"]})
        dot = build_dot_graph(stories)
        assert "US-001" in dot
        assert "US-002" in dot

    def test_contains_edge(self) -> None:
        stories = _make_stories({"US-001": [], "US-002": ["US-001"]})
        dot = build_dot_graph(stories)
        assert "->" in dot
        # Edge should be US-002 -> US-001 (blocked_by direction)
        assert '"US-002" -> "US-001"' in dot

    def test_rankdir_present(self) -> None:
        dot = build_dot_graph([])
        assert "rankdir" in dot

    def test_large_graph_dot(self) -> None:
        """12+ stories produce valid DOT output with correct edge count."""
        deps_map: dict[str, list[str]] = {f"US-{i:03d}": [] for i in range(1, 13)}
        for i in range(2, 13):
            deps_map[f"US-{i:03d}"] = [f"US-{i - 1:03d}"]
        stories = _make_stories(deps_map)
        dot = build_dot_graph(stories)
        # 11 edges expected (012→011, 011→010, ..., 002→001)
        assert dot.count("->") == 11
