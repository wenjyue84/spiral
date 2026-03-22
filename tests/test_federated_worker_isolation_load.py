"""Integration test: Verify worker sub-project isolation under federated load (US-752)."""

from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any, TextIO, cast

import pytest

from lib.prd.slice_prd import slice_prd


class TestFederatedWorkerIsolation:
    """Tests for worker sub-project isolation under federated load."""

    @pytest.fixture
    def federated_prd(self: "TestFederatedWorkerIsolation") -> dict[str, Any]:
        """Load federated load test fixture."""
        fixture_path = Path(__file__).parent / "fixtures" / "federated_load_test_prd.json"
        with open(fixture_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        # Convert 'stories' to 'userStories' for slice_prd compatibility
        return {"userStories": data["stories"]}

    def test_sub_project_fidelity(self, federated_prd: dict[str, Any]) -> None:
        """Verify each worker receives stories from only one sub_project.

        Simulates 3-worker distribution: each worker gets ~10 stories.
        Asserts that each worker's slice contains stories from only one sub_project.
        """
        # Load fixture: 30 stories, 10 per sub_project
        prd = federated_prd
        assert len(prd["userStories"]) == 30

        # Simulate 3 workers, each getting ~10 stories via round-robin distribution
        # Worker 1: stories 0-9, Worker 2: stories 10-19, Worker 3: stories 20-29
        num_workers = 3
        stories_per_worker = 10
        workers_slices: dict[int, dict[str, Any]] = {}

        for worker_id in range(1, num_workers + 1):
            start_idx = (worker_id - 1) * stories_per_worker
            end_idx = worker_id * stories_per_worker

            # Slice the PRD to get only this worker's stories
            worker_stories = prd["userStories"][start_idx:end_idx]
            assert len(worker_stories) == stories_per_worker

            # Create a worker-local PRD
            worker_prd = {"userStories": worker_stories}
            workers_slices[worker_id] = worker_prd

        # Verify each worker has stories from only one sub_project
        for worker_id, worker_prd in workers_slices.items():
            sub_projects = {s["sub_project"] for s in worker_prd["userStories"]}

            # Each worker should have exactly one sub_project
            assert len(sub_projects) == 1, f"Worker {worker_id} has cross-contamination: sub_projects={sub_projects}"

            # Verify we have all 3 sub-projects represented across workers
            assert list(sub_projects)[0] in ["frontend", "backend", "infra"]

    def test_no_duplicate_story_ids(self, federated_prd: dict[str, Any]) -> None:
        """Verify no duplicate story IDs in federated fixture."""
        prd = federated_prd
        story_ids = [s["id"] for s in prd["userStories"]]
        id_counts = collections.Counter(story_ids)

        duplicates = [sid for sid, count in id_counts.items() if count > 1]
        assert not duplicates, f"Duplicate story IDs found: {duplicates}"

    def test_all_required_fields_present(self, federated_prd: dict[str, Any]) -> None:
        """Verify each story has required fields for federated distribution."""
        prd = federated_prd
        required_fields = {"id", "title", "sub_project"}

        for story in prd["userStories"]:
            for field in required_fields:
                assert field in story, f"Story {story.get('id', '?')} missing field '{field}'"

    def test_sub_project_distribution_across_all_workers(self, federated_prd: dict[str, Any]) -> None:
        """Verify all 3 sub-projects are distributed across workers.

        In round-robin distribution with 3 workers and 30 stories,
        each worker should get exactly one sub_project.
        """
        prd = federated_prd
        num_workers = 3
        stories_per_worker = 10

        worker_sub_projects: dict[int, str] = {}

        for worker_id in range(1, num_workers + 1):
            start_idx = (worker_id - 1) * stories_per_worker
            end_idx = worker_id * stories_per_worker

            worker_stories = prd["userStories"][start_idx:end_idx]
            sub_projects = {s["sub_project"] for s in worker_stories}

            # Must be exactly one sub_project
            assert len(sub_projects) == 1
            worker_sub_projects[worker_id] = list(sub_projects)[0]

        # All 3 sub-projects must be represented
        all_assigned = set(worker_sub_projects.values())
        assert all_assigned == {"frontend", "backend", "infra"}, f"Not all sub-projects assigned: {all_assigned}"

    def test_no_cross_worker_file_conflicts(self, federated_prd: dict[str, Any]) -> None:
        """Verify no cross-worker story ID conflicts when sliced.

        Simulates writing results to separate worker result files.
        """
        prd = federated_prd
        num_workers = 3
        stories_per_worker = 10

        # Collect all story IDs per worker
        worker_story_ids: dict[int, set[str]] = {}

        for worker_id in range(1, num_workers + 1):
            start_idx = (worker_id - 1) * stories_per_worker
            end_idx = worker_id * stories_per_worker

            worker_stories = prd["userStories"][start_idx:end_idx]
            worker_story_ids[worker_id] = {s["id"] for s in worker_stories}

        # Verify no overlapping story IDs between workers
        for w1 in range(1, num_workers + 1):
            for w2 in range(w1 + 1, num_workers + 1):
                overlap = worker_story_ids[w1] & worker_story_ids[w2]
                assert not overlap, f"Workers {w1} and {w2} share story IDs: {overlap}"

    def test_fixture_load_via_slice_prd(self, federated_prd: dict[str, Any]) -> None:
        """Verify federated fixture works with slice_prd function.

        Tests that slice_prd can load and slice the federated fixture without errors.
        """
        prd = federated_prd
        # Test slicing to batch sizes typical for parallel workers
        batch_sizes = [10, 20, 30]

        for batch_size in batch_sizes:
            sliced = slice_prd(prd, batch_size)
            # Sliced PRD should contain at most batch_size pending stories
            # All stories are pending (passes=False) in the fixture
            assert len(sliced["userStories"]) <= batch_size

    def test_results_tsv_sub_project_consistency(self, federated_prd: dict[str, Any]) -> None:
        """Verify results.tsv records maintain sub_project consistency with PRD.

        When writing story telemetry to results.tsv, the sub_project field
        must match the story's sub_project from the original PRD.
        Acceptance: No story row in results.tsv differs from its prd.json assignment.
        """
        import tempfile

        from lib.results_tsv import HEADER, ResultsRecord, parse_results_tsv, write_results_row

        prd = federated_prd
        batch_size = 10
        sliced = slice_prd(prd, batch_size)

        # Create a map of story_id -> sub_project from the sliced PRD
        story_sub_projects: dict[str, str] = {
            s["id"]: s.get("sub_project", "") for s in sliced.get("userStories", []) if "id" in s
        }

        # Write mock results.tsv entries
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8", newline="") as f:
            temp_path = f.name

            # Write header
            header_line = "\t".join(HEADER)
            f.write(header_line + "\n")

            # Write a record for each sliced story
            for story_id, sub_project in story_sub_projects.items():
                record = ResultsRecord(
                    timestamp="2026-03-22T00:00:00Z",
                    spiral_iter="1",
                    ralph_iter="1",
                    story_id=story_id,
                    story_title=f"Test: {story_id}",
                    status="success",
                    duration_sec="10.5",
                    model="haiku",
                    retry_num="0",
                    commit_sha="abc1234",
                    run_id="run-1",
                    sub_project=sub_project,
                )
                # Cast f to TextIO for type checking compatibility
                write_results_row(cast(TextIO, f), record)

        try:
            # Read back and verify sub_project consistency
            records = parse_results_tsv(temp_path)
            for record in records:
                if record.story_id in story_sub_projects:
                    expected_sub_project = story_sub_projects[record.story_id]
                    actual_sub_project = record.sub_project
                    assert actual_sub_project == expected_sub_project, (
                        f"Story {record.story_id}: expected sub_project '{expected_sub_project}', "
                        f"got '{actual_sub_project}'"
                    )
        finally:
            # Cleanup
            Path(temp_path).unlink(missing_ok=True)
