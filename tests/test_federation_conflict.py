"""Integration tests for federation file conflict detection (US-1044)."""

import pytest

from lib.federation.conflict_detector import detect_file_conflicts


@pytest.fixture
def federated_prd() -> dict[str, object]:
    """2 sub-projects touching 3 common files."""
    return {
        "productName": "Test",
        "branchName": "main",
        "subProjects": [{"namespace": "alpha"}, {"namespace": "beta"}],
        "userStories": [
            {
                "id": "ALPHA-001",
                "title": "Alpha story 1",
                "sub_project": "alpha",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": [],
                "filesTouch": ["lib/core.py", "lib/utils.py", "config.yml"],
            },
            {
                "id": "ALPHA-002",
                "title": "Alpha story 2",
                "sub_project": "alpha",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": [],
                "filesTouch": ["lib/core.py"],
            },
            {
                "id": "BETA-001",
                "title": "Beta story 1",
                "sub_project": "beta",
                "passes": False,
                "acceptanceCriteria": ["AC1"],
                "dependencies": [],
                "filesTouch": [
                    "lib/core.py",
                    "lib/utils.py",
                    "config.yml",
                    "beta_only.py",
                ],
            },
        ],
    }


class TestDetectFileConflicts:
    """Integration tests for detect_file_conflicts()."""

    def test_detects_all_common_files(self, federated_prd: dict[str, object]) -> None:
        """All 3 common files are reported as conflicts."""
        conflicts = detect_file_conflicts(federated_prd)
        paths = {c.file_path for c in conflicts}
        assert "lib/core.py" in paths
        assert "lib/utils.py" in paths
        assert "config.yml" in paths

    def test_no_false_positives(self, federated_prd: dict[str, object]) -> None:
        """Files touched by only one sub-project are not reported."""
        conflicts = detect_file_conflicts(federated_prd)
        paths = {c.file_path for c in conflicts}
        assert "beta_only.py" not in paths

    def test_conflict_has_both_sub_projects(self, federated_prd: dict[str, object]) -> None:
        """Each conflict includes both sub-project names."""
        conflicts = detect_file_conflicts(federated_prd)
        core = next(c for c in conflicts if c.file_path == "lib/core.py")
        assert "alpha" in core.sub_projects
        assert "beta" in core.sub_projects

    def test_story_ids_present(self, federated_prd: dict[str, object]) -> None:
        """Conflict lists story IDs from all involved sub-projects."""
        conflicts = detect_file_conflicts(federated_prd)
        core = next(c for c in conflicts if c.file_path == "lib/core.py")
        assert "ALPHA-001" in core.story_ids
        assert "BETA-001" in core.story_ids

    def test_resolution_hints_actionable(self, federated_prd: dict[str, object]) -> None:
        """Every conflict has a non-trivial resolution hint."""
        conflicts = detect_file_conflicts(federated_prd)
        for c in conflicts:
            assert c.suggested_resolution
            assert len(c.suggested_resolution) > 20

    def test_config_file_resolution_hint(self, federated_prd: dict[str, object]) -> None:
        """Config/YAML file gets a 'coordinate edits' resolution hint."""
        conflicts = detect_file_conflicts(federated_prd)
        cfg = next(c for c in conflicts if c.file_path == "config.yml")
        assert "config" in cfg.suggested_resolution.lower() or "merge" in cfg.suggested_resolution.lower()

    def test_to_dict_serialization(self, federated_prd: dict[str, object]) -> None:
        """to_dict() returns JSON-serializable structure with required keys."""
        conflicts = detect_file_conflicts(federated_prd)
        assert conflicts
        d = conflicts[0].to_dict()
        assert "file_path" in d
        assert "sub_projects" in d
        assert "story_ids" in d
        assert "suggested_resolution" in d
        assert isinstance(d["sub_projects"], list)

    def test_no_conflicts_single_sub_project(self) -> None:
        """No conflicts when all stories belong to the same sub-project."""
        prd: dict[str, object] = {
            "userStories": [
                {
                    "id": "US-1",
                    "sub_project": "alpha",
                    "filesTouch": ["a.py", "b.py"],
                    "passes": False,
                    "acceptanceCriteria": [],
                    "dependencies": [],
                },
                {
                    "id": "US-2",
                    "sub_project": "alpha",
                    "filesTouch": ["a.py"],
                    "passes": False,
                    "acceptanceCriteria": [],
                    "dependencies": [],
                },
            ]
        }
        assert detect_file_conflicts(prd) == []

    def test_empty_prd(self) -> None:
        """Empty PRD returns no conflicts."""
        assert detect_file_conflicts({}) == []
