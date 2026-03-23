"""Integration test: Federated Worker Isolation — Verify No Cross-Worker prd.json Corruption (US-1064).

Tests verify that 3 parallel workers on different sub-projects maintain prd.json isolation
and don't corrupt each other's story state. Each worker modifies only its assigned sub-project
stories after Phase M merge.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from merge_worker_results import main as merge_main
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()


def _make_story(story_id: str, passes: bool = False, sub_project: str | None = None, **extra: Any) -> dict[str, Any]:
    """Create a minimal valid story dict with sub_project field."""
    s: dict[str, Any] = {
        "id": story_id,
        "title": f"Story {story_id}",
        "passes": passes,
        "priority": "medium",
        "description": f"Test story {story_id}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    if sub_project:
        s["sub_project"] = sub_project
    s.update(extra)
    return s


def _make_prd_federated(stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a federated prd.json with 3 sub-projects."""
    return {
        "schemaVersion": 1,
        "productName": "FederatedProduct",
        "branchName": "main",
        "overview": "Federated test PRD with 3 sub-projects",
        "goals": ["Test federated isolation"],
        "subProjects": ["app-v1", "api-v2", "web-v3"],
        "userStories": stories,
    }


def _write_prd(path: Path, prd: dict[str, Any]) -> str:
    """Write prd.json atomically."""
    atomic_write_json(str(path), prd)
    return str(path)


def _read_prd(path: Path) -> dict[str, Any]:
    """Read prd.json."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, dict)
        return data


class TestFederatedWorkerIsolation:
    """Tests for federated worker isolation with 3 sub-projects."""

    def test_fixture_creates_3_sub_projects(self, tmp_path: Path) -> None:
        """AC1: Test fixture loads federated prd.json with 3 sub-projects (app-v1, api-v2, web-v3)."""
        stories = []
        for sp_idx, sub_project in enumerate(["app-v1", "api-v2", "web-v3"]):
            for i in range(5):
                story_id = f"US-{sp_idx * 5 + i + 1:03d}"
                stories.append(_make_story(story_id, passes=False, sub_project=sub_project))

        prd = _make_prd_federated(stories)
        prd_path = tmp_path / "prd.json"
        _write_prd(prd_path, prd)

        loaded_prd = _read_prd(prd_path)
        assert len(loaded_prd["userStories"]) == 15
        assert loaded_prd.get("subProjects") == ["app-v1", "api-v2", "web-v3"]

        sub_projects_found = {s.get("sub_project") for s in loaded_prd["userStories"]}
        assert sub_projects_found == {"app-v1", "api-v2", "web-v3"}

        for sub_project in ["app-v1", "api-v2", "web-v3"]:
            count = sum(1 for s in loaded_prd["userStories"] if s.get("sub_project") == sub_project)
            assert count == 5

    def test_worker_isolation_structure_integrity(self, tmp_path: Path) -> None:
        """AC2: Verify prd.json structure is stable across worker modifications."""
        stories = []
        for sp_idx, sub_project in enumerate(["app-v1", "api-v2", "web-v3"]):
            for i in range(5):
                story_id = f"US-{sp_idx * 5 + i + 1:03d}"
                stories.append(_make_story(story_id, passes=False, sub_project=sub_project))

        prd = _make_prd_federated(stories)
        prd_path = tmp_path / "prd.json"
        _write_prd(prd_path, prd)

        # Simulate worker modifications sequentially
        for target_sub_project in ["app-v1", "api-v2", "web-v3"]:
            prd = _read_prd(prd_path)
            for story in prd.get("userStories", []):
                if story.get("sub_project") == target_sub_project:
                    story["passes"] = True
            _write_prd(prd_path, prd)

        final_prd = _read_prd(prd_path)
        assert len(final_prd["userStories"]) == 15

        for story in final_prd["userStories"]:
            assert "id" in story
            assert "sub_project" in story
            assert story.get("passes") is True

        assert final_prd.get("subProjects") == ["app-v1", "api-v2", "web-v3"]

    def test_worker_sub_project_fidelity_after_merge(self, tmp_path: Path) -> None:
        """AC3: Verify worker modifications maintain sub-project boundaries."""

        stories = []
        for sp_idx, sub_project in enumerate(["app-v1", "api-v2", "web-v3"]):
            for i in range(5):
                story_id = f"US-{sp_idx * 5 + i + 1:03d}"
                stories.append(_make_story(story_id, passes=False, sub_project=sub_project))

        main_prd = _make_prd_federated(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        worker_prd_paths = []
        for worker_id, assigned_sub_project in enumerate([(0, "app-v1"), (1, "api-v2"), (2, "web-v3")]):
            _, sub_project = assigned_sub_project
            worker_stories = []
            for story in stories:
                if story.get("sub_project") == sub_project:
                    story_copy = story.copy()
                    story_copy["passes"] = True
                    worker_stories.append(story_copy)
                else:
                    worker_stories.append(story.copy())

            worker_prd = _make_prd_federated(worker_stories)
            worker_path = tmp_path / f"worker-{worker_id}-prd.json"
            _write_prd(worker_path, worker_prd)
            worker_prd_paths.append(str(worker_path))

        sys.argv = ["merge", "--main", str(main_prd_path)] + ["--workers"] + worker_prd_paths
        merge_ret = merge_main()
        assert merge_ret == 0

        merged_prd = _read_prd(main_prd_path)
        assert len(merged_prd["userStories"]) == 15

        for story in merged_prd["userStories"]:
            assert story.get("passes") is True

        app_v1_count = sum(1 for s in merged_prd["userStories"] if s.get("sub_project") == "app-v1")
        api_v2_count = sum(1 for s in merged_prd["userStories"] if s.get("sub_project") == "api-v2")
        web_v3_count = sum(1 for s in merged_prd["userStories"] if s.get("sub_project") == "web-v3")

        assert app_v1_count == 5
        assert api_v2_count == 5
        assert web_v3_count == 5
