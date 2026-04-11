"""tests/test_check_federated_deps.py — Tests for check-federated-deps CLI (US-685)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from check_federated_deps import (
    check_namespaces,
    find_all_cycles,
    find_orphans,
    validate,
)


class TestFindAllCycles:
    """Test cycle detection in dependency graphs."""

    def test_no_cycles(self) -> None:
        """A→B, C→D with no cycles."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": []},
            {"id": "US-003", "dependencies": ["US-004"]},
            {"id": "US-004", "dependencies": []},
        ]
        assert find_all_cycles(stories) == []

    def test_simple_cycle_two_nodes(self) -> None:
        """A→B→A cycle."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
        ]
        cycles = find_all_cycles(stories)
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle[0] == cycle[-1]  # Cycle path ends at start
        assert set(cycle[:-1]) == {"US-001", "US-002"}

    def test_three_node_cycle(self) -> None:
        """A→B→C→A cycle."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": ["US-001"]},
        ]
        cycles = find_all_cycles(stories)
        assert len(cycles) == 1
        cycle = cycles[0]
        assert cycle[0] == cycle[-1]
        assert set(cycle[:-1]) == {"US-001", "US-002", "US-003"}

    def test_multiple_independent_cycles(self) -> None:
        """A→B→A and C→D→C cycles."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-001"]},
            {"id": "US-003", "dependencies": ["US-004"]},
            {"id": "US-004", "dependencies": ["US-003"]},
        ]
        cycles = find_all_cycles(stories)
        assert len(cycles) == 2
        cycle_sets = [frozenset(c[:-1]) for c in cycles]
        assert frozenset({"US-001", "US-002"}) in cycle_sets
        assert frozenset({"US-003", "US-004"}) in cycle_sets

    def test_cycle_with_external_deps(self) -> None:
        """A→B→C→A cycle with D→A external dep."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": ["US-003"]},
            {"id": "US-003", "dependencies": ["US-001"]},
            {"id": "US-004", "dependencies": ["US-001"]},
        ]
        cycles = find_all_cycles(stories)
        assert len(cycles) == 1
        assert set(cycles[0][:-1]) == {"US-001", "US-002", "US-003"}

    def test_empty_stories(self) -> None:
        """Empty stories list."""
        assert find_all_cycles([]) == []


