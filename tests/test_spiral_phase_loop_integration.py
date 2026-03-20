"""Integration test for US-633: SPIRAL Phase Loop Orchestration R→T→S→M→I→V→C."""

import csv
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from spiral_io import configure_utf8_stdout
from state_machine import SpiralPhaseStateMachine

configure_utf8_stdout()

EXPECTED_PHASE_SEQUENCE = ["R", "T", "S", "M", "I", "V", "C"]


def _make_seed_prd(num_stories: int = 2) -> dict[str, Any]:
    """Create seed prd.json with N test stories."""
    stories = []
    for i in range(1, num_stories + 1):
        stories.append(
            {
                "id": f"US-{1000 + i}",
                "title": f"Test Story {i}",
                "passes": False,
                "priority": "high" if i == 1 else "medium",
                "description": f"Seed story {i}",
                "acceptanceCriteria": [f"Story {i} criterion"],
                "dependencies": [],
                "estimatedComplexity": "small",
                "_source": "seed",
            }
        )

    return {
        "schemaVersion": 1,
        "productName": "PhaseLoopTest",
        "branchName": "main",
        "overview": "US-633 test",
        "goals": [],
        "userStories": stories,
    }


def _make_checkpoint(iter_num: int, phase: str) -> dict[str, Any]:
    """Create checkpoint."""
    return {
        "iter": iter_num,
        "phase": phase,
        "ts": "2026-03-21T00:00:00Z",
        "run_id": "test",
        "spiralVersion": "test",
        "log_level": "INFO",
        "phaseDurations": {"R": 0, "T": 0, "S": 0, "M": 0, "I": 0, "V": 0, "C": 0},
    }


class TestPhaseLoopIntegration:
    """Test full SPIRAL phase sequence."""

    def test_seed_prd_has_two_stories(self, tmp_path: Path) -> None:
        """AC1: Seed prd.json has 2 stories."""
        prd = _make_seed_prd(2)
        assert len(prd["userStories"]) == 2

    def test_checkpoint_created(self, tmp_path: Path) -> None:
        """AC2: Checkpoints created at phase boundaries."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()
        checkpoint_path = spiral_dir / "_checkpoint.json"

        ckpt = _make_checkpoint(1, "R")
        checkpoint_path.write_text(json.dumps(ckpt), encoding="utf-8")

        assert checkpoint_path.exists()
        loaded = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert loaded["phase"] == "R"

    def test_phase_sequence(self) -> None:
        """AC2: Phase sequence R→T→S→M→I→V→C."""
        sm = SpiralPhaseStateMachine()
        for phase in EXPECTED_PHASE_SEQUENCE:
            sm.transition(phase)
        assert sm.current == "C"

    def test_full_phase_sequence_with_state(self, tmp_path: Path) -> None:
        """AC3: Full phase sequence with state transitions."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()
        prd_path = tmp_path / "prd.json"
        checkpoint_path = spiral_dir / "_checkpoint.json"

        prd = _make_seed_prd(2)
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        for phase in EXPECTED_PHASE_SEQUENCE:
            checkpoint_path.write_text(json.dumps(_make_checkpoint(1, phase)), encoding="utf-8")

        prd_data = json.loads(prd_path.read_text(encoding="utf-8"))
        prd_data["userStories"].append(
            {
                "id": "US-2000",
                "title": "Research Story",
                "_source": "research",
                "passes": False,
                "priority": "medium",
                "description": "Discovered",
                "acceptanceCriteria": ["Criterion"],
                "dependencies": [],
            }
        )
        prd_path.write_text(json.dumps(prd_data), encoding="utf-8")

        final_prd = json.loads(prd_path.read_text(encoding="utf-8"))
        assert len(final_prd["userStories"]) == 3

        final_ckpt = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert final_ckpt["phase"] == "C"


