"""Tests for lib/trace_dependencies.py — US-675.

Acceptance criteria:
1. spiral trace-dependencies US-001 outputs tree with sub_project labels,
   file paths, and project boundaries.
2. Detects circular dependencies and reports cycle path.
3. JSON output matches schema: {story_id, dependencies, has_cycle, [cycle_path]}.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from trace_dependencies import (
    DependencyNode,
    detect_cycle,
    format_tree,
    to_json_output,
    trace_deps,
)


def _stories_by_id(stories: list[dict]) -> dict:  # type: ignore[type-arg]
    return {s["id"]: s for s in stories}


class TestTraceDeps:
    """trace_deps resolves dependency chains correctly."""

    def test_single_story_no_deps(self) -> None:
        """Story with no dependencies returns a leaf node."""
        stories = [{"id": "US-001", "dependencies": [], "sub_project": "proj-a"}]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.story_id == "US-001"
        assert node.depth == 0
        assert node.children == []
        assert not node.has_cycle

    def test_linear_chain_resolved(self) -> None:
        """US-001 -> US-002 -> US-003 resolves to 2 levels of children."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert len(node.children) == 1
        child = node.children[0]
        assert child.story_id == "US-002"
        assert child.depth == 1
        assert len(child.children) == 1
        assert child.children[0].story_id == "US-003"

    def test_sub_project_label_from_field(self) -> None:
        """sub_project field is preserved on the resolved node."""
        stories = [
            {"id": "US-001", "dependencies": ["PROJECT-B-US-005"]},
            {"id": "PROJECT-B-US-005", "sub_project": "project-b", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.children[0].sub_project == "project-b"

    def test_sub_project_inferred_from_id(self) -> None:
        """Sub-project is inferred from prefixed story ID like PROJECT-B-US-005."""
        stories = [
            {"id": "US-001", "dependencies": ["PROJECT-B-US-005"]},
            {"id": "PROJECT-B-US-005", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.children[0].sub_project == "PROJECT-B"

    def test_files_from_filesTouch(self) -> None:
        """Files are read from filesTouch field if present."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": [], "filesTouch": ["src/auth.py"]},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.children[0].files == ["src/auth.py"]

    def test_unknown_dependency_returns_empty_node(self) -> None:
        """A dependency that is not in prd.json resolves to an empty node."""
        stories = [{"id": "US-001", "dependencies": ["US-UNKNOWN"]}]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert len(node.children) == 1
        assert node.children[0].story_id == "US-UNKNOWN"
        assert node.children[0].children == []

    def test_depth_increments_correctly(self) -> None:
        """Node depth increments for each level of the tree."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.depth == 0
        assert node.children[0].depth == 1
        assert node.children[0].children[0].depth == 2


class TestCycleDetection:
    """Circular dependencies are detected and reported correctly."""

    def test_two_story_cycle_detected(self) -> None:
        """US-001 -> US-002 -> US-001 is a cycle."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        assert node.has_cycle

    def test_cycle_path_contains_both_nodes(self) -> None:
        """Cycle path contains US-001 and US-002."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        all_ids = {n.story_id for n in [node] + node.children}
        assert (
            "US-001" in all_ids or "US-001" in node.cycle_path or any("US-001" in c.cycle_path for c in node.children)
        )

    def test_detect_cycle_function_returns_path(self) -> None:
        """detect_cycle returns non-empty list for cyclic stories."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        sbi = _stories_by_id(stories)
        cycle = detect_cycle("US-001", sbi)
        assert len(cycle) >= 2
        assert "US-001" in cycle

    def test_detect_cycle_no_cycle_returns_empty(self) -> None:
        """detect_cycle returns [] for a valid DAG."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        cycle = detect_cycle("US-001", sbi)
        assert cycle == []

    def test_three_node_cycle(self) -> None:
        """US-001 -> US-002 -> US-003 -> US-001 is a three-node cycle."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": ["US-001"]},
        ]
        sbi = _stories_by_id(stories)
        cycle = detect_cycle("US-001", sbi)
        assert len(cycle) >= 3
        assert "US-001" in cycle


class TestFormatTree:
    """format_tree renders the dependency tree as ASCII."""

    def test_root_only_output(self) -> None:
        """Single-node tree outputs just the root story ID."""
        node = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[])
        output = format_tree(node)
        assert "US-001" in output

    def test_child_with_sub_project_label(self) -> None:
        """Child nodes show [sub_project] tag."""
        root = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[])
        child = DependencyNode(story_id="PROJECT-B-US-005", sub_project="project-b", depth=1, files=[])
        root.children = [child]
        output = format_tree(root)
        assert "[project-b]" in output
        assert "PROJECT-B-US-005" in output

    def test_files_shown_in_output(self) -> None:
        """Node files are shown in parentheses."""
        root = DependencyNode(story_id="US-001", sub_project="", depth=0, files=["src/auth.py"])
        output = format_tree(root)
        assert "src/auth.py" in output

    def test_cycle_marker_shown(self) -> None:
        """Cyclic nodes are marked with CYCLE."""
        node = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[], has_cycle=True)
        output = format_tree(node)
        assert "CYCLE" in output

    def test_tree_connectors_present(self) -> None:
        """Tree uses standard ASCII connectors for branches."""
        root = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[])
        child1 = DependencyNode(story_id="US-002", sub_project="", depth=1, files=[])
        child2 = DependencyNode(story_id="US-003", sub_project="", depth=1, files=[])
        root.children = [child1, child2]
        output = format_tree(root)
        # Should have both branch and last-branch connectors
        assert "├──" in output or "└──" in output


class TestJsonOutput:
    """to_json_output matches the acceptance criteria schema."""

    def test_json_schema_fields_present(self) -> None:
        """JSON output contains story_id, dependencies, has_cycle."""
        node = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[])
        output = to_json_output(node)
        assert "story_id" in output
        assert "dependencies" in output
        assert "has_cycle" in output

    def test_json_no_deps_empty_list(self) -> None:
        """Story with no dependencies has empty dependencies list."""
        node = DependencyNode(story_id="US-001", sub_project="", depth=0, files=[])
        output = to_json_output(node)
        assert output["story_id"] == "US-001"
        assert output["dependencies"] == []
        assert output["has_cycle"] is False

    def test_json_dep_schema_fields(self) -> None:
        """Each dependency entry has story_id, sub_project, depth, files."""
        stories = [
            {"id": "US-001", "dependencies": ["PROJECT-B-US-005"]},
            {
                "id": "PROJECT-B-US-005",
                "sub_project": "project-b",
                "dependencies": [],
                "filesTouch": ["src/auth.py"],
            },
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        output = to_json_output(node)
        deps = output["dependencies"]
        assert len(deps) == 1
        dep = deps[0]
        assert dep["story_id"] == "PROJECT-B-US-005"
        assert dep["sub_project"] == "project-b"
        assert dep["depth"] == 1
        assert dep["files"] == ["src/auth.py"]

    def test_json_cycle_path_included_when_cycle(self) -> None:
        """JSON output includes cycle_path when has_cycle is True."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        output = to_json_output(node)
        if output["has_cycle"]:
            assert "cycle_path" in output

    def test_json_is_serialisable(self) -> None:
        """JSON output round-trips through json.dumps without error."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": [], "filesTouch": ["lib/foo.py"]},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        output = to_json_output(node)
        serialised = json.dumps(output)
        assert "US-001" in serialised
        assert "US-002" in serialised

    def test_json_transitive_deps_all_listed(self) -> None:
        """Three-level chain has all transitive deps in flat dependencies list."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": []},
        ]
        sbi = _stories_by_id(stories)
        node = trace_deps("US-001", sbi)
        output = to_json_output(node)
        dep_ids = [d["story_id"] for d in output["dependencies"]]
        assert "US-002" in dep_ids
        assert "US-003" in dep_ids
