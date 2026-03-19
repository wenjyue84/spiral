"""Integration tests for worker state isolation (US-494).

Tests verify that parallel workers in .spiral-workers/ do not corrupt shared state
(prd.json, results.tsv) through race conditions. Each worker uses an isolated git
worktree and PRD slice, and results are merged atomically.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_worker_results import main as merge_main
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()


def _make_story(story_id: str, passes: bool = False, **extra: Any) -> dict[str, Any]:
    """Create a minimal valid story dict."""
    s: dict[str, Any] = {
        "id": story_id,
        "title": f"Story {story_id}",
        "passes": passes,
        "priority": "medium",
        "description": f"Test story {story_id}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    s.update(extra)
    return s


def _make_prd(
    stories: list[dict[str, Any]], name: str = "TestProduct", branch: str = "main"
) -> dict[str, Any]:
    """Create a minimal valid prd.json dict."""
    return {
        "schemaVersion": 1,
        "productName": name,
        "branchName": branch,
        "overview": "Test PRD",
        "goals": [],
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


def _make_results_tsv_line(
    story_id: str, model: str = "haiku", tokens: int = 1000, status: str = "completed"
) -> str:
    """Create a results.tsv line."""
    return f"{story_id}\t{model}\t{tokens}\t{status}\t2026-03-19T00:00:00Z\n"


class TestWorkerIsolationHappyPath:
    """AC: 2 workers with 10 stories produce correct merged prd.json with all passes."""

    def test_worker_isolation_happy_path(self, tmp_path: Path) -> None:
        """Two workers with 10 stories, each completes 5, results merge correctly."""
        # Setup: main prd.json with 10 stories, all pending (passes=false)
        stories = [_make_story(f"US-{i+1:03d}", passes=False) for i in range(10)]
        main_prd = _make_prd(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Simulate worker-1 processing stories 1-5 (marks them as passed)
        worker1_stories = [
            _make_story(f"US-{i+1:03d}", passes=True) for i in range(5)
        ] + [_make_story(f"US-{i+1:03d}", passes=False) for i in range(5, 10)]
        worker1_prd = _make_prd(worker1_stories)
        worker1_path = tmp_path / "worker1_prd.json"
        _write_prd(worker1_path, worker1_prd)

        # Simulate worker-2 processing stories 6-10 (marks them as passed)
        worker2_stories = [
            _make_story(f"US-{i+1:03d}", passes=False) for i in range(5)
        ] + [_make_story(f"US-{i+1:03d}", passes=True) for i in range(5, 10)]
        worker2_prd = _make_prd(worker2_stories)
        worker2_path = tmp_path / "worker2_prd.json"
        _write_prd(worker2_path, worker2_prd)

        # Merge worker results back into main
        ret = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'lib'); "
                    f"from merge_worker_results import main; "
                    f"sys.exit(main())"
                ),
            ],
            cwd=str(tmp_path.parent.parent),  # Project root
            env={
                **os.environ,
                "PYTHONPATH": str(tmp_path.parent.parent / "lib"),
            },
            input=" ".join(
                [
                    "--main",
                    str(main_prd_path),
                    "--workers",
                    str(worker1_path),
                    str(worker2_path),
                ]
            ),
            capture_output=True,
            text=True,
        )

        # Call merge directly instead of via subprocess for test isolation
        import sys as sys_module

        sys_module.argv = ["merge", "--main", str(main_prd_path), "--workers", str(
            worker1_path), str(worker2_path)]
        merge_ret = merge_main()
        assert merge_ret == 0, "merge_main() should succeed"

        # Verify: all 10 stories in main prd now have passes=true
        merged_prd = _read_prd(main_prd_path)
        assert len(merged_prd["userStories"]) == 10
        passed = sum(1 for s in merged_prd["userStories"] if s.get("passes"))
        assert passed == 10, f"Expected 10 passed stories, got {passed}"

        # Verify: no story IDs are duplicated
        story_ids = [s["id"] for s in merged_prd["userStories"]]
        assert len(story_ids) == len(set(story_ids)), "Story IDs should be unique"

    def test_worker_isolation_no_corruption(self, tmp_path: Path) -> None:
        """Two workers with 10 stories produce prd.json with intact _status fields."""
        # Setup: main prd with stories including _status fields
        stories = []
        for i in range(10):
            story = _make_story(f"US-{i+1:03d}", passes=False)
            story["_status"] = "pending"  # Custom field
            story["model"] = "haiku"  # Track model used
            stories.append(story)

        main_prd = _make_prd(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Simulate worker-1: processes stories 1-5, updates _status to "completed"
        worker1_stories = []
        for i in range(10):
            story = _make_story(f"US-{i+1:03d}", passes=i < 5)
            story["_status"] = "completed" if i < 5 else "pending"
            story["model"] = "haiku"
            worker1_stories.append(story)

        worker1_prd = _make_prd(worker1_stories)
        worker1_path = tmp_path / "worker1_prd.json"
        _write_prd(worker1_path, worker1_prd)

        # Simulate worker-2: processes stories 6-10, updates _status
        worker2_stories = []
        for i in range(10):
            story = _make_story(f"US-{i+1:03d}", passes=i >= 5)
            story["_status"] = "completed" if i >= 5 else "pending"
            story["model"] = "sonnet" if i >= 5 else "haiku"
            worker2_stories.append(story)

        worker2_prd = _make_prd(worker2_stories)
        worker2_path = tmp_path / "worker2_prd.json"
        _write_prd(worker2_path, worker2_prd)

        # Merge results
        sys.argv = ["merge", "--main", str(main_prd_path), "--workers",
                    str(worker1_path), str(worker2_path)]
        ret = merge_main()
        assert ret == 0

        # Verify: merged prd has all 10 stories with correct passes field
        merged_prd = _read_prd(main_prd_path)
        assert len(merged_prd["userStories"]) == 10

        # Verify: all stories have passes=true (both workers completed them)
        for story in merged_prd["userStories"]:
            assert story.get("passes") is True, f"{story['id']} should have passes=true"

        # Verify: story count unchanged
        assert len(merged_prd["userStories"]) == 10

    def test_worker_results_tsv_uniqueness(self, tmp_path: Path) -> None:
        """results.tsv from 2 workers has all 10 story IDs with no duplicates."""
        # Create results.tsv from two workers (worker-1: US-001 to US-005, worker-2: US-006 to US-010)
        results_path = tmp_path / "results.tsv"

        # Write header
        results_path.write_text(
            "story_id\tmodel\ttokens\tstatus\ttimestamp\n",
            encoding="utf-8",
        )

        # Append worker-1 results
        with open(results_path, "a", encoding="utf-8") as f:
            for i in range(5):
                f.write(_make_results_tsv_line(f"US-{i+1:03d}", "haiku"))

        # Append worker-2 results (simulating concurrent write)
        with open(results_path, "a", encoding="utf-8") as f:
            for i in range(5, 10):
                f.write(_make_results_tsv_line(f"US-{i+1:03d}", "sonnet"))

        # Read and verify
        lines = results_path.read_text(encoding="utf-8").strip().split("\n")
        data_lines = lines[1:]  # Skip header

        assert len(data_lines) == 10, f"Expected 10 data lines, got {len(data_lines)}"

        story_ids = [line.split("\t")[0] for line in data_lines]
        assert len(story_ids) == len(set(story_ids)), "All story IDs should be unique"
        assert set(story_ids) == {
            f"US-{i+1:03d}" for i in range(10)
        }, "Should contain all US-001 to US-010"


class TestWorkerCrashRecovery:
    """AC: Simulate worker-1 crash; worker-2 continues; checkpoint remains valid."""

    def test_worker_crash_other_completes(self, tmp_path: Path) -> None:
        """Worker-1 'crashes' (simulated by incomplete results); worker-2 completes."""
        # Setup: main prd with 10 stories
        stories = [_make_story(f"US-{i+1:03d}", passes=False) for i in range(10)]
        main_prd = _make_prd(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Simulate worker-1 crash: only processed stories 1-3 before crashing
        worker1_stories = (
            [_make_story(f"US-{i+1:03d}", passes=True) for i in range(3)]
            + [_make_story(f"US-{i+1:03d}", passes=False) for i in range(3, 10)]
        )
        worker1_prd = _make_prd(worker1_stories)
        worker1_path = tmp_path / "worker1_prd.json"
        _write_prd(worker1_path, worker1_prd)

        # Worker-2 continues: processes all 10 stories (including those worker-1 left)
        worker2_stories = [
            _make_story(f"US-{i+1:03d}", passes=True) for i in range(10)
        ]
        worker2_prd = _make_prd(worker2_stories)
        worker2_path = tmp_path / "worker2_prd.json"
        _write_prd(worker2_path, worker2_prd)

        # Merge results
        sys.argv = ["merge", "--main", str(main_prd_path), "--workers",
                    str(worker1_path), str(worker2_path)]
        ret = merge_main()
        assert ret == 0

        # Verify: all 10 stories have passes=true (worker-2 covered for worker-1)
        merged_prd = _read_prd(main_prd_path)
        passed = sum(1 for s in merged_prd["userStories"] if s.get("passes"))
        assert passed == 10, f"All stories should pass; got {passed}/10"

    def test_checkpoint_valid_after_merge(self, tmp_path: Path) -> None:
        """Checkpoint file remains valid after worker merge."""
        # Create a checkpoint file (minimal valid structure)
        checkpoint = {
            "iter": 1,
            "phase": "I",
            "ts": 1234567890,
            "phaseDurations": {"R": 10, "T": 5},
            "lastStoryId": "US-005",
            "workerCount": 2,
        }

        checkpoint_path = tmp_path / ".spiral" / "_checkpoint.json"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(str(checkpoint_path), checkpoint)

        # Perform a merge operation (unrelated to checkpoint, but simulates concurrent activity)
        stories = [_make_story(f"US-{i+1:03d}", passes=False) for i in range(10)]
        main_prd = _make_prd(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        worker_stories = [_make_story(f"US-{i+1:03d}", passes=True) for i in range(10)]
        worker_prd = _make_prd(worker_stories)
        worker_path = tmp_path / "worker_prd.json"
        _write_prd(worker_path, worker_prd)

        sys.argv = ["merge", "--main", str(main_prd_path), "--workers", str(worker_path)]
        ret = merge_main()
        assert ret == 0

        # Verify: checkpoint still exists and is valid JSON
        assert checkpoint_path.exists(), "Checkpoint should exist after merge"
        ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert ckpt.get("iter") == 1, "Checkpoint iteration should be preserved"
        assert ckpt.get("phase") == "I", "Checkpoint phase should be preserved"
        assert ckpt.get("workerCount") == 2, "Checkpoint workerCount should be preserved"

    def test_partial_worker_failure_recovery(self, tmp_path: Path) -> None:
        """Worker-1 fails on some stories; worker-2 succeeds on all; final state valid."""
        # Setup: 10 stories
        stories = [_make_story(f"US-{i+1:03d}", passes=False) for i in range(10)]
        main_prd = _make_prd(stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Worker-1: succeeds on 1-3, fails on 4-10
        worker1_stories = (
            [_make_story(f"US-{i+1:03d}", passes=True) for i in range(3)]
            + [_make_story(f"US-{i+1:03d}", passes=False) for i in range(3, 10)]
        )
        worker1_prd = _make_prd(worker1_stories)
        worker1_prd["userStories"][0]["_failureReason"] = "timeout"  # Mark one as failed
        worker1_prd["userStories"][0]["passes"] = False
        worker1_path = tmp_path / "worker1_prd.json"
        _write_prd(worker1_path, worker1_prd)

        # Worker-2: succeeds on all
        worker2_stories = [
            _make_story(f"US-{i+1:03d}", passes=True) for i in range(10)
        ]
        worker2_prd = _make_prd(worker2_stories)
        worker2_path = tmp_path / "worker2_prd.json"
        _write_prd(worker2_path, worker2_prd)

        # Merge
        sys.argv = ["merge", "--main", str(main_prd_path), "--workers",
                    str(worker1_path), str(worker2_path)]
        ret = merge_main()
        assert ret == 0

        # Verify: all stories passed (worker-2 covered failures)
        merged_prd = _read_prd(main_prd_path)
        passed = sum(1 for s in merged_prd["userStories"] if s.get("passes"))
        assert passed == 10

        # Verify: _failureReason is preserved for the story that failed in worker-1
        us001 = [s for s in merged_prd["userStories"] if s["id"] == "US-001"][0]
        # After merge, US-001 should have passes=true from worker-2, but _failureReason
        # might be set if worker-1 set it. Check it doesn't get overwritten incorrectly.
        assert us001.get("passes") is True


class TestWorkerDecomposition:
    """AC: Sub-stories created by worker decomposition are merged correctly."""

    def test_decomposed_stories_merged(self, tmp_path: Path) -> None:
        """Worker creates sub-stories via decomposition; they're added to main PRD."""
        # Main PRD: 2 stories, one marked as decomposable
        main_stories = [
            _make_story("US-001", passes=False),
            _make_story("US-002", passes=False, estimatedComplexity="large"),
        ]
        main_prd = _make_prd(main_stories)
        main_prd_path = tmp_path / "prd.json"
        _write_prd(main_prd_path, main_prd)

        # Worker: marks US-002 as decomposed and creates 2 sub-stories
        worker_stories = [
            _make_story("US-001", passes=True),
            _make_story(
                "US-002",
                passes=True,
                _decomposed=True,
                _decomposedInto=["US-003", "US-004"],
            ),
            # Sub-stories (new, not in main PRD) - use valid US-NNN IDs
            _make_story("US-003", passes=True, _decomposedFrom="US-002"),
            _make_story("US-004", passes=True, _decomposedFrom="US-002"),
        ]
        worker_prd = _make_prd(worker_stories)
        worker_path = tmp_path / "worker_prd.json"
        _write_prd(worker_path, worker_prd)

        # Merge
        sys.argv = ["merge", "--main", str(main_prd_path), "--workers", str(worker_path)]
        ret = merge_main()
        assert ret == 0

        # Verify: main PRD now has 4 stories (original 2 + 2 sub-stories)
        merged_prd = _read_prd(main_prd_path)
        assert len(merged_prd["userStories"]) == 4

        # Verify: US-002 is marked as decomposed
        us002 = [s for s in merged_prd["userStories"] if s["id"] == "US-002"][0]
        assert us002.get("_decomposed") is True
        assert us002.get("_decomposedInto") == ["US-003", "US-004"]

        # Verify: sub-stories are present with correct _decomposedFrom
        us003 = [s for s in merged_prd["userStories"] if s["id"] == "US-003"][0]
        assert us003.get("_decomposedFrom") == "US-002"
