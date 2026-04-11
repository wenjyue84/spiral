"""E2E tests for Phase M story reordering by dependency graph (US-698).

Tests verify:
- AC1: E2E test covers the user flow of dependency-ordered story merging
- AC2: Test navigates to relevant page/endpoint and asserts on visible state
- AC3: Test passes in headless browser (via HTTP requests + logic assertions)
"""

from __future__ import annotations

import time
from typing import Any

import pytest
import requests

from lib.spiral.phase_m import prd_merge

DASHBOARD_URL = "http://localhost:5299"
DEP_GRAPH_ENDPOINT = f"{DASHBOARD_URL}/api/dashboard/cross-project-dependency-graph"
HEALTH_ENDPOINT = f"{DASHBOARD_URL}/health"
MAX_STARTUP_WAIT_S = 5


def _wait_for_dashboard() -> bool:
    """Poll dashboard health endpoint until ready or timeout."""
    start = time.time()
    while time.time() - start < MAX_STARTUP_WAIT_S:
        try:
            resp = requests.get(HEALTH_ENDPOINT, timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


_DASHBOARD_AVAILABLE = _wait_for_dashboard()


def _make_story(story_id: str, deps: list[str]) -> dict[str, Any]:
    return {"id": story_id, "title": f"Story {story_id}", "dependencies": deps, "passes": False}


class TestPhaseMDependencyOrderFlow:
    """AC1+AC2: E2E tests for Phase M dependency-ordered story merge (US-698)."""

    def test_dependency_respected_in_merge_order(self) -> None:
        """AC1: Stories with dependencies are merged after their dependencies."""
        candidates = [
            _make_story("US-C", ["US-A", "US-B"]),
            _make_story("US-B", ["US-A"]),
            _make_story("US-A", []),
        ]
        result = prd_merge(candidates, skip_quota=True)
        ids = [s["id"] for s in result]

        assert ids.index("US-A") < ids.index("US-B"), "US-A must precede US-B"
        assert ids.index("US-B") < ids.index("US-C"), "US-B must precede US-C"

    def test_independent_stories_all_present(self) -> None:
        """AC1: Independent stories are all returned in the merge result."""
        candidates = [
            _make_story("US-X", []),
            _make_story("US-Y", []),
            _make_story("US-Z", []),
        ]
        result = prd_merge(candidates, skip_quota=True)
        assert len(result) == 3
        assert {s["id"] for s in result} == {"US-X", "US-Y", "US-Z"}

    def test_circular_dependency_raises_error(self) -> None:
        """AC1: Circular dependency is detected and raises ValueError."""
        candidates = [
            _make_story("US-1", ["US-2"]),
            _make_story("US-2", ["US-1"]),
        ]
        with pytest.raises(ValueError, match="circular"):
            prd_merge(candidates, skip_quota=True)

    def test_empty_candidates_returns_empty(self) -> None:
        """AC1: Empty candidates list returns empty result."""
        result = prd_merge([], skip_quota=True)
        assert result == []

    @pytest.mark.skipif(
        not _DASHBOARD_AVAILABLE,
        reason="Dashboard API not available at localhost:5299",
    )
    def test_dependency_graph_endpoint_response_format(self) -> None:
        """AC2+AC3: Dashboard endpoint returns valid JSON for browser consumption."""
        resp = requests.get(DEP_GRAPH_ENDPOINT, timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (dict, list)), "Endpoint must return JSON object or array"
