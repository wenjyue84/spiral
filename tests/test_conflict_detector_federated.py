#!/usr/bin/env python3
"""Tests for federated file conflict detection (US-691)."""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from conflict_detector import detect_federated_conflicts, write_conflict_report


class TestExtractFederatedConflicts:
    """Test federated conflict detection with sub_project_id tracking."""

    def test_no_conflicts_different_files(self) -> None:
        """Two stories from different sub-projects modifying different files: no conflict."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/auth.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-b",
                "filesTouch": ["src/api.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)
        assert conflicts == []
        assert errors == []

    def test_collision_same_file_different_projects(self) -> None:
        """Same file modified by stories from different sub-projects: collision."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-b",
                "filesTouch": ["src/core.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict["file_path"] == "src/core.py"
        assert set(conflict["sub_projects"]) == {"project-a", "project-b"}
        assert conflict["conflict_type"] == "file_collision"
        assert len(errors) > 0

    def test_no_collision_same_file_same_project(self) -> None:
        """Same file modified by stories from same sub-project: no collision."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)
        assert conflicts == []
        assert errors == []

    def test_collision_multiple_files(self) -> None:
        """Multiple files modified by different projects: multiple collisions."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py", "src/utils.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-b",
                "filesTouch": ["src/core.py", "src/api.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        assert len(conflicts) == 1  # One conflict (shared file core.py)
        conflict = conflicts[0]
        assert conflict["file_path"] == "src/core.py"
        assert set(conflict["sub_projects"]) == {"project-a", "project-b"}

    def test_collision_three_projects(self) -> None:
        """Same file modified by three different sub-projects: one collision with 3 projects."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/config.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-b",
                "filesTouch": ["src/config.py"],
            },
            {
                "id": "US-003",
                "passes": False,
                "_source": "project-c",
                "filesTouch": ["src/config.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict["file_path"] == "src/config.py"
        assert set(conflict["sub_projects"]) == {"project-a", "project-b", "project-c"}

    def test_filters_completed_stories(self) -> None:
        """Completed stories (passes=True) should be filtered out."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py"],
            },
            {
                "id": "US-002",
                "passes": True,  # Completed
                "_source": "project-b",
                "filesTouch": ["src/core.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)
        assert conflicts == []
        assert errors == []

    def test_filters_decomposed_stories(self) -> None:
        """Decomposed stories (_decomposed=True) should be filtered out."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["src/core.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_decomposed": True,
                "_source": "project-b",
                "filesTouch": ["src/core.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)
        assert conflicts == []
        assert errors == []

    def test_error_message_format(self) -> None:
        """Error messages should include file path, story ID, and sub_project."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "project-a",
                "filesTouch": ["lib/shared.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "project-b",
                "filesTouch": ["lib/shared.py"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        assert len(errors) > 0
        # Check that error message contains file path
        assert any("lib/shared.py" in e for e in errors)
        # Check that error mentions sub-projects
        assert any("project-a" in e or "project-b" in e for e in errors)

    def test_empty_stories(self) -> None:
        """Empty story list should produce no conflicts."""
        conflicts, errors = detect_federated_conflicts([])
        assert conflicts == []
        assert errors == []


class TestWriteConflictReport:
    """Test conflict report file generation."""

    def test_write_conflict_report_creates_file(self) -> None:
        """write_conflict_report should create .spiral/merge_conflicts.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, ".spiral", "merge_conflicts.json")
            conflicts = [
                {
                    "file_path": "src/core.py",
                    "sub_projects": ["project-a", "project-b"],
                    "conflict_type": "file_collision",
                }
            ]

            write_conflict_report(conflicts, report_path)

            assert os.path.isfile(report_path)
            with open(report_path, encoding="utf-8") as f:
                data = json.load(f)
            assert data == conflicts

    def test_write_conflict_report_empty(self) -> None:
        """Empty conflicts should write empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, ".spiral", "merge_conflicts.json")

            write_conflict_report([], report_path)

            assert os.path.isfile(report_path)
            with open(report_path, encoding="utf-8") as f:
                data = json.load(f)
            assert data == []

    def test_write_conflict_report_creates_directory(self) -> None:
        """write_conflict_report should create parent directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "deep", "nested", "merge_conflicts.json")
            conflicts = [
                {
                    "file_path": "src/api.py",
                    "sub_projects": ["core", "auth"],
                    "conflict_type": "file_collision",
                }
            ]

            write_conflict_report(conflicts, report_path)

            assert os.path.isfile(report_path)


class TestIntegrationPhaseM:
    """Integration tests simulating Phase M merge blocking."""

    def test_phase_m_would_block_on_conflict(self) -> None:
        """Simulate Phase M: detect_federated_conflicts returns exit code 1 on collision."""
        stories = [
            {
                "id": "US-501",
                "passes": False,
                "_source": "core-team",
                "filesTouch": ["lib/auth.ts"],
            },
            {
                "id": "US-502",
                "passes": False,
                "_source": "web-team",
                "filesTouch": ["lib/auth.ts"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        # Phase M merge should block (exit code 1) if conflicts found
        assert len(conflicts) == 1
        assert len(errors) > 0

    def test_phase_m_allows_merge_no_conflict(self) -> None:
        """Simulate Phase M: detect_federated_conflicts allows merge (exit code 0) when no conflict."""
        stories = [
            {
                "id": "US-501",
                "passes": False,
                "_source": "core-team",
                "filesTouch": ["lib/auth.ts"],
            },
            {
                "id": "US-502",
                "passes": False,
                "_source": "web-team",
                "filesTouch": ["src/api.ts"],
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        # Phase M merge should proceed (exit code 0) if no conflicts found
        assert len(conflicts) == 0
        assert len(errors) == 0

    def test_acceptance_criteria_file_path_extraction(self) -> None:
        """AC1: Extract modified file paths from stories and track sub_project_id."""
        stories = [
            {
                "id": "US-691-TEST-001",
                "passes": False,
                "_source": "federated-core",
                "filesTouch": ["lib/merge.py", "lib/federate.py"],
                "technicalNotes": ["File to edit: lib/merge.py"],
            },
            {
                "id": "US-691-TEST-002",
                "passes": False,
                "_source": "federated-web",
                "filesTouch": ["lib/merge.py"],  # Same file!
            },
        ]
        conflicts, errors = detect_federated_conflicts(stories)

        # Should detect collision on lib/merge.py across different sub_projects
        assert len(conflicts) == 1
        assert conflicts[0]["file_path"] == "lib/merge.py"
        assert "federated-core" in conflicts[0]["sub_projects"]
        assert "federated-web" in conflicts[0]["sub_projects"]

    def test_acceptance_criteria_collision_detection(self) -> None:
        """AC2: Detect collisions and write merge_conflicts.json with proper structure."""
        stories = [
            {
                "id": "US-691-TEST-A",
                "passes": False,
                "_source": "proj-a",
                "filesTouch": ["src/auth.py", "src/config.py"],
            },
            {
                "id": "US-691-TEST-B",
                "passes": False,
                "_source": "proj-b",
                "filesTouch": ["src/config.py"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, ".spiral", "merge_conflicts.json")
            conflicts, _ = detect_federated_conflicts(stories)
            write_conflict_report(conflicts, report_path)

            # Verify report structure
            with open(report_path, encoding="utf-8") as f:
                report = json.load(f)

            assert isinstance(report, list)
            assert len(report) == 1
            assert report[0]["file_path"] == "src/config.py"
            assert report[0]["conflict_type"] == "file_collision"
            assert set(report[0]["sub_projects"]) == {"proj-a", "proj-b"}

    def test_acceptance_criteria_error_message_format(self) -> None:
        """AC3: Error messages for merge blocking with proper format."""
        stories = [
            {
                "id": "US-001",
                "passes": False,
                "_source": "sub-proj-1",
                "filesTouch": ["lib/shared.py"],
            },
            {
                "id": "US-002",
                "passes": False,
                "_source": "sub-proj-2",
                "filesTouch": ["lib/shared.py"],
            },
        ]
        _, errors = detect_federated_conflicts(stories)

        # Verify error message format
        assert len(errors) > 0
        error = errors[0]
        assert "lib/shared.py" in error
        assert "manual resolution required" in error
