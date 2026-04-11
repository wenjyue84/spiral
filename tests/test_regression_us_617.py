"""Regression test for US-617: Phase M Federated Order Merge Optimization.

Guards against breakage of topological sort for cross-project story dependencies.
Ensures stories with dependencies are ordered correctly during Phase M merge.

Story: US-617 — Phase M: Optimize Merge Order for Federated Stories with Cross-Project Dependencies
Feature: order_federated_stories_by_dependency() topological sorting with cycle detection
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib" / "impl"))

from phase_m_federated_order import order_federated_stories_by_dependency  # noqa: E402


def _make_story(
    sid: str,
    title: str = "",
    description: str = "",
    dependencies: list[str] | None = None,
) -> dict[str, str | list[str]]:
    """Helper to create a test story dict."""
    return {
        "id": sid,
        "title": title or f"Story {sid}",
        "description": description,
        "dependencies": dependencies or [],
    }


@pytest.mark.us_617
class TestUS617RegressionFederatedOrder:
    """Regression tests for US-617: topological sort for federated story merge order."""

    def test_us_617_topological_sort_dependency_order(self) -> None:
        """Core observable behavior: dependencies are merged before dependents.

        Story A depends on Story B; Story B must appear before Story A in merge order.
        This is the primary observable behavior that Phase M depends on.
        """
        stories = [
            _make_story("US-A1", description="This depends on US-B1."),
            _make_story("US-B1"),
        ]

        result = order_federated_stories_by_dependency(stories)
        ids = [s["id"] for s in result]

        # Core observable: B (dependency) before A (dependent)
        assert ids.index("US-B1") < ids.index("US-A1"), (
            f"Dependency order failed: US-B1 should appear before US-A1. Got: {ids}"
        )

    def test_us_617_cycle_detection_raises_error(self) -> None:
        """Observable behavior: circular dependencies raise ValueError.

        If Story A→B and Story B→A, this is unresolvable.
        The function must detect and raise with 'circular dependency' message.
        """
        stories = [
            _make_story("US-A1", description="Depends on US-B1."),
            _make_story("US-B1", description="Depends on US-A1."),
        ]

        # Must raise ValueError for circular dependency
        with pytest.raises(ValueError, match="circular dependency"):
            order_federated_stories_by_dependency(stories)

    def test_us_617_description_based_dependencies(self) -> None:
        """Observable behavior: cross-project dependencies in description are recognized.

        Phase M optimization scans descriptions for "depends on", "requires", "after" keywords
        and infers ordering from text references. This test verifies that mechanism works.
        """
        stories = [
            _make_story(
                "US-BACKEND-1",
                description="Implements database schema. Must complete before API work.",
            ),
            _make_story(
                "US-API-1",
                description="Builds REST endpoints. Requires US-BACKEND-1 to be done first.",
            ),
        ]

        result = order_federated_stories_by_dependency(stories)
        ids = [s["id"] for s in result]

        # US-BACKEND-1 (dependency) must appear before US-API-1 (dependent)
        # This demonstrates description-based dependency scanning works
        assert ids.index("US-BACKEND-1") < ids.index("US-API-1"), (
            f"Description-based dependencies failed: US-BACKEND-1 should appear before US-API-1. Got: {ids}"
        )

    def test_us_617_chain_ordering_three_stories(self) -> None:
        """Observable behavior: multi-level dependency chains are ordered correctly.

        Story A→B→C means C executes first, then B, then A.
        This verifies transitive dependency ordering works.
        """
        stories = [
            _make_story("US-A1", description="Requires US-B1."),
            _make_story("US-B1", description="Requires US-C1."),
            _make_story("US-C1"),
        ]

        result = order_federated_stories_by_dependency(stories)
        ids = [s["id"] for s in result]

        # Verify chain order: C before B before A
        assert ids.index("US-C1") < ids.index("US-B1"), (
            f"Chain ordering failed at first link: {ids}"
        )
        assert ids.index("US-B1") < ids.index("US-A1"), (
            f"Chain ordering failed at second link: {ids}"
        )

    def test_us_617_merge_prevents_unmet_dependencies(self) -> None:
        """Observable behavior: returned order ensures Phase M can safely merge in sequence.

        If Phase M merges stories in the returned order, no story will be implemented
        before its dependencies. This is the integration point with Phase I.
        """
        # Complex dependency graph: A→C, B→C, D is independent
        stories = [
            _make_story("US-A1", description="depends on US-C1"),
            _make_story("US-B1", description="depends on US-C1"),
            _make_story("US-C1"),
            _make_story("US-D1"),
        ]

        result = order_federated_stories_by_dependency(stories)
        ids = [s["id"] for s in result]

        # Key observable: C (depended-on) comes before both A and B
        c_idx = ids.index("US-C1")
        a_idx = ids.index("US-A1")
        b_idx = ids.index("US-B1")

        assert c_idx < a_idx, f"C should come before A. Order: {ids}"
        assert c_idx < b_idx, f"C should come before B. Order: {ids}"
