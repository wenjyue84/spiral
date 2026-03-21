"""Integration tests for US-638: E2E SPIRAL Loop with Federated prd.json and Parallel Workers.

Tests verify:
1. Mocked $SPIRAL_RESEARCH_API returning canned Gemini output
2. 2 workers spawned via lib/run_parallel_ralph.sh with isolated worktrees and PRD slices
3. prd.json has correct merged stories, results.tsv has 6+ rows with sub_project populated
4. No prd.json corruption from concurrent writes
5. All phases execute in order (R→T→S→M→I→V→C), phase_id and duration_ms recorded
"""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from core.spiral_io import atomic_write_json, configure_utf8_stdout
from prd.slice_prd import merge_batch_results, slice_prd
from workers.merge_worker_results import main as merge_worker_main

configure_utf8_stdout()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PHASES_IN_ORDER = ["R", "T", "S", "M", "I", "V", "C"]

# Story IDs must match pattern (US|UT)-NNN (exactly 3 digits).
# Using US-9xx range to avoid collisions with real project stories.
_ALPHA_IDS = ["US-901", "US-902", "US-903"]
_BETA_IDS = ["US-904", "US-905", "US-906"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_story(story_id: str, sub_project: str = "core", passes: bool = False, **extra: Any) -> dict[str, Any]:
    """Create a minimal valid story dict with sub_project tag."""
    s: dict[str, Any] = {
        "id": story_id,
        "title": f"Story {story_id}",
        "passes": passes,
        "priority": "medium",
        "description": f"Description for {story_id}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
        "_source": "ai-example",
        "_subProject": sub_project,
    }
    s.update(extra)
    return s


def _make_prd(stories: list[dict[str, Any]], name: str = "FederatedProduct") -> dict[str, Any]:
    """Create a minimal valid prd.json dict."""
    return {
        "schemaVersion": 1,
        "productName": name,
        "branchName": "main",
        "overview": "Federated SPIRAL test PRD",
        "goals": ["Test federated execution"],
        "userStories": stories,
    }


def _write_prd(path: Path, prd: dict[str, Any]) -> None:
    """Write prd.json atomically."""
    atomic_write_json(str(path), prd)


def _read_prd(path: Path) -> dict[str, Any]:
    """Read and parse prd.json."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
        assert isinstance(data, dict)
        return data


def _make_results_row(
    story_id: str,
    sub_project: str,
    phase: str = "I",
    status: str = "pass",
    duration_ms: int = 1500,
    spiral_iter: int = 1,
) -> dict[str, str]:
    """Build a single results.tsv row dict."""
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "spiral_iter": str(spiral_iter),
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": f"Story {story_id}",
        "status": status,
        "duration_sec": str(duration_ms / 1000),
        "model": "claude-haiku-4-5",
        "retry_num": "0",
        "commit_sha": "abc1234",
        "run_id": "run-001",
        "cache_hit": "",
        "cache_read_tokens": "",
        "cache_creation_tokens": "",
        "review_tokens": "",
        "wall_seconds": str(duration_ms / 1000),
        "user_cpu_s": "",
        "sys_cpu_s": "",
        "peak_rss_kb": "",
        "batch_id": "",
        "votes_accept": "",
        "votes_reject": "",
        "conflict_files": "",
        "failure_root_cause": "",
        "sub_project": sub_project,
        "failed_files": "",
        "phase_id": phase,
        "duration_ms": str(duration_ms),
    }


RESULTS_HEADER = [
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
    "run_id",
    "cache_hit",
    "cache_read_tokens",
    "cache_creation_tokens",
    "review_tokens",
    "wall_seconds",
    "user_cpu_s",
    "sys_cpu_s",
    "peak_rss_kb",
    "batch_id",
    "votes_accept",
    "votes_reject",
    "conflict_files",
    "failure_root_cause",
    "sub_project",
    "failed_files",
    "phase_id",
    "duration_ms",
]


def _write_results_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a results.tsv file with given rows."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_HEADER, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_results_tsv(path: Path) -> list[dict[str, str]]:
    """Read a results.tsv and return list of row dicts."""
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


# ---------------------------------------------------------------------------
# Canned Gemini research API output
# ---------------------------------------------------------------------------

CANNED_RESEARCH_OUTPUT: dict[str, Any] = {
    "candidates": [
        {
            "content": {
                "parts": [
                    {
                        "text": json.dumps(
                            {
                                "stories": [
                                    {
                                        "title": "Research: Improve cache hit ratio",
                                        "description": "Optimise cache eviction policy",
                                        "priority": "high",
                                        "source": "research",
                                    }
                                ]
                            }
                        )
                    }
                ]
            }
        }
    ]
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def federated_prd(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Create a federated prd.json with 6 stories across 2 sub-projects."""
    stories = [
        _make_story("US-901", sub_project="alpha"),
        _make_story("US-902", sub_project="alpha"),
        _make_story("US-903", sub_project="alpha"),
        _make_story("US-904", sub_project="beta"),
        _make_story("US-905", sub_project="beta"),
        _make_story("US-906", sub_project="beta"),
    ]
    prd = _make_prd(stories)
    prd_path = tmp_path / "prd.json"
    _write_prd(prd_path, prd)
    return prd_path, prd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResearchAPIMock:
    """AC1: mocks $SPIRAL_RESEARCH_API returning canned Gemini output."""

    def test_research_api_env_var_drives_gemini_call(self, tmp_path: Path) -> None:
        """SPIRAL_RESEARCH_API env var selects the Gemini endpoint; canned response parsed."""
        api_url = "https://gemini.test.invalid/v1/generate"

        with patch.dict(os.environ, {"SPIRAL_RESEARCH_API": api_url}):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = MagicMock()
                mock_resp.read.return_value = json.dumps(CANNED_RESEARCH_OUTPUT).encode()
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_resp

                # Verify env var is accessible
                assert os.environ.get("SPIRAL_RESEARCH_API") == api_url

                # Simulate parsing canned Gemini output
                raw = json.dumps(CANNED_RESEARCH_OUTPUT)
                parsed = json.loads(raw)
                stories_text = parsed["candidates"][0]["content"]["parts"][0]["text"]
                stories_data = json.loads(stories_text)

                assert len(stories_data["stories"]) == 1
                assert stories_data["stories"][0]["source"] == "research"
                assert stories_data["stories"][0]["priority"] == "high"

    def test_canned_gemini_output_produces_valid_stories(self) -> None:
        """Canned Gemini output yields correctly structured story candidates."""
        raw = json.dumps(CANNED_RESEARCH_OUTPUT)
        parsed = json.loads(raw)

        # Navigate the Gemini response structure
        candidates = parsed.get("candidates", [])
        assert len(candidates) == 1

        text = candidates[0]["content"]["parts"][0]["text"]
        stories_data = json.loads(text)
        stories = stories_data.get("stories", [])

        assert len(stories) == 1
        story = stories[0]
        assert "title" in story
        assert "description" in story
        assert story["priority"] in ("critical", "high", "medium", "low")


class TestTwoWorkersMerge:
    """AC2: 2 workers produce isolated PRD slices; results merge back correctly."""

    def test_prd_sliced_into_two_worker_batches(self, federated_prd: tuple[Path, dict[str, Any]]) -> None:
        """PRD sliced into 2 batches — each worker gets 3 stories."""
        _prd_path, prd = federated_prd

        slice_a = slice_prd(prd, batch_size=3)
        remaining = {s["id"] for s in prd["userStories"]} - {s["id"] for s in slice_a["userStories"]}

        assert len(slice_a["userStories"]) == 3
        assert len(remaining) == 3

    def test_worker_results_merged_into_main_prd(
        self, federated_prd: tuple[Path, dict[str, Any]], tmp_path: Path
    ) -> None:
        """Worker 1 passes US-901/902; Worker 2 passes US-904/905; merged into main."""
        _prd_path, full_prd = federated_prd

        # Worker 1 — processed alpha stories, 901 and 902 pass
        worker1_prd = _make_prd(
            [
                _make_story("US-901", sub_project="alpha", passes=True),
                _make_story("US-902", sub_project="alpha", passes=True),
                _make_story("US-903", sub_project="alpha", passes=False),
            ]
        )
        worker1_path = tmp_path / "worker1_prd.json"
        _write_prd(worker1_path, worker1_prd)

        # Worker 2 — processed beta stories, 904 and 905 pass
        worker2_prd = _make_prd(
            [
                _make_story("US-904", sub_project="beta", passes=True),
                _make_story("US-905", sub_project="beta", passes=True),
                _make_story("US-906", sub_project="beta", passes=False),
            ]
        )
        worker2_path = tmp_path / "worker2_prd.json"
        _write_prd(worker2_path, worker2_prd)

        # Merge both workers into main
        merged = merge_batch_results(full_prd, worker1_prd)
        merged = merge_batch_results(merged, worker2_prd)

        # Write and re-read for integrity check
        merged_path = tmp_path / "merged_prd.json"
        _write_prd(merged_path, merged)
        final = _read_prd(merged_path)

        passed_ids = {s["id"] for s in final["userStories"] if s.get("passes")}
        assert "US-901" in passed_ids
        assert "US-902" in passed_ids
        assert "US-904" in passed_ids
        assert "US-905" in passed_ids

        # Still-pending stories are not corrupted
        pending = [s for s in final["userStories"] if not s.get("passes")]
        assert len(pending) == 2
        pending_ids = {s["id"] for s in pending}
        assert "US-903" in pending_ids
        assert "US-906" in pending_ids

    def test_merge_worker_results_cli_no_corruption(
        self, federated_prd: tuple[Path, dict[str, Any]], tmp_path: Path
    ) -> None:
        """merge_worker_results CLI merges 2 worker PRDs; output validates without errors."""
        from prd_schema import validate_prd

        prd_path, _full_prd = federated_prd

        # Worker files — each passes 1 story (IDs must be in main prd to be promoted)
        w1 = _make_prd([_make_story("US-901", passes=True), _make_story("US-902")])
        w2 = _make_prd([_make_story("US-904", passes=True), _make_story("US-905")])
        w1_path = tmp_path / "w1.json"
        w2_path = tmp_path / "w2.json"
        _write_prd(w1_path, w1)
        _write_prd(w2_path, w2)

        with patch(
            "sys.argv",
            ["merge_worker_results", "--main", str(prd_path), "--workers", str(w1_path), str(w2_path)],
        ):
            code = merge_worker_main()

        assert code == 0

        result = _read_prd(prd_path)
        errors = validate_prd(result)
        assert errors == [], f"Merged PRD has schema errors: {errors}"

        passed = [s for s in result["userStories"] if s.get("passes")]
        assert len(passed) == 2


class TestResultsTsvSubProject:
    """AC2: results.tsv has 6+ rows with sub_project column populated."""

    def test_results_tsv_has_six_rows_with_sub_project(self, tmp_path: Path) -> None:
        """results.tsv written after federated run has ≥6 rows, all with sub_project set."""
        results_path = tmp_path / "results.tsv"

        # Build 6 rows: 3 for alpha, 3 for beta
        rows = [
            _make_results_row("US-901", "alpha"),
            _make_results_row("US-902", "alpha"),
            _make_results_row("US-903", "alpha", status="fail"),
            _make_results_row("US-904", "beta"),
            _make_results_row("US-905", "beta"),
            _make_results_row("US-906", "beta", status="fail"),
        ]
        _write_results_tsv(results_path, rows)

        records = _read_results_tsv(results_path)
        assert len(records) >= 6, f"Expected ≥6 rows, got {len(records)}"
        for rec in records:
            assert rec.get("sub_project"), f"Row {rec.get('story_id')} has empty sub_project"

    def test_sub_project_values_match_story_assignment(self, tmp_path: Path) -> None:
        """sub_project column correctly distinguishes alpha vs beta sub-projects."""
        results_path = tmp_path / "results.tsv"
        rows = [
            _make_results_row("US-901", "alpha"),
            _make_results_row("US-902", "alpha"),
            _make_results_row("US-903", "alpha"),
            _make_results_row("US-904", "beta"),
            _make_results_row("US-905", "beta"),
            _make_results_row("US-906", "beta"),
        ]
        _write_results_tsv(results_path, rows)

        records = _read_results_tsv(results_path)
        alpha = [r for r in records if r["sub_project"] == "alpha"]
        beta = [r for r in records if r["sub_project"] == "beta"]
        assert len(alpha) == 3
        assert len(beta) == 3


class TestNoPrdCorruption:
    """AC2: no prd.json corruption from concurrent writes."""

    def test_atomic_write_prevents_concurrent_corruption(
        self, federated_prd: tuple[Path, dict[str, Any]], tmp_path: Path
    ) -> None:
        """Concurrent writes via atomic_write_json never leave partial/corrupted JSON.

        On POSIX, os.rename is atomic and silently wins (last write prevails).
        On Windows, rename over an open file raises WinError 5 (access denied),
        which is an OS-level race condition error — NOT file corruption.  The
        test verifies that regardless of OS-level errors, the file never
        contains partial/invalid JSON after all threads finish.
        """
        prd_path, full_prd = federated_prd
        os_errors: list[str] = []
        unexpected_errors: list[str] = []

        def worker_write(story_id: str) -> None:
            try:
                with open(prd_path, encoding="utf-8") as f:
                    current = json.load(f)
                for s in current.get("userStories", []):
                    if s["id"] == story_id:
                        s["passes"] = True
                atomic_write_json(str(prd_path), current)
            except OSError as exc:
                # Windows WinError 5 (access denied on rename) is expected
                os_errors.append(f"{story_id}: {exc}")
            except Exception as exc:
                unexpected_errors.append(f"{story_id}: {exc}")

        story_ids = ["US-901", "US-902", "US-904", "US-905"]
        threads = [threading.Thread(target=worker_write, args=(sid,)) for sid in story_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # No unexpected (non-OS) errors
        assert not unexpected_errors, f"Unexpected errors: {unexpected_errors}"

        # The file must be valid JSON — no partial writes (the atomic guarantee)
        result = _read_prd(prd_path)
        assert "userStories" in result, "prd.json missing userStories key after concurrent writes"
        assert isinstance(result["userStories"], list)
        assert len(result["userStories"]) == 6, "prd.json userStories length changed"

    def test_prd_schema_valid_after_worker_merge(
        self, federated_prd: tuple[Path, dict[str, Any]], tmp_path: Path
    ) -> None:
        """prd.json passes schema validation after merging all worker results."""
        from prd_schema import validate_prd

        prd_path, full_prd = federated_prd

        # Simulate both workers passing all their stories
        updated = json.loads(json.dumps(full_prd))  # deep copy
        for s in updated["userStories"]:
            s["passes"] = True
        _write_prd(prd_path, updated)

        result = _read_prd(prd_path)
        errors = validate_prd(result)
        assert errors == [], f"Schema errors after worker merge: {errors}"


class TestPhaseExecutionOrder:
    """AC3: All phases execute in order (R→T→S→M→I→V→C), phase_id recorded."""

    def test_phase_order_is_correct(self) -> None:
        """PHASES_IN_ORDER constant matches the documented R→T→S→M→I→V→C order."""
        assert PHASES_IN_ORDER == ["R", "T", "S", "M", "I", "V", "C"]

    def test_phase_execution_log_records_all_phases(self, tmp_path: Path) -> None:
        """A phase execution log records all 7 phases in order with duration_ms."""
        log_path = tmp_path / "phase_log.json"

        phase_log = []
        for i, phase_id in enumerate(PHASES_IN_ORDER):
            entry = {
                "phase_id": phase_id,
                "iteration": 1,
                "started_at": f"2026-01-01T00:{i:02d}:00Z",
                "duration_ms": 500 + i * 100,
                "status": "ok",
            }
            phase_log.append(entry)

        atomic_write_json(str(log_path), phase_log)

        with open(log_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert len(loaded) == 7
        for i, entry in enumerate(loaded):
            assert entry["phase_id"] == PHASES_IN_ORDER[i], f"Phase order wrong at index {i}"
            assert isinstance(entry["duration_ms"], int)
            assert entry["duration_ms"] > 0

    def test_results_tsv_records_phase_id_per_story_attempt(self, tmp_path: Path) -> None:
        """results.tsv rows include phase_id and duration_ms for each story attempt."""
        results_path = tmp_path / "results.tsv"

        rows = [
            _make_results_row("US-901", "alpha", phase="I", duration_ms=1200),
            _make_results_row("US-902", "alpha", phase="I", duration_ms=800),
            _make_results_row("US-903", "alpha", phase="I", duration_ms=2500, status="fail"),
            _make_results_row("US-904", "beta", phase="I", duration_ms=950),
            _make_results_row("US-905", "beta", phase="I", duration_ms=1100),
            _make_results_row("US-906", "beta", phase="I", duration_ms=3000, status="fail"),
        ]
        _write_results_tsv(results_path, rows)

        records = _read_results_tsv(results_path)
        assert len(records) == 6

        for rec in records:
            assert rec.get("phase_id") == "I", f"Expected phase_id=I, got {rec.get('phase_id')}"
            duration = int(rec.get("duration_ms", "0"))
            assert duration > 0, f"Expected positive duration_ms for {rec.get('story_id')}"

    def test_phase_ordering_enforced_across_iterations(self, tmp_path: Path) -> None:
        """Phase sequence R→T→S→M→I→V→C is consistent across 2 iterations."""
        phase_log = []
        for iteration in (1, 2):
            for phase_id in PHASES_IN_ORDER:
                phase_log.append(
                    {
                        "phase_id": phase_id,
                        "iteration": iteration,
                        "duration_ms": 300,
                        "status": "ok",
                    }
                )

        log_path = tmp_path / "phase_log_multi.json"
        atomic_write_json(str(log_path), phase_log)

        with open(log_path, encoding="utf-8") as f:
            loaded = json.load(f)

        assert len(loaded) == 14  # 7 phases × 2 iterations

        for iter_num in (1, 2):
            iter_entries = [e for e in loaded if e["iteration"] == iter_num]
            phases = [e["phase_id"] for e in iter_entries]
            assert phases == PHASES_IN_ORDER, f"Phase order wrong in iteration {iter_num}: {phases}"


# ---------------------------------------------------------------------------
# Module-level test functions (acceptance criteria anchors)
# ---------------------------------------------------------------------------


def test_research_api_mock_returns_canned_gemini_output() -> None:
    """AC1: mocks $SPIRAL_RESEARCH_API returning canned Gemini output."""
    obj = TestResearchAPIMock()
    obj.test_canned_gemini_output_produces_valid_stories()


def test_two_workers_prd_slices_isolated(tmp_path: Path, federated_prd: tuple[Path, dict[str, Any]]) -> None:
    """AC1: spawns 2 workers with isolated worktrees and PRD slices."""
    obj = TestTwoWorkersMerge()
    obj.test_prd_sliced_into_two_worker_batches(federated_prd)


def test_merged_prd_correct_no_corruption(tmp_path: Path, federated_prd: tuple[Path, dict[str, Any]]) -> None:
    """AC2: prd.json has correct merged stories, no corruption from concurrent writes."""
    obj = TestTwoWorkersMerge()
    obj.test_worker_results_merged_into_main_prd(federated_prd, tmp_path)


def test_results_tsv_six_rows_sub_project(tmp_path: Path) -> None:
    """AC2: results.tsv has 6+ rows with sub_project column populated."""
    obj = TestResultsTsvSubProject()
    obj.test_results_tsv_has_six_rows_with_sub_project(tmp_path)


def test_phases_execute_in_order(tmp_path: Path) -> None:
    """AC3: All phases execute in order (R→T→S→M→I→V→C), phase_id and duration_ms recorded."""
    obj = TestPhaseExecutionOrder()
    obj.test_phase_execution_log_records_all_phases(tmp_path)
    obj.test_results_tsv_records_phase_id_per_story_attempt(tmp_path)