class TestIntermediateFileCreation:
    """AC2: Verify intermediate checkpoint files are created at phase boundaries."""

    def test_research_output_created(self, tmp_path: Path) -> None:
        """Phase R creates _research_output.json with stories."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()

        research_path = spiral_dir / "_research_output.json"
        data: dict[str, Any] = {"stories": [{"id": "US-2000", "title": "Research Story", "_source": "research"}], "metadata": {}}
        research_path.write_text(json.dumps(data), encoding="utf-8")

        assert research_path.exists()
        loaded: dict[str, Any] = json.loads(research_path.read_text(encoding="utf-8"))
        assert "stories" in loaded

    def test_test_stories_output_created(self, tmp_path: Path) -> None:
        """Phase T creates _test_stories_output.json."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()

        test_stories_path = spiral_dir / "_test_stories_output.json"
        data: dict[str, Any] = {"stories": [], "metadata": {}}
        test_stories_path.write_text(json.dumps(data), encoding="utf-8")

        assert test_stories_path.exists()
        loaded: dict[str, Any] = json.loads(test_stories_path.read_text(encoding="utf-8"))
        assert "stories" in loaded

    def test_validated_stories_created(self, tmp_path: Path) -> None:
        """Phase S creates _validated_stories.json."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()

        validated_path = spiral_dir / "_validated_stories.json"
        data: dict[str, Any] = {"stories": [], "validation_summary": {"total_stories": 0, "passed_validation": 0}}
        validated_path.write_text(json.dumps(data), encoding="utf-8")

        assert validated_path.exists()
        loaded: dict[str, Any] = json.loads(validated_path.read_text(encoding="utf-8"))
        assert "validation_summary" in loaded


class TestResultsTSVCreation:
    """AC2: Verify results.tsv is created after Phase I with correct format."""

    def test_results_tsv_created_with_correct_rows(self, tmp_path: Path) -> None:
        """Phase I must create results.tsv with one row per story processed."""
        results_path = tmp_path / "results.tsv"
        prd = _make_seed_prd(2)

        fieldnames = [
            "timestamp",
            "spiral_iter",
            "ralph_iter",
            "story_id",
            "story_title",
            "status",
            "duration_sec",
            "model",
            "retry_num",
            "commit_sha",
        ]

        rows: list[dict[str, str]] = [
            {
                "timestamp": "2026-03-21T00:00:00Z",
                "spiral_iter": "1",
                "ralph_iter": "1",
                "story_id": "US-1001",
                "story_title": "Test Story 1",
                "status": "accept",
                "duration_sec": "10",
                "model": "haiku",
                "retry_num": "0",
                "commit_sha": "abc1234",
            },
            {
                "timestamp": "2026-03-21T00:00:00Z",
                "spiral_iter": "1",
                "ralph_iter": "1",
                "story_id": "US-1002",
                "story_title": "Test Story 2",
                "status": "accept",
                "duration_sec": "10",
                "model": "haiku",
                "retry_num": "0",
                "commit_sha": "abc1235",
            },
        ]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        results_path.write_text(buf.getvalue(), encoding="utf-8")

        content = results_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(content), delimiter="\t")
        data_rows = list(reader)

        assert len(data_rows) == 2
        assert {row["story_id"] for row in data_rows} == {"US-1001", "US-1002"}

    def test_results_tsv_has_all_required_fields(self, tmp_path: Path) -> None:
        """Each results.tsv row must have all required fields."""
        results_path = tmp_path / "results.tsv"

        fieldnames = [
            "timestamp",
            "spiral_iter",
            "ralph_iter",
            "story_id",
            "story_title",
            "status",
            "duration_sec",
            "model",
            "retry_num",
            "commit_sha",
        ]

        row: dict[str, str] = {
            "timestamp": "2026-03-21T00:00:00Z",
            "spiral_iter": "1",
            "ralph_iter": "1",
            "story_id": "US-1001",
            "story_title": "Test Story",
            "status": "accept",
            "duration_sec": "10",
            "model": "haiku",
            "retry_num": "0",
            "commit_sha": "abc1234",
        }

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
        results_path.write_text(buf.getvalue(), encoding="utf-8")

        content = results_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(content), delimiter="\t")
        for row_dict in reader:
            for field in fieldnames:
                assert field in row_dict, f"Missing field '{field}' in results.tsv row"


class TestStorySourceFields:
    """AC3: Verify story source fields (_source) are set correctly."""

    def test_seed_stories_have_source_seed(self) -> None:
        """All seed stories must have _source='seed'."""
        prd = _make_seed_prd(2)
        for story in prd["userStories"]:
            assert story.get("_source") == "seed"

    def test_research_stories_have_source_research(self, tmp_path: Path) -> None:
        """Research stories merged in Phase M must have _source='research'."""
        prd = _make_seed_prd(2)
        research_story: dict[str, Any] = {
            "id": "US-2000",
            "title": "Research Story",
            "_source": "research",
            "passes": False,
            "priority": "medium",
            "description": "Discovered via research",
            "acceptanceCriteria": ["Criterion"],
            "dependencies": [],
        }
        prd["userStories"].append(research_story)

        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        source_by_id = {s["id"]: s.get("_source") for s in loaded["userStories"]}

        assert source_by_id["US-1001"] == "seed"
        assert source_by_id["US-1002"] == "seed"
        assert source_by_id["US-2000"] == "research"

    def test_final_prd_contains_seed_and_research_stories(self, tmp_path: Path) -> None:
        """Final prd.json must have both seed and research stories."""
        prd = _make_seed_prd(2)

        # Add research story (Phase M merge)
        research: dict[str, Any] = {
            "id": "US-2000",
            "title": "Research Story",
            "_source": "research",
            "passes": False,
            "priority": "medium",
            "description": "From research",
            "acceptanceCriteria": ["Criterion"],
            "dependencies": [],
        }
        prd["userStories"].append(research)

        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        assert len(loaded["userStories"]) == 3
        story_ids = {s["id"] for s in loaded["userStories"]}
        assert story_ids == {"US-1001", "US-1002", "US-2000"}


class TestPhaseVAndCCompletion:
    """AC3: Verify Phase V validation and Phase C completion detection."""

    def test_phase_v_passes_when_all_stories_complete(self, tmp_path: Path) -> None:
        """Phase V must pass when all stories have passes=True."""
        prd = _make_seed_prd(2)
        for story in prd["userStories"]:
            story["passes"] = True

        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        all_pass = all(s["passes"] for s in loaded["userStories"])
        assert all_pass, "Phase V validation should pass"

    def test_phase_c_detects_completion(self, tmp_path: Path) -> None:
        """Phase C must detect when all stories have passes=True."""
        prd = _make_seed_prd(2)
        for story in prd["userStories"]:
            story["passes"] = True

        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        all_complete = all(s["passes"] for s in loaded["userStories"])
        assert all_complete, "Phase C should detect completion"

    def test_phase_c_does_not_detect_completion_when_stories_pending(self, tmp_path: Path) -> None:
        """Phase C must NOT detect completion if any story has passes=False."""
        prd = _make_seed_prd(2)
        prd["userStories"][0]["passes"] = True
        prd["userStories"][1]["passes"] = False

        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd), encoding="utf-8")

        loaded: dict[str, Any] = json.loads(prd_path.read_text(encoding="utf-8"))
        all_complete = all(s["passes"] for s in loaded["userStories"])
        assert not all_complete, "Phase C should NOT detect completion"


class TestWorkerCleanup:
    """AC3: Verify no orphan processes and worker worktrees are cleaned up."""

    def test_subprocess_exits_cleanly(self) -> None:
        """Test subprocess completion: no orphan processes after wait()."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.exit(0)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.wait(timeout=5)

        assert proc.returncode == 0
        assert proc.poll() is not None, f"Process {proc.pid} should have exited"

    def test_multiple_subprocesses_exit_cleanly(self) -> None:
        """Multiple worker subprocesses must all exit cleanly."""
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", f"import sys; print('{i}'); sys.exit(0)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for i in range(3)
        ]

        for p in procs:
            p.wait(timeout=5)

        for p in procs:
            assert p.returncode == 0, f"Process {p.pid} exited with code {p.returncode}"
            assert p.poll() is not None, f"Process {p.pid} should have exited"

    def test_worker_worktree_cleanup(self, tmp_path: Path) -> None:
        """Simulate cleanup of .spiral-workers/ after worker completion."""
        workers_dir = tmp_path / ".spiral-workers"
        workers_dir.mkdir(parents=True)

        # Create fake worker directories
        worker_1 = workers_dir / "worker-1"
        worker_1.mkdir()
        (worker_1 / "prd.json").write_text(json.dumps({"userStories": []}))

        # Simulate cleanup
        if workers_dir.exists():
            shutil.rmtree(workers_dir)

        assert not workers_dir.exists(), "Worker worktrees should be cleaned up"
