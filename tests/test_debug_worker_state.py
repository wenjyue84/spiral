"""Integration tests for debug_worker_state (US-1066).

Verifies:
- Output JSON schema (workers + diagnostics keys, all required worker fields)
- Worker data is consistent with actual filesystem state
- Detached HEAD detection is reported in diagnostics
- Empty / missing workers dir handled gracefully
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from debug_worker_state import dump_worker_state

REQUIRED_WORKER_KEYS = {
    "worker_id",
    "pid",
    "worktree_path",
    "current_story_id",
    "phase",
    "memory_mb",
    "prd_slice_size",
}


def _write_heartbeat(worker_dir: Path, data: dict[str, Any]) -> None:
    with open(worker_dir / ".heartbeat", "w", encoding="utf-8") as f:
        json.dump(data, f)


def _write_prd(worker_dir: Path, stories: list[dict[str, Any]]) -> None:
    prd: dict[str, Any] = {"userStories": stories}
    with open(worker_dir / "prd.json", "w", encoding="utf-8") as f:
        json.dump(prd, f)


@pytest.fixture
def tmp_workers(tmp_path: Path) -> Path:
    return tmp_path / ".spiral-workers"


def test_output_schema_has_required_keys(tmp_workers: Path) -> None:
    """dump_worker_state returns dict with 'workers' and 'diagnostics' keys."""
    tmp_workers.mkdir()
    result = dump_worker_state(str(tmp_workers))
    assert "workers" in result
    assert "diagnostics" in result
    assert isinstance(result["workers"], list)
    assert isinstance(result["diagnostics"], list)


def test_no_workers_dir_returns_empty(tmp_path: Path) -> None:
    """Missing workers dir returns empty workers and diagnostics lists."""
    result = dump_worker_state(str(tmp_path / "nonexistent"))
    assert result == {"workers": [], "diagnostics": []}


def test_single_worker_all_fields_present(tmp_workers: Path) -> None:
    """Single worker entry includes all required schema fields."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)
    _write_heartbeat(
        w1,
        {"pid": 1234, "storyId": "US-42", "phase": "I", "memMb": 512, "ts": time.time()},
    )

    result = dump_worker_state(str(tmp_workers))
    assert len(result["workers"]) == 1
    worker = result["workers"][0]
    assert REQUIRED_WORKER_KEYS == set(worker.keys())


def test_worker_data_consistent_with_filesystem(tmp_workers: Path) -> None:
    """Worker fields reflect actual heartbeat data and worktree path on disk."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)
    _write_heartbeat(
        w1,
        {"pid": 9999, "storyId": "US-100", "phase": "V", "memMb": 256, "ts": time.time()},
    )
    _write_prd(w1, [{"id": "US-100", "passes": False}, {"id": "US-101", "passes": True}])

    result = dump_worker_state(str(tmp_workers))
    worker = result["workers"][0]

    assert worker["worker_id"] == "worker-1"
    assert worker["pid"] == 9999
    assert worker["current_story_id"] == "US-100"
    assert worker["phase"] == "V"
    assert worker["memory_mb"] == 256
    # prd_slice_size counts only pending (passes=False) stories
    assert worker["prd_slice_size"] == 1
    # worktree_path is an absolute path pointing to worker dir
    assert os.path.isabs(worker["worktree_path"])
    assert Path(worker["worktree_path"]).name == "worker-1"


def test_prd_slice_size_counts_pending_stories(tmp_workers: Path) -> None:
    """prd_slice_size counts stories where passes != True."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)
    _write_heartbeat(w1, {"ts": time.time()})
    stories: list[dict[str, Any]] = [
        {"id": "US-1", "passes": True},
        {"id": "US-2", "passes": False},
        {"id": "US-3"},  # missing passes field
        {"id": "US-4", "passes": False},
    ]
    _write_prd(w1, stories)

    result = dump_worker_state(str(tmp_workers))
    assert result["workers"][0]["prd_slice_size"] == 3


def test_missing_heartbeat_uses_defaults(tmp_workers: Path) -> None:
    """Worker dir without .heartbeat file returns zeros/unknown defaults."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)

    result = dump_worker_state(str(tmp_workers))
    assert len(result["workers"]) == 1
    worker = result["workers"][0]
    assert worker["pid"] == 0
    assert worker["current_story_id"] == "unknown"
    assert worker["phase"] == "unknown"
    assert worker["memory_mb"] == 0


def test_detached_head_reported_in_diagnostics(tmp_workers: Path) -> None:
    """Detached HEAD state for a worker appears in diagnostics section."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)
    _write_heartbeat(w1, {"ts": time.time(), "storyId": "US-77"})

    # Simulate detached HEAD: symbolic-ref returns non-zero
    def _mock_run(cmd: list[str], capture_output: bool = False, text: bool = False, timeout: int = 10) -> Any:
        mock = type("R", (), {"returncode": 128, "stdout": "abc1234\n", "stderr": ""})()
        if "symbolic-ref" in cmd:
            mock.returncode = 128
        elif "rev-parse" in cmd:
            mock.returncode = 0
            mock.stdout = "abc1234\n"
        return mock

    with patch("debug_worker_state.subprocess.run", side_effect=_mock_run):
        result = dump_worker_state(str(tmp_workers))

    assert len(result["diagnostics"]) == 1
    diag = result["diagnostics"][0]
    assert diag["worker_id"] == "worker-1"
    assert diag["issue"] == "detached_head"
    assert "detached" in diag["detail"].lower()


def test_multiple_workers_sorted_order(tmp_workers: Path) -> None:
    """Multiple workers are returned in sorted order by worker_id."""
    for i in [3, 1, 2]:
        w = tmp_workers / f"worker-{i}"
        w.mkdir(parents=True)
        _write_heartbeat(w, {"ts": time.time(), "storyId": f"US-{i}"})

    result = dump_worker_state(str(tmp_workers))
    ids = [w["worker_id"] for w in result["workers"]]
    assert ids == ["worker-1", "worker-2", "worker-3"]


def test_output_is_json_serializable(tmp_workers: Path) -> None:
    """Output can be round-tripped through JSON serialization."""
    w1 = tmp_workers / "worker-1"
    w1.mkdir(parents=True)
    _write_heartbeat(w1, {"pid": 42, "storyId": "US-5", "phase": "M", "memMb": 100, "ts": time.time()})

    result = dump_worker_state(str(tmp_workers))
    serialized = json.dumps(result)
    parsed: dict[str, Any] = json.loads(serialized)
    assert parsed["workers"][0]["worker_id"] == "worker-1"
