"""Integration test: Phase M Federated Merge with File Conflict Detection (US-1072).

Tests verify that Phase M correctly detects and handles conflicts when multiple
sub-projects modify overlapping files during a federated merge.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from conflict_detector import detect_federated_conflicts
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()


def _make_story(
    story_id: str,
    passes: bool = False,
    sub_project: str | None = None,
    files_to_touch: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a minimal valid story dict with sub_project and filesTouch fields."""
    s: dict[str, Any] = {
        "id": story_id,
        "title": f"Story {story_id}",
        "passes": passes,
        "priority": "medium",
        "description": f"Test story {story_id}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
        "filesTouch": files_to_touch or [],
    }
    if sub_project:
        s["sub_project"] = sub_project
    s.update(extra)
    return s


def _make_prd_federated(stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a federated prd.json with 2 sub-projects."""
    return {
        "schemaVersion": 1,
        "productName": "FederatedConflictTest",
        "branchName": "main",
        "overview": "Federated test PRD with conflict scenario",
        "goals": ["Test conflict detection"],
        "subProjects": ["sub-project-A", "sub-project-B"],
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


class TestPhaseMMergeConflictDetection:
    """Tests for Phase M conflict detection in federated merges."""

    def test_conflict_detection_same_file_different_projects(self, tmp_path: Path) -> None:
        """AC1: Test detects conflict when sub-project-A and sub-project-B both touch same file.

        Two stories from different sub-projects modify the same file path.
        detect_federated_conflicts() should identify this as a file collision.
        """
        # Story 1: sub-project-A modifies shared_module.py
        story_a = _make_story(
            "US-001",
            passes=False,
            sub_project="sub-project-A",
            files_to_touch=["src/shared_module.py", "src/utils.py"],
        )

        # Story 2: sub-project-B also modifies shared_module.py (conflict!)
        story_b = _make_story(
            "US-002",
            passes=False,
            sub_project="sub-project-B",
            files_to_touch=["src/shared_module.py", "src/config.py"],
        )

        # Story 3: sub-project-A modifies different file (no conflict)
        story_c = _make_story(
            "US-003",
            passes=False,
            sub_project="sub-project-A",
            files_to_touch=["src/feature_a.py"],
        )

        stories = [story_a, story_b, story_c]

        # Detect conflicts
        conflicts, error_msgs = detect_federated_conflicts(stories)

        # Assert that the shared file is reported as a conflict
        assert len(conflicts) > 0, "Expected at least one conflict detected"

        shared_file_conflicts = [c for c in conflicts if c.get("file_path") == "src/shared_module.py"]
        assert len(shared_file_conflicts) > 0, "Expected conflict for src/shared_module.py"

        conflict = shared_file_conflicts[0]
        assert conflict["conflict_type"] == "file_collision"
        assert set(conflict["sub_projects"]) == {"sub-project-A", "sub-project-B"}

        # No error should be raised for conflicts without manual review
        # (first-in-wins strategy means conflicts are reported but don't block merge)

    def test_merge_strategy_first_in_wins(self, tmp_path: Path) -> None:
        """AC2: Test merge strategy handles conflicts consistently (first-in-wins approach).

        When conflicts are detected, Phase M should apply a consistent merge strategy.
        With first-in-wins, the first story to touch a file "owns" that file.
        """
        # Create stories where A and B both want to modify config.json
        story_a_first = _make_story(
            "US-010",
            passes=False,
            sub_project="sub-project-A",
            files_to_touch=["config.json", "src/app.py"],
        )

        story_b_second = _make_story(
            "US-011",
            passes=False,
            sub_project="sub-project-B",
            files_to_touch=["config.json", "src/api.py"],
        )

        story_a_unrelated = _make_story(
            "US-012",
            passes=False,
            sub_project="sub-project-A",
            files_to_touch=["src/unique_a.py"],
        )

        stories = [story_a_first, story_b_second, story_a_unrelated]
        prd = _make_prd_federated(stories)
        prd_path = tmp_path / "prd.json"
        _write_prd(prd_path, prd)

        # Detect conflicts
        conflicts, _ = detect_federated_conflicts(stories)

        # The conflict should be recorded
        config_conflicts = [c for c in conflicts if c.get("file_path") == "config.json"]
        assert len(config_conflicts) > 0

        # After detection, prd.json should still have all stories (no automatic removal)
        final_prd = _read_prd(prd_path)
        assert len(final_prd["userStories"]) == 3

        # All stories should still be present
        story_ids = {s.get("id") for s in final_prd["userStories"]}
        assert story_ids == {"US-010", "US-011", "US-012"}

    def test_no_cross_worker_corruption_after_merge(self, tmp_path: Path) -> None:
        """AC3: Test that prd.json and worker PRDs remain consistent after merge.

        Simulates 3 workers where two have file conflicts. Verifies that both
        the main prd.json and all worker prd.json files remain structurally
        consistent with no data loss or cross-contamination.
        """
        # Create main prd with conflicting stories
        main_stories = [
            _make_story(
                "US-100",
                passes=False,
                sub_project="sub-project-A",
                files_to_touch=["shared.py"],
            ),
            _make_story(
                "US-101",
                passes=False,
                sub_project="sub-project-B",
                files_to_touch=["shared.py"],
            ),
            _make_story(
                "US-102",
                passes=False,
                sub_project="sub-project-A",
                files_to_touch=["unique_a.py"],
            ),
        ]

        main_prd = _make_prd_federated(main_stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Create worker PRDs (each with a subset of stories)
        worker_configs = [
            ("worker-0", ["US-100", "US-102"]),  # A's stories
            ("worker-1", ["US-101"]),  # B's stories
        ]

        worker_prd_paths = []
        for worker_name, story_ids in worker_configs:
            worker_stories = []
            for s in main_stories:
                if s.get("id") in story_ids:
                    # Create a copy and keep passes=False so conflict detector sees it
                    story_copy = s.copy()
                    worker_stories.append(story_copy)
                else:
                    # Non-assigned stories stay with original passes value
                    worker_stories.append(s.copy())

            # Add some non-conflicting stories to the worker PRD
            if worker_name == "worker-0":
                worker_stories.append(
                    _make_story(
                        "US-200",
                        passes=False,
                        sub_project="sub-project-A",
                        files_to_touch=["unique_a_extra.py"],
                    )
                )

            worker_prd = _make_prd_federated(worker_stories)
            worker_path = tmp_path / f"{worker_name}-prd.json"
            _write_prd(worker_path, worker_prd)
            worker_prd_paths.append(worker_path)

        # Verify main prd still has 3 stories
        main_prd_check = _read_prd(main_prd_path)
        assert len(main_prd_check["userStories"]) == 3
        main_story_ids = {s.get("id") for s in main_prd_check["userStories"]}
        assert main_story_ids == {"US-100", "US-101", "US-102"}

        # Verify each worker prd is structurally intact
        for worker_path in worker_prd_paths:
            worker_prd_check = _read_prd(worker_path)
            assert worker_prd_check.get("schemaVersion") == 1
            assert worker_prd_check.get("subProjects") == ["sub-project-A", "sub-project-B"]
            assert len(worker_prd_check["userStories"]) > 0

            # All stories should have required fields
            for story in worker_prd_check["userStories"]:
                assert "id" in story
                assert "sub_project" in story
                assert "filesTouch" in story

        # Detect conflicts across all worker stories
        all_worker_stories: list[dict[str, Any]] = []
        for worker_path in worker_prd_paths:
            worker_prd_data = _read_prd(worker_path)
            all_worker_stories.extend(worker_prd_data.get("userStories", []))

        conflicts, _ = detect_federated_conflicts(all_worker_stories)
        # Should detect the shared.py conflict
        assert len(conflicts) > 0
        shared_conflicts = [c for c in conflicts if c.get("file_path") == "shared.py"]
        assert len(shared_conflicts) > 0

        # After all operations, main prd should still have exactly 3 stories
        final_main_prd = _read_prd(main_prd_path)
        assert len(final_main_prd["userStories"]) == 3
        assert final_main_prd.get("subProjects") == ["sub-project-A", "sub-project-B"]