class TestFindOrphans:
    """Test orphan detection (missing dependencies)."""

    def test_no_orphans(self) -> None:
        """All dependencies exist."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002"]},
            {"id": "US-002", "dependencies": []},
        ]
        assert find_orphans(stories) == []

    def test_single_orphan(self) -> None:
        """US-001 depends on non-existent US-999."""
        stories = [
            {"id": "US-001", "dependencies": ["US-999"]},
        ]
        assert find_orphans(stories) == ["US-999"]

    def test_multiple_orphans(self) -> None:
        """Multiple missing dependencies."""
        stories = [
            {"id": "US-001", "dependencies": ["US-999", "US-888"]},
        ]
        orphans = find_orphans(stories)
        assert set(orphans) == {"US-999", "US-888"}

    def test_orphans_with_valid_deps(self) -> None:
        """Mix of valid and orphan dependencies."""
        stories = [
            {"id": "US-001", "dependencies": ["US-002", "US-999"]},
            {"id": "US-002", "dependencies": []},
        ]
        assert find_orphans(stories) == ["US-999"]

    def test_empty_stories(self) -> None:
        """Empty stories list."""
        assert find_orphans([]) == []

    def test_no_dependencies_field(self) -> None:
        """Stories without dependencies field."""
        stories = [
            {"id": "US-001"},
        ]
        assert find_orphans(stories) == []


class TestCheckNamespaces:
    """Test namespace validation."""

    def test_valid_namespaces(self) -> None:
        """All stories have consistent namespaces."""
        stories = [
            {"id": "US-001", "sub_project": "core"},
            {"id": "US-002", "sub_project": "core"},
            {"id": "PROJECT-B-US-003", "sub_project": "PROJECT-B"},
        ]
        result = check_namespaces(stories)
        assert result["valid"] is True
        assert result["conflicts"] == []
        assert "core" in result["namespaces"]
        assert "PROJECT-B" in result["namespaces"]

    def test_inferred_namespace_no_explicit(self) -> None:
        """Namespaces inferred from story ID prefix."""
        stories = [
            {"id": "PROJECT-A-US-001"},
            {"id": "PROJECT-A-US-002"},
            {"id": "PROJECT-B-US-003"},
        ]
        result = check_namespaces(stories)
        assert result["valid"] is True
        assert set(result["namespaces"]["PROJECT-A"]) == {
            "PROJECT-A-US-001",
            "PROJECT-A-US-002",
        }
        assert result["namespaces"]["PROJECT-B"] == ["PROJECT-B-US-003"]

    def test_namespace_conflict_explicit_vs_inferred(self) -> None:
        """Explicit sub_project conflicts with inferred prefix."""
        stories = [
            {
                "id": "PROJECT-A-US-001",
                "sub_project": "other",
            },
        ]
        result = check_namespaces(stories)
        assert result["valid"] is False
        assert len(result["conflicts"]) == 1
        assert "PROJECT-A-US-001" in result["conflicts"][0]

    def test_empty_stories(self) -> None:
        """Empty stories list."""
        result = check_namespaces([])
        assert result["valid"] is True
        assert result["namespaces"] == {}
        assert result["conflicts"] == []


class TestValidate:
    """Test full federated validation."""

    def test_valid_prd(self) -> None:
        """Valid prd.json with no issues."""
        prd = {
            "userStories": [
                {"id": "US-001", "dependencies": ["US-002"]},
                {"id": "US-002", "dependencies": []},
            ]
        }
        result = validate(prd)
        assert result["valid"] is True
        assert result["cycles"] == []
        assert result["orphans"] == []

    def test_prd_with_cycle(self) -> None:
        """prd.json with cycle."""
        prd = {
            "userStories": [
                {"id": "US-001", "dependencies": ["US-002"]},
                {"id": "US-002", "dependencies": ["US-001"]},
            ]
        }
        result = validate(prd)
        assert result["valid"] is False
        assert len(result["cycles"]) == 1

    def test_prd_with_orphans(self) -> None:
        """prd.json with orphan dependencies."""
        prd = {
            "userStories": [
                {"id": "US-001", "dependencies": ["US-999"]},
            ]
        }
        result = validate(prd)
        assert result["valid"] is False
        assert result["orphans"] == ["US-999"]

    def test_prd_with_cycle_and_orphans(self) -> None:
        """prd.json with both cycles and orphans."""
        prd = {
            "userStories": [
                {"id": "US-001", "dependencies": ["US-002", "US-999"]},
                {"id": "US-002", "dependencies": ["US-001"]},
            ]
        }
        result = validate(prd)
        assert result["valid"] is False
        assert len(result["cycles"]) > 0
        assert "US-999" in result["orphans"]

    def test_prd_namespace_conflict_not_strict(self) -> None:
        """Namespace conflict ignored when strict=False."""
        prd = {
            "userStories": [
                {"id": "PROJECT-A-US-001", "sub_project": "other"},
            ]
        }
        result = validate(prd, strict=False)
        assert result["valid"] is True

    def test_prd_namespace_conflict_strict(self) -> None:
        """Namespace conflict treated as error when strict=True."""
        prd = {
            "userStories": [
                {"id": "PROJECT-A-US-001", "sub_project": "other"},
            ]
        }
        result = validate(prd, strict=True)
        assert result["valid"] is False

    def test_empty_prd(self) -> None:
        """Empty prd.json."""
        prd: dict[str, list[Any]] = {"userStories": []}
        result = validate(prd)
        assert result["valid"] is True

    def test_prd_missing_userstories(self) -> None:
        """prd.json missing userStories key."""
        prd: dict[str, list[Any]] = {}
        result = validate(prd)
        assert result["valid"] is True

    def test_federated_prd_multi_project(self) -> None:
        """Federated prd.json with stories from multiple projects."""
        prd = {
            "userStories": [
                {
                    "id": "PROJECT-A-US-001",
                    "dependencies": ["PROJECT-B-US-001"],
                },
                {
                    "id": "PROJECT-B-US-001",
                    "dependencies": [],
                },
            ]
        }
        result = validate(prd)
        assert result["valid"] is True
        assert "PROJECT-A" in result["namespaces"]
        assert "PROJECT-B" in result["namespaces"]

    def test_complex_valid_graph(self) -> None:
        """Complex dependency graph with no issues."""
        prd = {
            "userStories": [
                {"id": "US-001", "dependencies": ["US-002", "US-003"]},
                {"id": "US-002", "dependencies": ["US-004"]},
                {"id": "US-003", "dependencies": ["US-004"]},
                {"id": "US-004", "dependencies": []},
            ]
        }
        result = validate(prd)
        assert result["valid"] is True
        assert result["cycles"] == []
        assert result["orphans"] == []
