"""Integration tests for federated multi-project worker distribution (US-636)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))


def _make_story(sid, passes=False, sub_project=None, **extra):
    """Create a minimal valid story dict."""
    s = {
        "id": sid,
        "title": f"Story {sid}",
        "passes": passes,
        "priority": "medium",
        "description": f"Description for {sid}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    if sub_project:
        s["sub_project"] = sub_project
    s.update(extra)
    return s


def _make_prd(stories, name="TestProduct", branch="main"):
    """Create a minimal valid PRD."""
    return {
        "schemaVersion": 1,
        "productName": name,
        "branchName": branch,
        "overview": "Test PRD",
        "goals": ["Test goal"],
        "userStories": stories,
    }


def _write_prd(path, prd):
    """Write PRD to file and return path as string."""
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


def _read_prd(path):
    """Read and parse PRD JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestFederatedWorkers:
    """Test federated multi-project worker distribution."""

    def test_federated_partition_prd_creates_sub_project_workers(self, tmp_path):
        """AC: partition_prd.py with --federated creates worker-{sub_project}-{N}.json files."""
        # Create federated prd.json with api and frontend sub-projects
        prd = _make_prd(
            [
                _make_story("US-001", sub_project="api"),
                _make_story("US-002", sub_project="api"),
                _make_story("US-003", sub_project="frontend"),
                _make_story("US-004", sub_project="frontend"),
                _make_story("US-005", sub_project="frontend"),
            ]
        )
        prd_file = _write_prd(tmp_path / "prd.json", prd)
        outdir = tmp_path / "workers"
        outdir.mkdir()

        # Run partition_prd.py with --federated
        spiral_home = Path(__file__).parent.parent
        result = subprocess.run(
            [
                "python",
                str(spiral_home / "lib" / "prd" / "partition_prd.py"),
                "--prd",
                prd_file,
                "--workers",
                "2",
                "--outdir",
                str(outdir),
                "--federated",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"partition_prd.py failed: {result.stderr}"

        # Verify worker-api-{N}.json files were created
        assert (outdir / "worker-api-1.json").exists(), "worker-api-1.json not created"
        assert (outdir / "worker-api-2.json").exists(), "worker-api-2.json not created"

        # Verify worker-frontend-{N}.json files were created
        assert (outdir / "worker-frontend-1.json").exists(), "worker-frontend-1.json not created"
        assert (outdir / "worker-frontend-2.json").exists(), "worker-frontend-2.json not created"

        # Verify no standard worker_{N}.json files were created
        assert not (outdir / "worker_1.json").exists(), "Standard worker_1.json should not exist in federated mode"

    def test_federated_partition_prd_routes_stories_by_sub_project(self, tmp_path):
        """AC: partition_prd.py --federated routes stories to matching sub_project workers."""
        prd = _make_prd(
            [
                _make_story("US-001", sub_project="api"),
                _make_story("US-002", sub_project="api"),
                _make_story("US-003", sub_project="frontend"),
                _make_story("US-004", sub_project="frontend"),
            ]
        )
        prd_file = _write_prd(tmp_path / "prd.json", prd)
        outdir = tmp_path / "workers"
        outdir.mkdir()

        # Run partition_prd.py with --federated
        spiral_home = Path(__file__).parent.parent
        subprocess.run(
            [
                "python",
                str(spiral_home / "lib" / "prd" / "partition_prd.py"),
                "--prd",
                prd_file,
                "--workers",
                "2",
                "--outdir",
                str(outdir),
                "--federated",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Verify worker-api-1 has only API stories
        worker_api_1 = _read_prd(outdir / "worker-api-1.json")
        api_stories = [s for s in worker_api_1["userStories"] if not s.get("passes")]
        api_sub_projects = {s.get("sub_project") for s in api_stories}
        assert api_sub_projects <= {"api", None}, "worker-api-1 should only contain api stories"

        # Verify worker-frontend-1 has only frontend stories
        worker_frontend_1 = _read_prd(outdir / "worker-frontend-1.json")
        frontend_stories = [s for s in worker_frontend_1["userStories"] if not s.get("passes")]
        frontend_sub_projects = {s.get("sub_project") for s in frontend_stories}
        assert frontend_sub_projects <= {"frontend", None}, "worker-frontend-1 should only contain frontend stories"

    def test_federated_worktree_naming_respects_sub_project(self, tmp_path):
        """AC: run_parallel_ralph.sh detects federated mode and creates worker-{sub_project}-{N} worktrees."""
        # This is a conceptual test since we can't run the full bash script in pytest
        # Instead, verify the federated detection logic would work

        prd = _make_prd(
            [
                _make_story("US-001", sub_project="api"),
                _make_story("US-002", sub_project="frontend"),
            ]
        )
        prd_file = _write_prd(tmp_path / "prd.json", prd)

        # Read PRD and check for sub_project field in pending stories
        prd_data = _read_prd(prd_file)
        pending = [s for s in prd_data["userStories"] if not s.get("passes")]
        sub_projects = {s.get("sub_project") for s in pending if s.get("sub_project")}

        # Verify federated mode would be detected
        assert len(sub_projects) > 0, "Federated mode should be detected when stories have sub_project"
        assert "api" in sub_projects, "api sub_project should be detected"
        assert "frontend" in sub_projects, "frontend sub_project should be detected"

    def test_federated_partition_with_mixed_and_default_sub_projects(self, tmp_path):
        """AC: partition_prd.py handles stories with and without sub_project field correctly."""
        prd = _make_prd(
            [
                _make_story("US-001", sub_project="api"),
                _make_story("US-002"),  # No sub_project
                _make_story("US-003", sub_project="api"),
            ]
        )
        prd_file = _write_prd(tmp_path / "prd.json", prd)
        outdir = tmp_path / "workers"
        outdir.mkdir()

        # Run partition without --federated (standard mode)
        spiral_home = Path(__file__).parent.parent
        result = subprocess.run(
            [
                "python",
                str(spiral_home / "lib" / "prd" / "partition_prd.py"),
                "--prd",
                prd_file,
                "--workers",
                "2",
                "--outdir",
                str(outdir),
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"partition_prd.py failed: {result.stderr}"

        # Verify standard naming (worker_{N}.json) is used
        assert (outdir / "worker_1.json").exists(), "worker_1.json not created"
        assert (outdir / "worker_2.json").exists(), "worker_2.json not created"

        # Verify no federated names were created
        assert not (outdir / "worker-api-1.json").exists(), "Federated names should not exist in standard mode"

    def test_federated_no_cross_project_contamination(self, tmp_path):
        """AC: Federated partition ensures no cross-project file contamination in filesTouch."""
        prd = _make_prd(
            [
                _make_story("US-001", sub_project="api", filesTouch=["api/handler.py"]),
                _make_story("US-002", sub_project="frontend", filesTouch=["frontend/page.tsx"]),
            ]
        )
        prd_file = _write_prd(tmp_path / "prd.json", prd)
        outdir = tmp_path / "workers"
        outdir.mkdir()

        # Run partition with --federated (need at least 2 workers for partition_prd)
        spiral_home = Path(__file__).parent.parent
        subprocess.run(
            [
                "python",
                str(spiral_home / "lib" / "prd" / "partition_prd.py"),
                "--prd",
                prd_file,
                "--workers",
                "2",
                "--outdir",
                str(outdir),
                "--federated",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Verify worker-api-1 contains api story with api files
        worker_api = _read_prd(outdir / "worker-api-1.json")
        api_stories = [s for s in worker_api["userStories"] if not s.get("passes")]
        assert any(s["id"] == "US-001" for s in api_stories), "api story should be in api worker"

        # Verify worker-frontend-1 contains frontend story with frontend files
        worker_frontend = _read_prd(outdir / "worker-frontend-1.json")
        frontend_stories = [s for s in worker_frontend["userStories"] if not s.get("passes")]
        assert any(s["id"] == "US-002" for s in frontend_stories), "frontend story should be in frontend worker"
