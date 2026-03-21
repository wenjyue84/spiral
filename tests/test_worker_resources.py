"""Integration tests for worker resource usage metrics (US-647).

Verifies read_worker_resources() and append_history() against
.spiral/worker_heartbeats.json / worker-resources-history.json.
"""

import json
import os

import pytest

from lib.worker_resources import append_history, read_worker_resources


@pytest.fixture()
def sd(tmp_path: pytest.TempPathFactory) -> str:
    return str(tmp_path)


def _hb(spiral_dir: str, data: dict) -> None:  # type: ignore[type-arg]
    with open(os.path.join(spiral_dir, "worker_heartbeats.json"), "w") as f:
        json.dump(data, f)


def test_missing_heartbeats_returns_empty(sd: str) -> None:
    assert read_worker_resources(sd) == []


def test_malformed_json_returns_empty(sd: str) -> None:
    with open(os.path.join(sd, "worker_heartbeats.json"), "w") as f:
        f.write("not-json")
    assert read_worker_resources(sd) == []


def test_reads_two_workers(sd: str) -> None:
    _hb(
        sd,
        {
            "worker-1": {"memory_peak_mb": 480, "avg_cpu_percent": 65, "stories_completed": 3, "uptime_seconds": 340},
            "worker-2": {"memory_peak_mb": 512, "avg_cpu_percent": 72, "stories_completed": 2, "uptime_seconds": 290},
        },
    )
    result = read_worker_resources(sd)
    assert len(result) == 2
    assert {w["worker_id"] for w in result} == {"worker-1", "worker-2"}


def test_metrics_non_zero_for_active_worker(sd: str) -> None:
    _hb(sd, {"worker-1": {"memory_peak_mb": 480, "avg_cpu_percent": 65, "stories_completed": 3, "uptime_seconds": 340}})
    w = read_worker_resources(sd)[0]
    assert w["memory_peak_mb"] > 0
    assert w["avg_cpu_percent"] > 0
    assert w["stories_completed"] == 3


def test_history_created_and_accumulates(sd: str) -> None:
    m1 = [
        {
            "worker_id": "worker-1",
            "memory_peak_mb": 480.0,
            "avg_cpu_percent": 65.0,
            "stories_completed": 3,
            "uptime_seconds": 340,
        }
    ]
    m2 = [
        {
            "worker_id": "worker-1",
            "memory_peak_mb": 520.0,
            "avg_cpu_percent": 70.0,
            "stories_completed": 4,
            "uptime_seconds": 400,
        }
    ]
    append_history(sd, m1)
    append_history(sd, m2)
    hist_file = os.path.join(sd, "worker-resources-history.json")
    assert os.path.exists(hist_file)
    with open(hist_file) as f:
        hist = json.load(f)
    assert len(hist) == 2
    assert "timestamp" in hist[0]
    assert hist[1]["workers"][0]["stories_completed"] == 4
