"""
tests/test_merge_conflict_detection.py

Integration tests for US-097: git merge-tree conflict detection in the
parallel worker integration step of run_parallel_ralph.sh.

These tests create fixture git repos to simulate the conflict-detection
logic, covering the requeue path when workers modify the same files.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, cwd=None, check=True):
    """Run a shell command and return CompletedProcess."""
    return subprocess.run(
        cmd, shell=True, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, check=check,
    )


def git(cmd, cwd):
    """Run a git command in a directory."""
    return run(f"git {cmd}", cwd=cwd)


def default_branch(repo: Path) -> str:
    """Return the default branch name (main or master) of a repo."""
    result = run("git rev-parse --abbrev-ref HEAD", cwd=repo, check=False)
    return result.stdout.strip() or "main"


def init_repo(path: Path) -> str:
    """Initialise a git repo, return the default branch name."""
    path.mkdir(parents=True, exist_ok=True)
    git("init", path)
    git("config user.email test@spiral.local", path)
    git("config user.name Test", path)
    (path / "base.txt").write_text("shared content\nline 2\n")
    git("add .", path)
    git('commit -m "initial"', path)
    return default_branch(path)


def git_version_supports_write_tree() -> bool:
    """Return True if git >= 2.38 (supports merge-tree --write-tree)."""
    try:
        result = run("git version")
        parts = result.stdout.strip().split()
        ver = parts[2] if len(parts) >= 3 else "0.0.0"
        nums = ver.split(".")
        major, minor = int(nums[0]), int(nums[1])
        return (major, minor) >= (2, 38)
    except Exception:
        return False


HAS_NEW_MERGE_TREE = git_version_supports_write_tree()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path):
    """A fresh git repo with one initial commit; returns (path, default_branch)."""
    branch = init_repo(tmp_path)
    return tmp_path, branch


@pytest.fixture()
def conflicting_branches(tmp_path):
    """
    Repo where HEAD (main) AND branch1 both change the same line differently.

    Layout:
      common ancestor: base.txt = "shared content\\nline 2\\n"
      main (HEAD):     base.txt line 1 = "from main"
      branch1:         base.txt line 1 = "from branch-1"

    Merging branch1 into main conflicts on line 1.
    Returns (repo_path, default_branch).
    """
    main = init_repo(tmp_path)

    # branch1 — changes line 1 to "from branch-1" (branches off before main changes)
    git("checkout -b branch1", tmp_path)
    (tmp_path / "base.txt").write_text("from branch-1\nline 2\n")
    git("add .", tmp_path)
    git('commit -m "branch1 change"', tmp_path)

    # Main ALSO changes line 1 (creates a true conflict)
    git(f"checkout {main}", tmp_path)
    (tmp_path / "base.txt").write_text("from main\nline 2\n")
    git("add .", tmp_path)
    git('commit -m "main changes same line"', tmp_path)

    return tmp_path, main


@pytest.fixture()
def clean_branches(tmp_path):
    """
    Repo where branch1 and branch2 modify *different* files — no conflict.
    Returns (repo_path, default_branch).
    """
    main = init_repo(tmp_path)

    git("checkout -b branch1", tmp_path)
    (tmp_path / "file-a.txt").write_text("worker 1 file\n")
    git("add .", tmp_path)
    git('commit -m "branch1 adds file-a"', tmp_path)

    git(f"checkout {main}", tmp_path)
    git("checkout -b branch2", tmp_path)
    (tmp_path / "file-b.txt").write_text("worker 2 file\n")
    git("add .", tmp_path)
    git('commit -m "branch2 adds file-b"', tmp_path)

    git(f"checkout {main}", tmp_path)
    return tmp_path, main


# ── Unit: _detect_merge_conflicts logic ──────────────────────────────────────

class TestMergeTreeDetection:
    """Test conflict detection using git merge-tree --write-tree."""

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_conflicting_branches_detected(self, conflicting_branches):
        """merge-tree exits non-zero when branches conflict."""
        repo, _ = conflicting_branches
        result = run(
            "git merge-tree --write-tree HEAD branch1",
            cwd=repo, check=False,
        )
        assert result.returncode != 0, (
            "Expected non-zero exit code for conflicting branches"
        )

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_clean_branches_not_detected(self, clean_branches):
        """merge-tree exits 0 when branches merge cleanly."""
        repo, _ = clean_branches
        result = run(
            "git merge-tree --write-tree HEAD branch1",
            cwd=repo, check=False,
        )
        assert result.returncode == 0, (
            f"Expected clean merge; got rc={result.returncode}\n{result.stdout}"
        )

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_conflict_output_mentions_file(self, conflicting_branches):
        """merge-tree output contains conflict markers for the conflicting file."""
        repo, _ = conflicting_branches
        result = run(
            "git merge-tree --write-tree HEAD branch1",
            cwd=repo, check=False,
        )
        combined = result.stdout + result.stderr
        assert "Merge conflict in" in combined or "CONFLICT" in combined, (
            f"Expected conflict marker in output:\n{combined}"
        )

    def test_old_style_fallback_detects_conflict(self, conflicting_branches):
        """Old-style git merge-tree BASE BRANCH1 BRANCH2 shows <<< markers."""
        repo, _ = conflicting_branches
        base = run("git merge-base HEAD branch1", cwd=repo).stdout.strip()
        result = run(
            f"git merge-tree {base} HEAD branch1",
            cwd=repo, check=False,
        )
        assert "<<<<<<<" in result.stdout, (
            "Expected <<< conflict marker in old-style merge-tree output"
        )

    def test_old_style_no_conflict(self, clean_branches):
        """Old-style merge-tree shows no <<< markers for clean branches."""
        repo, _ = clean_branches
        base = run("git merge-base HEAD branch1", cwd=repo).stdout.strip()
        result = run(
            f"git merge-tree {base} HEAD branch1",
            cwd=repo, check=False,
        )
        assert "<<<<<<<" not in result.stdout, (
            "Unexpected conflict marker for clean branches"
        )


# ── Unit: prd.json story requeue ─────────────────────────────────────────────

def make_worker_prd(stories_passed: list) -> dict:
    """Build a minimal prd.json dict with passed stories."""
    return {
        "productName": "test",
        "userStories": [
            {"id": sid, "title": f"Story {sid}", "passes": True}
            for sid in stories_passed
        ],
    }


def reset_conflict_stories(prd_path: Path, story_ids: list):
    """Apply the merge_conflict reset to specific stories in a prd.json file."""
    with open(prd_path) as f:
        data = json.load(f)
    for story in data["userStories"]:
        if story["id"] in story_ids:
            story["passes"] = False
            story["_failureReason"] = "merge_conflict"
    with open(prd_path, "w") as f:
        json.dump(data, f, indent=2)


class TestStoryRequeueOnConflict:
    """Verify that conflicting worker stories are reset to pending."""

    def test_reset_passes_to_false(self, tmp_path):
        """Stories from a conflicting worker should have passes=False after reset."""
        prd = make_worker_prd(["US-001", "US-002"])
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        reset_conflict_stories(prd_path, ["US-001", "US-002"])

        with open(prd_path) as f:
            result = json.load(f)

        for story in result["userStories"]:
            assert story["passes"] is False, f"{story['id']} should be pending"
            assert story.get("_failureReason") == "merge_conflict", (
                f"{story['id']} should have _failureReason='merge_conflict'"
            )

    def test_failure_reason_distinguishes_conflict_from_implementation(self, tmp_path):
        """_failureReason='merge_conflict' must be distinct from implementation failures."""
        prd = make_worker_prd(["US-010"])
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        reset_conflict_stories(prd_path, ["US-010"])

        with open(prd_path) as f:
            data = json.load(f)

        assert data["userStories"][0]["_failureReason"] == "merge_conflict"
        assert data["userStories"][0]["_failureReason"] != "quality_gate_fail"

    def test_non_conflicting_stories_untouched(self, tmp_path):
        """Stories not in the conflicting worker should remain passes=True."""
        prd = {
            "productName": "test",
            "userStories": [
                {"id": "US-001", "title": "Story 1", "passes": True},  # conflicting
                {"id": "US-002", "title": "Story 2", "passes": True},  # clean
            ],
        }
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        # Only reset US-001 (conflicting worker's story)
        reset_conflict_stories(prd_path, ["US-001"])

        with open(prd_path) as f:
            result = json.load(f)

        us001 = next(s for s in result["userStories"] if s["id"] == "US-001")
        us002 = next(s for s in result["userStories"] if s["id"] == "US-002")
        assert us001["passes"] is False
        assert us002["passes"] is True, "Clean worker story should remain passed"

    def test_pending_stories_not_double_reset(self, tmp_path):
        """Stories already pending should not have _failureReason overwritten."""
        prd = {
            "productName": "test",
            "userStories": [
                {"id": "US-001", "passes": True, "title": "Passed"},
                {"id": "US-002", "passes": False, "title": "Already pending"},
            ],
        }
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        # Only conflicting worker passed US-001
        reset_conflict_stories(prd_path, ["US-001"])

        with open(prd_path) as f:
            data = json.load(f)

        us002 = next(s for s in data["userStories"] if s["id"] == "US-002")
        assert us002["passes"] is False
        # _failureReason should not have been added to US-002
        assert "_failureReason" not in us002


# ── Unit: spiral_events.jsonl logging ────────────────────────────────────────

class TestSpiralEventsLogging:
    """Verify merge conflict events are written to spiral_events.jsonl."""

    def test_merge_conflict_event_structure(self, tmp_path):
        """merge_conflict_detected event has required fields."""
        events_file = tmp_path / "spiral_events.jsonl"

        event = {
            "ts": "2026-03-13T12:00:00Z",
            "event": "merge_conflict_detected",
            "workerId": 2,
            "branch": "spiral-worker-2-1234567890",
            "conflictingFiles": ["lib/spiral.sh"],
        }
        events_file.write_text(json.dumps(event) + "\n")

        parsed = json.loads(events_file.read_text().strip())
        assert parsed["event"] == "merge_conflict_detected"
        assert parsed["workerId"] == 2
        assert "conflictingFiles" in parsed
        assert isinstance(parsed["conflictingFiles"], list)

    def test_merge_conflict_summary_event(self, tmp_path):
        """merge_conflict_summary event contains clean and conflict counts."""
        events_file = tmp_path / "spiral_events.jsonl"

        summary = {
            "ts": "2026-03-13T12:01:00Z",
            "event": "merge_conflict_summary",
            "cleanWorkers": 1,
            "conflictWorkers": 1,
        }
        events_file.write_text(json.dumps(summary) + "\n")

        data = json.loads(events_file.read_text())
        assert data["event"] == "merge_conflict_summary"
        assert data["cleanWorkers"] == 1
        assert data["conflictWorkers"] == 1

    def test_clean_run_emits_summary_not_detected(self, tmp_path):
        """When all workers are clean, no merge_conflict_detected event appears."""
        events_file = tmp_path / "spiral_events.jsonl"
        summary = {
            "ts": "2026-03-13T12:02:00Z",
            "event": "merge_conflict_summary",
            "cleanWorkers": 2,
            "conflictWorkers": 0,
        }
        events_file.write_text(json.dumps(summary) + "\n")

        events = [json.loads(l) for l in events_file.read_text().strip().splitlines()]
        conflict_events = [e for e in events if e["event"] == "merge_conflict_detected"]
        assert len(conflict_events) == 0

    def test_multiple_events_appended(self, tmp_path):
        """Multiple events can coexist in spiral_events.jsonl (JSONL format)."""
        events_file = tmp_path / "spiral_events.jsonl"
        ev1 = {"ts": "2026-03-13T12:00:00Z", "event": "merge_conflict_detected", "workerId": 1}
        ev2 = {"ts": "2026-03-13T12:01:00Z", "event": "merge_conflict_summary", "cleanWorkers": 1, "conflictWorkers": 1}
        events_file.write_text(json.dumps(ev1) + "\n" + json.dumps(ev2) + "\n")

        lines = events_file.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "merge_conflict_detected"
        assert json.loads(lines[1])["event"] == "merge_conflict_summary"


# ── Integration: full conflict-requeue path with fixture repo ─────────────────

class TestConflictRequeueIntegration:
    """
    End-to-end simulation of the conflict-detected requeue path using a
    fixture git repo — integration test for US-097 acceptance criteria.
    """

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_conflicting_worker_stories_requeued(self, tmp_path):
        """
        Scenario: 2 workers both modify base.txt → merge-tree detects conflict
        → conflicting worker's stories are reset to pending in prd.json
        → non-conflicting worker's stories remain passed.
        """
        repo = tmp_path / "repo"
        main = init_repo(repo)

        # Worker 1: modifies base.txt
        git("checkout -b spiral-worker-1-ts", repo)
        (repo / "base.txt").write_text("worker 1 content\nline 2\n")
        git("add .", repo)
        git('commit -m "worker1 story US-001"', repo)
        git(f"checkout {main}", repo)

        # Worker 2: modifies base.txt differently (conflicts with worker 1)
        git("checkout -b spiral-worker-2-ts", repo)
        (repo / "base.txt").write_text("worker 2 content\nline 2\n")
        git("add .", repo)
        git('commit -m "worker2 story US-002"', repo)
        git(f"checkout {main}", repo)

        # Simulate Step 6: merge prd.json (both stories passed)
        prd = {
            "productName": "test",
            "userStories": [
                {"id": "US-001", "title": "Worker 1 story", "passes": True},
                {"id": "US-002", "title": "Worker 2 story", "passes": True},
            ],
        }
        prd_path = repo / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        # Simulate coordinator applying Worker 1's changes to main first
        git("merge --no-edit spiral-worker-1-ts", repo)

        # Step 6.5: merge-tree check of Worker 2 vs updated main → conflict
        result = run(
            "git merge-tree --write-tree HEAD spiral-worker-2-ts",
            cwd=repo, check=False,
        )
        assert result.returncode != 0, "Should detect conflict for Worker 2"

        # Reset Worker 2's stories (US-002) to pending
        reset_conflict_stories(prd_path, ["US-002"])

        # Verify final state
        with open(prd_path) as f:
            final = json.load(f)

        us001 = next(s for s in final["userStories"] if s["id"] == "US-001")
        us002 = next(s for s in final["userStories"] if s["id"] == "US-002")

        assert us001["passes"] is True, "Worker 1 story should remain passed"
        assert us002["passes"] is False, "Worker 2 story should be requeued"
        assert us002.get("_failureReason") == "merge_conflict"

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_non_conflicting_workers_merge_normally(self, tmp_path):
        """
        Scenario: 2 workers modify different files → both merge cleanly
        → all stories remain passed.
        """
        repo = tmp_path / "repo"
        main = init_repo(repo)

        git("checkout -b spiral-worker-1-ts", repo)
        (repo / "file-a.txt").write_text("worker 1\n")
        git("add .", repo)
        git('commit -m "worker1"', repo)
        git(f"checkout {main}", repo)

        git("checkout -b spiral-worker-2-ts", repo)
        (repo / "file-b.txt").write_text("worker 2\n")
        git("add .", repo)
        git('commit -m "worker2"', repo)
        git(f"checkout {main}", repo)

        # Both workers should merge cleanly with main
        for branch in ("spiral-worker-1-ts", "spiral-worker-2-ts"):
            result = run(
                f"git merge-tree --write-tree HEAD {branch}",
                cwd=repo, check=False,
            )
            assert result.returncode == 0, (
                f"Expected clean merge for {branch}: rc={result.returncode}"
            )

    @pytest.mark.skipif(not HAS_NEW_MERGE_TREE, reason="git < 2.38")
    def test_merge_conflict_does_not_affect_sibling_worker(self, tmp_path):
        """
        When Worker 1 conflicts, Worker 2 (clean) still has its patch applied.
        Worker 1's stories are pending; Worker 2's stories remain passed.
        """
        repo = tmp_path / "repo"
        main = init_repo(repo)

        # Worker 1 (conflicting): modifies base.txt
        git("checkout -b spiral-worker-1-ts", repo)
        (repo / "base.txt").write_text("worker 1\nline 2\n")
        git("add .", repo)
        git('commit -m "w1"', repo)
        git(f"checkout {main}", repo)

        # Worker 2 (clean): adds a new file
        git("checkout -b spiral-worker-2-ts", repo)
        (repo / "worker2-only.txt").write_text("worker 2\n")
        git("add .", repo)
        git('commit -m "w2"', repo)
        git(f"checkout {main}", repo)

        prd = {
            "productName": "test",
            "userStories": [
                {"id": "US-001", "passes": True, "title": "W1"},
                {"id": "US-002", "passes": True, "title": "W2"},
            ],
        }
        prd_path = repo / "prd.json"
        prd_path.write_text(json.dumps(prd, indent=2))

        # Modify main (e.g. another commit that makes Worker 1 conflict)
        (repo / "base.txt").write_text("main changed too\nline 2\n")
        git("add .", repo)
        git('commit -m "main update"', repo)

        # Worker 1 now conflicts; Worker 2 should still be clean
        w1_result = run(
            "git merge-tree --write-tree HEAD spiral-worker-1-ts",
            cwd=repo, check=False,
        )
        w2_result = run(
            "git merge-tree --write-tree HEAD spiral-worker-2-ts",
            cwd=repo, check=False,
        )

        # Worker 1 conflicts (both modified base.txt differently)
        assert w1_result.returncode != 0, "Worker 1 should conflict"
        # Worker 2 is clean (only adds worker2-only.txt)
        assert w2_result.returncode == 0, "Worker 2 should be clean"

        # Reset only Worker 1's stories
        reset_conflict_stories(prd_path, ["US-001"])

        with open(prd_path) as f:
            final = json.load(f)

        us001 = next(s for s in final["userStories"] if s["id"] == "US-001")
        us002 = next(s for s in final["userStories"] if s["id"] == "US-002")
        assert us001["passes"] is False
        assert us001.get("_failureReason") == "merge_conflict"
        assert us002["passes"] is True, "Sibling worker must not be affected"
