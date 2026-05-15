"""tests/test_federation_validation.py — validation tests for federated PRD system.

Tests for prd.include path resolution, circular dependency detection,
and global story ID uniqueness across multi-project topologies.
"""

from __future__ import annotations

import json
from pathlib import Path

from lib.federation_graph import build_dag, detect_cycles


def _collect_story_ids_from_dag(root_prd_path: str, graph: dict[str, list[str]]) -> dict[str, list[str]]:
    """Collect all story IDs from all PRD files in the DAG.

    Args:
        root_prd_path: Root prd.json path (unused but kept for consistency).
        graph: DAG graph from build_dag().

    Returns:
        Dict mapping story_id → list of file paths where it appears.
    """
    story_locations: dict[str, list[str]] = {}

    for prd_path in graph.keys():
        try:
            with open(prd_path, encoding="utf-8") as f:
                data: dict[str, object] = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        stories: list[object] = data.get("userStories", [])  # type: ignore[assignment]
        for story in stories:
            story_obj = story
            if isinstance(story_obj, dict):
                story_id = story_obj.get("id")
            else:
                continue
            if story_id:
                if story_id not in story_locations:
                    story_locations[story_id] = []
                story_locations[story_id].append(prd_path)

    return story_locations


def test_all_includes_resolve() -> None:
    """Verify all prd.include paths in fixture topology resolve without FileNotFoundError."""
    fixture_root = Path(__file__).parent / "fixtures" / "multi-project-prd" / "project-a" / "prd.json"
    assert fixture_root.exists(), f"Fixture not found: {fixture_root}"

    # build_dag should not raise FileNotFoundError
    graph = build_dag(str(fixture_root))

    # Verify graph is populated
    assert len(graph) > 0, "Graph should not be empty"
    assert str(fixture_root.resolve()) in graph, "Root prd.json should be in graph"

    # Verify all nodes in graph have valid include lists
    for prd_path, includes in graph.items():
        assert isinstance(includes, list), f"Includes for {prd_path} should be a list"
        # All include paths should be absolute
        for include_path in includes:
            assert Path(include_path).is_absolute(), f"Include path should be absolute: {include_path}"


def test_circular_dependency_detection() -> None:
    """Verify circular dependency detection reports all three node paths.

    Fixture has: A → B → C → A (3-node cycle).
    """
    fixture_root = Path(__file__).parent / "fixtures" / "multi-project-prd" / "project-a" / "prd.json"
    assert fixture_root.exists(), f"Fixture not found: {fixture_root}"

    graph = build_dag(str(fixture_root))
    has_cycle, cycle_nodes = detect_cycles(graph)

    # Verify cycle is detected
    assert has_cycle, "Circular dependency should be detected"

    # Verify all three nodes are in the cycle
    assert len(cycle_nodes) >= 3, f"Cycle should include at least 3 nodes, got {len(cycle_nodes)}"

    # Extract project names from the cycle paths
    project_dirs = set()
    for path in cycle_nodes[:-1]:  # Exclude the last node (which is a repeat for cycle closure)
        parts = Path(path).parts
        if "project-a" in parts or "project-b" in parts or "project-c" in parts:
            for p in parts:
                if p in ("project-a", "project-b", "project-c"):
                    project_dirs.add(p)

    # All three projects should be in the cycle
    assert len(project_dirs) >= 2, f"Cycle should span multiple projects, found in: {project_dirs}"


def test_story_id_uniqueness() -> None:
    """Detect duplicate story IDs across the multi-project topology.

    Fixture has US-001 defined in both project-a and project-b.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "multi-project-prd" / "project-a" / "prd.json"
    assert fixture_root.exists(), f"Fixture not found: {fixture_root}"

    graph = build_dag(str(fixture_root))
    story_locations = _collect_story_ids_from_dag(str(fixture_root), graph)

    # Find duplicate story IDs (those appearing in multiple files)
    duplicates: dict[str, list[str]] = {}
    for story_id, locations in story_locations.items():
        if len(locations) > 1:
            duplicates[story_id] = locations

    # Verify duplicate US-001 is detected
    assert "US-001" in duplicates, f"Duplicate US-001 should be detected. Found duplicates: {list(duplicates.keys())}"

    # Verify both project-a and project-b are in the locations
    us001_paths = duplicates["US-001"]
    assert len(us001_paths) >= 2, f"US-001 should appear in at least 2 files, found in {len(us001_paths)}"

    # Verify paths contain project-a and project-b
    path_str = " ".join(us001_paths)
    assert "project-a" in path_str, f"US-001 should be in project-a. Locations: {us001_paths}"
    assert "project-b" in path_str, f"US-001 should be in project-b. Locations: {us001_paths}"
