"""Integration test for US-636: Federated worker distribution with 5+5 stories.

Tests the full federated partition pipeline with:
- 'api' sub-project: 5 pending stories
- 'frontend' sub-project: 5 pending stories

Acceptance Criteria:
- AC1: lib/run_parallel_ralph_federated.sh exists and validates sub_project field
- AC2: partition_prd.py --federated routes stories exclusively by sub_project;
       results.tsv has sub_project column populated for every story
- AC3: With 5+5 stories, 2 workers created per sub-project;
       each worker processes only its sub_project's stories;
       no cross-project contamination in filesTouch assignments
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

SPIRAL_HOME = Path(__file__).parent.parent


def _story(sid: str, sub_project: str, files: list[str] | None = None) -> dict[str, Any]:
    """Build a minimal valid story with sub_project."""
    s: dict[str, Any] = {
        "id": sid,
        "title": f"Story {sid}",
        "description": f"Implementation for {sid}",
        "passes": False,
        "priority": "medium",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
        "sub_project": sub_project,
    }
    if files:
        s["filesTouch"] = files
    return s


def _prd(stories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "productName": "TestFederated",
        "branchName": "main",
        "overview": "Federated integration test PRD",
        "goals": ["Verify federated worker distribution"],
        "userStories": stories,
    }


def _partition(prd_file: Path, outdir: Path, workers: int = 2) -> subprocess.CompletedProcess[str]:
    """Run partition_prd.py with --federated flag."""
    return subprocess.run(
        [
            sys.executable,
            str(SPIRAL_HOME / "lib" / "prd" / "partition_prd.py"),
            "--prd",
            str(prd_file),
            "--workers",
            str(workers),
            "--outdir",
            str(outdir),
            "--federated",
        ],
        capture_output=True,
        text=True,
    )


class TestFederatedScript:
    """AC1: lib/run_parallel_ralph_federated.sh exists and validates sub_project."""

    def test_federated_script_exists(self) -> None:
        """lib/run_parallel_ralph_federated.sh must exist."""
        script = SPIRAL_HOME / "lib" / "run_parallel_ralph_federated.sh"
        assert script.exists(), "lib/run_parallel_ralph_federated.sh not found"

    def test_federated_script_is_executable_or_bash_script(self) -> None:
        """lib/run_parallel_ralph_federated.sh must be a valid bash script."""
        script = SPIRAL_HOME / "lib" / "run_parallel_ralph_federated.sh"
        content = script.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/bash"), "Script must start with #!/bin/bash shebang"

    def test_federated_script_delegates_to_run_parallel_ralph(self) -> None:
        """lib/run_parallel_ralph_federated.sh must delegate to run_parallel_ralph.sh."""
        script = SPIRAL_HOME / "lib" / "run_parallel_ralph_federated.sh"
        content = script.read_text(encoding="utf-8")
        assert "run_parallel_ralph.sh" in content, "Federated script must delegate to run_parallel_ralph.sh"

    def test_federated_script_references_sub_project(self) -> None:
        """lib/run_parallel_ralph_federated.sh must reference sub_project field."""
        script = SPIRAL_HOME / "lib" / "run_parallel_ralph_federated.sh"
        content = script.read_text(encoding="utf-8")
        assert "sub_project" in content, "Script must reference sub_project field"

    def test_federated_script_references_worktree_naming(self) -> None:
        """lib/run_parallel_ralph_federated.sh must document worker-{sub_project}-N naming."""
        script = SPIRAL_HOME / "lib" / "run_parallel_ralph_federated.sh"
        content = script.read_text(encoding="utf-8")
        assert (
            "worker-{sub_project}" in content
            or "worker-{sub_project}-N" in content
            or "worker-{_sp}" in content
            or "{sub_project}-{N}" in content
        ), "Script must document worker-{sub_project}-N worktree naming"


class TestFederatedPartition5Stories:
    """AC2 & AC3: Federated partition with 5 api + 5 frontend stories."""

    @pytest.fixture()
    def federated_prd_5x5(self, tmp_path: Path) -> Path:
        """Create a federated PRD with 5 api + 5 frontend stories.

        Story IDs use the valid (US|UT)-NNN pattern as required by prd_schema.py.
        Sub-project is tracked via the sub_project field, not the ID prefix.
        """
        stories = [
            # 5 api sub-project stories (IDs US-001..US-005)
            _story("US-001", "api", files=["api/auth.py"]),
            _story("US-002", "api", files=["api/routes.py"]),
            _story("US-003", "api", files=["api/models.py"]),
            _story("US-004", "api", files=["api/middleware.py"]),
            _story("US-005", "api", files=["api/tests/test_auth.py"]),
            # 5 frontend sub-project stories (IDs US-006..US-010)
            _story("US-006", "frontend", files=["frontend/App.tsx"]),
            _story("US-007", "frontend", files=["frontend/components/Login.tsx"]),
            _story("US-008", "frontend", files=["frontend/pages/Dashboard.tsx"]),
            _story("US-009", "frontend", files=["frontend/hooks/useAuth.ts"]),
            _story("US-010", "frontend", files=["frontend/tests/Login.test.tsx"]),
        ]
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(_prd(stories), indent=2), encoding="utf-8")
        return prd_file

    def test_partition_succeeds_with_5x5_stories(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: partition_prd.py --federated succeeds with 5 api + 5 frontend stories."""
        outdir = tmp_path / "workers"
        outdir.mkdir()

        result = _partition(federated_prd_5x5, outdir, workers=2)
        assert result.returncode == 0, f"partition_prd.py failed:\n{result.stderr}"

    def test_two_api_workers_created(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: 2 worker files created for 'api' sub-project."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        assert (outdir / "worker-api-1.json").exists(), "worker-api-1.json not created"
        assert (outdir / "worker-api-2.json").exists(), "worker-api-2.json not created"

    def test_two_frontend_workers_created(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: 2 worker files created for 'frontend' sub-project."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        assert (outdir / "worker-frontend-1.json").exists(), "worker-frontend-1.json not created"
        assert (outdir / "worker-frontend-2.json").exists(), "worker-frontend-2.json not created"

    def test_no_standard_worker_files_in_federated_mode(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: No generic worker_N.json files created in federated mode."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        assert not (outdir / "worker_1.json").exists(), "Standard worker_1.json must not exist in federated mode"
        assert not (outdir / "worker_2.json").exists(), "Standard worker_2.json must not exist in federated mode"

    def test_api_workers_contain_only_api_stories(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC2: Each api worker processes only stories with sub_project='api'."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        for worker_num in (1, 2):
            worker_file = outdir / f"worker-api-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data: dict[str, Any] = json.loads(worker_file.read_text(encoding="utf-8"))
            pending = [s for s in prd_data["userStories"] if not s.get("passes")]
            invalid = [s["id"] for s in pending if s.get("sub_project") not in ("api", None)]
            assert not invalid, f"worker-api-{worker_num} contains non-api stories: {invalid}"

    def test_frontend_workers_contain_only_frontend_stories(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC2: Each frontend worker processes only stories with sub_project='frontend'."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        for worker_num in (1, 2):
            worker_file = outdir / f"worker-frontend-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data = json.loads(worker_file.read_text(encoding="utf-8"))
            pending = [s for s in prd_data["userStories"] if not s.get("passes")]
            invalid = [s["id"] for s in pending if s.get("sub_project") not in ("frontend", None)]
            assert not invalid, f"worker-frontend-{worker_num} contains non-frontend stories: {invalid}"

    def test_all_5_api_stories_distributed_across_api_workers(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: All 5 api stories appear across api workers (no stories dropped)."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        api_story_ids: set[str] = set()
        for worker_num in (1, 2):
            worker_file = outdir / f"worker-api-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data = json.loads(worker_file.read_text(encoding="utf-8"))
            for s in prd_data["userStories"]:
                if not s.get("passes") and s.get("sub_project") == "api":
                    api_story_ids.add(s["id"])

        expected = {"US-001", "US-002", "US-003", "US-004", "US-005"}
        assert api_story_ids == expected, f"Not all api stories distributed. Missing: {expected - api_story_ids}"

    def test_all_5_frontend_stories_distributed_across_frontend_workers(
        self, federated_prd_5x5: Path, tmp_path: Path
    ) -> None:
        """AC3: All 5 frontend stories appear across frontend workers (no stories dropped)."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        frontend_story_ids: set[str] = set()
        for worker_num in (1, 2):
            worker_file = outdir / f"worker-frontend-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data = json.loads(worker_file.read_text(encoding="utf-8"))
            for s in prd_data["userStories"]:
                if not s.get("passes") and s.get("sub_project") == "frontend":
                    frontend_story_ids.add(s["id"])

        expected = {"US-006", "US-007", "US-008", "US-009", "US-010"}
        assert frontend_story_ids == expected, (
            f"Not all frontend stories distributed. Missing: {expected - frontend_story_ids}"
        )

    def test_no_cross_project_file_contamination(self, federated_prd_5x5: Path, tmp_path: Path) -> None:
        """AC3: git diff shows no cross-project file changes — api files not in frontend workers."""
        outdir = tmp_path / "workers"
        outdir.mkdir()
        _partition(federated_prd_5x5, outdir, workers=2)

        # api workers must not contain frontend filesTouch patterns
        for worker_num in (1, 2):
            worker_file = outdir / f"worker-api-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data = json.loads(worker_file.read_text(encoding="utf-8"))
            for s in prd_data["userStories"]:
                if not s.get("passes") and s.get("sub_project") == "api":
                    files = s.get("filesTouch", [])
                    frontend_files = [f for f in files if "frontend/" in f]
                    assert not frontend_files, f"api worker story {s['id']} has frontend/ files: {frontend_files}"

        # frontend workers must not contain api filesTouch patterns
        for worker_num in (1, 2):
            worker_file = outdir / f"worker-frontend-{worker_num}.json"
            if not worker_file.exists():
                continue
            prd_data = json.loads(worker_file.read_text(encoding="utf-8"))
            for s in prd_data["userStories"]:
                if not s.get("passes") and s.get("sub_project") == "frontend":
                    files = s.get("filesTouch", [])
                    api_files = [f for f in files if f.startswith("api/")]
                    assert not api_files, f"frontend worker story {s['id']} has api/ files: {api_files}"


class TestResultsTsvSubProjectColumn:
    """AC2: results.tsv includes sub_project column for all federated stories."""

    def test_results_tsv_has_sub_project_field_in_schema(self) -> None:
        """ResultsRecord dataclass includes sub_project field."""
        from results_tsv import HEADER, ResultsRecord

        assert "sub_project" in HEADER, "sub_project must be in HEADER"
        record = ResultsRecord(
            timestamp="2026-01-01T00:00:00Z",
            spiral_iter="1",
            ralph_iter="1",
            story_id="US-api-001",
            story_title="API Story",
            status="passed",
            duration_sec="10",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run-1",
            sub_project="api",
        )
        assert record.sub_project == "api"

    def test_results_tsv_write_read_preserves_sub_project(self, tmp_path: Path) -> None:
        """Writing and reading results.tsv preserves sub_project column values."""
        from results_tsv import ResultsRecord, parse_results_tsv, write_results_tsv

        records = [
            ResultsRecord(
                timestamp="2026-01-01T00:00:00Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id=f"US-00{i}",
                story_title=f"API Story {i}",
                status="passed",
                duration_sec="10",
                model="haiku",
                retry_num="0",
                commit_sha="abc123",
                run_id="run-1",
                sub_project="api",
            )
            for i in range(1, 6)
        ] + [
            ResultsRecord(
                timestamp="2026-01-01T00:00:00Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id=f"US-0{i}",
                story_title=f"Frontend Story {i}",
                status="passed",
                duration_sec="10",
                model="haiku",
                retry_num="0",
                commit_sha="abc123",
                run_id="run-1",
                sub_project="frontend",
            )
            for i in range(10, 15)
        ]

        tsv_path = str(tmp_path / "results.tsv")
        write_results_tsv(tsv_path, records)
        loaded = parse_results_tsv(tsv_path)

        assert len(loaded) == 10, f"Expected 10 records, got {len(loaded)}"

        api_records = [r for r in loaded if r.sub_project == "api"]
        frontend_records = [r for r in loaded if r.sub_project == "frontend"]

        assert len(api_records) == 5, "Must have 5 api records"
        assert len(frontend_records) == 5, "Must have 5 frontend records"

        for r in api_records:
            assert r.sub_project == "api", f"{r.story_id} has wrong sub_project: {r.sub_project!r}"
        for r in frontend_records:
            assert r.sub_project == "frontend", f"{r.story_id} has wrong sub_project: {r.sub_project!r}"

    def test_results_tsv_sub_project_empty_for_non_federated(self, tmp_path: Path) -> None:
        """Non-federated stories have empty sub_project (backward compatible)."""
        from results_tsv import ResultsRecord, parse_results_tsv, write_results_tsv

        record = ResultsRecord(
            timestamp="2026-01-01T00:00:00Z",
            spiral_iter="1",
            ralph_iter="1",
            story_id="US-001",
            story_title="Standard Story",
            status="passed",
            duration_sec="10",
            model="haiku",
            retry_num="0",
            commit_sha="abc123",
            run_id="run-1",
            # sub_project intentionally omitted (defaults to "")
        )
        tsv_path = str(tmp_path / "results.tsv")
        write_results_tsv(tsv_path, [record])
        loaded = parse_results_tsv(tsv_path)

        assert len(loaded) == 1
        assert loaded[0].sub_project == "", "Non-federated story sub_project must be empty string"
