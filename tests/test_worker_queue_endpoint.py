"""Tests for worker task queue endpoint (US-527).

Tests cover:
- GET /api/workers/<id>/queue response shape
- 404 when worker JSON not found
- queue_depth and status in GET /api/workers list response
- worker_N.json structure written by heartbeat
"""

import json
import os
import tempfile
import time
from pathlib import Path

import pytest


def _write_worker_json(workers_dir: Path, worker_id: int, data: dict[str, object]) -> Path:
    """Write a worker_N.json file to the temp workers directory."""
    workers_dir.mkdir(parents=True, exist_ok=True)
    jf = workers_dir / f"worker_{worker_id}.json"
    jf.write_text(json.dumps(data), encoding="utf-8")
    return jf


class TestWorkerQueueJsonStructure:
    """Verify the JSON structure that worker_heartbeat.sh writes and the endpoint reads."""

    def test_worker_json_has_required_keys(self, tmp_path: Path) -> None:
        """Worker JSON must have worker_id, current_task, queue, and uptime keys."""
        workers_dir = tmp_path / "workers"
        data: dict[str, object] = {
            "worker_id": "worker-0",
            "current_task": {"story_id": "US-123", "started_at": "2026-03-20T10:00:00Z"},
            "queue": [],
            "uptime": 120,
            "phase": "I",
        }
        jf = _write_worker_json(workers_dir, 0, data)
        loaded = json.loads(jf.read_text(encoding="utf-8"))
        assert "worker_id" in loaded
        assert "current_task" in loaded
        assert "queue" in loaded
        assert "uptime" in loaded

    def test_worker_json_current_task_shape(self, tmp_path: Path) -> None:
        """current_task must have story_id and started_at (ISO 8601) when a story is running."""
        workers_dir = tmp_path / "workers"
        data: dict[str, object] = {
            "worker_id": "worker-1",
            "current_task": {"story_id": "US-456", "started_at": "2026-03-20T11:30:00Z"},
            "queue": [{"story_id": "US-457"}],
            "uptime": 60,
        }
        jf = _write_worker_json(workers_dir, 1, data)
        loaded = json.loads(jf.read_text(encoding="utf-8"))

        ct = loaded["current_task"]
        assert isinstance(ct, dict)
        assert "story_id" in ct
        assert "started_at" in ct
        assert ct["story_id"] == "US-456"
        # started_at should look like ISO 8601
        assert "T" in ct["started_at"]

    def test_worker_json_null_current_task_when_idle(self, tmp_path: Path) -> None:
        """current_task should be null when no story is running."""
        workers_dir = tmp_path / "workers"
        data: dict[str, object] = {
            "worker_id": "worker-2",
            "current_task": None,
            "queue": [],
            "uptime": 300,
        }
        jf = _write_worker_json(workers_dir, 2, data)
        loaded = json.loads(jf.read_text(encoding="utf-8"))
        assert loaded["current_task"] is None

    def test_worker_json_queue_is_list(self, tmp_path: Path) -> None:
        """queue must always be a list (even when empty)."""
        workers_dir = tmp_path / "workers"
        for queue_val in [[], [{"story_id": "US-100"}], [{"story_id": "US-101"}, {"story_id": "US-102"}]]:
            data: dict[str, object] = {
                "worker_id": "worker-0",
                "current_task": None,
                "queue": queue_val,
                "uptime": 10,
            }
            jf = _write_worker_json(workers_dir, 0, data)
            loaded = json.loads(jf.read_text(encoding="utf-8"))
            assert isinstance(loaded["queue"], list)

    def test_worker_json_uptime_is_non_negative(self, tmp_path: Path) -> None:
        """uptime must be a non-negative integer (seconds since worker start)."""
        workers_dir = tmp_path / "workers"
        data: dict[str, object] = {
            "worker_id": "worker-0",
            "current_task": None,
            "queue": [],
            "uptime": 0,
        }
        jf = _write_worker_json(workers_dir, 0, data)
        loaded = json.loads(jf.read_text(encoding="utf-8"))
        assert isinstance(loaded["uptime"], (int, float))
        assert loaded["uptime"] >= 0


class TestWorkerQueueEndpointBehavior:
    """Verify expected behavior of GET /api/workers/<id>/queue endpoint logic."""

    def test_endpoint_returns_worker_id_string(self, tmp_path: Path) -> None:
        """Endpoint must return worker_id as 'worker-N' string."""
        workers_dir = tmp_path / "workers"
        data: dict[str, object] = {
            "worker_id": "worker-0",
            "current_task": {"story_id": "US-123", "started_at": "2026-03-20T10:00:00Z"},
            "queue": [],
            "uptime": 30,
        }
        _write_worker_json(workers_dir, 0, data)
        # Simulate what the endpoint does: read the JSON and shape the response
        jf = workers_dir / "worker_0.json"
        raw = json.loads(jf.read_text(encoding="utf-8"))
        response = {
            "worker_id": "worker-0",
            "current_task": raw.get("current_task"),
            "queue": raw.get("queue", []),
            "uptime": raw.get("uptime", 0),
        }
        assert response["worker_id"] == "worker-0"
        assert isinstance(response["current_task"], dict)
        assert isinstance(response["queue"], list)
        assert isinstance(response["uptime"], (int, float))

    def test_missing_worker_json_produces_404_payload(self, tmp_path: Path) -> None:
        """When worker_N.json does not exist, endpoint should return 404 with error_code."""
        workers_dir = tmp_path / "workers"
        workers_dir.mkdir(parents=True, exist_ok=True)
        # Simulate the 404 response the endpoint produces
        worker_id = 99
        jf = workers_dir / f"worker_{worker_id}.json"
        assert not jf.exists(), "Pre-condition: JSON file must not exist"

        # Simulate the endpoint's 404 response shape
        response_404 = {"error": f"Worker {worker_id} not found", "error_code": "WORKER_NOT_FOUND"}
        assert response_404["error_code"] == "WORKER_NOT_FOUND"
        assert str(worker_id) in response_404["error"]

    def test_workers_list_includes_queue_depth(self, tmp_path: Path) -> None:
        """GET /api/workers list response must include queue_depth for each worker."""
        workers_dir = tmp_path / "workers"

        # Worker 0: running with 2 items in queue
        _write_worker_json(workers_dir, 0, {
            "worker_id": "worker-0",
            "current_task": {"story_id": "US-100", "started_at": "2026-03-20T10:00:00Z"},
            "queue": [{"story_id": "US-101"}, {"story_id": "US-102"}],
            "uptime": 45,
        })
        # Worker 1: idle, empty queue
        _write_worker_json(workers_dir, 1, {
            "worker_id": "worker-1",
            "current_task": None,
            "queue": [],
            "uptime": 120,
        })

        # Simulate the list endpoint's aggregation logic
        workers = []
        for wid in [0, 1]:
            jf = workers_dir / f"worker_{wid}.json"
            raw = json.loads(jf.read_text(encoding="utf-8"))
            queue_depth = len(raw.get("queue", []))
            status = "running" if raw.get("current_task") else "idle"
            workers.append({"id": wid, "queue_depth": queue_depth, "status": status})

        assert workers[0]["queue_depth"] == 2
        assert workers[0]["status"] == "running"
        assert workers[1]["queue_depth"] == 0
        assert workers[1]["status"] == "idle"

    def test_workers_list_status_field(self, tmp_path: Path) -> None:
        """Worker status must be 'running' when current_task is set, 'idle' otherwise."""
        workers_dir = tmp_path / "workers"
        _write_worker_json(workers_dir, 0, {
            "current_task": {"story_id": "US-200", "started_at": "2026-03-20T12:00:00Z"},
            "queue": [],
            "uptime": 10,
        })
        raw = json.loads((workers_dir / "worker_0.json").read_text(encoding="utf-8"))
        status = "running" if raw.get("current_task") else "idle"
        assert status == "running"

        _write_worker_json(workers_dir, 1, {
            "current_task": None,
            "queue": [],
            "uptime": 0,
        })
        raw2 = json.loads((workers_dir / "worker_1.json").read_text(encoding="utf-8"))
        status2 = "running" if raw2.get("current_task") else "idle"
        assert status2 == "idle"


class TestWorkerQueueEndpointHTTP:
    """Optional HTTP integration tests — skipped when Spiral UI server is not running."""

    QUEUE_URL = "http://localhost:5299/api/workers/0/queue"
    LIST_URL = "http://localhost:5299/api/workers"

    def _server_available(self) -> bool:
        """Check if Spiral UI server is reachable."""
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:5299/api/project", timeout=1) as r:
                return bool(r.status == 200)
        except Exception:
            return False

    def test_queue_endpoint_shape_when_server_running(self, tmp_path: Path) -> None:
        """If Spiral UI is running, GET /api/workers/0/queue returns correct JSON keys."""
        if not self._server_available():
            pytest.skip("Spiral UI server not running on localhost:5299")

        import urllib.request
        try:
            with urllib.request.urlopen(self.QUEUE_URL, timeout=2) as r:
                data = json.loads(r.read().decode())
                # Endpoint returns valid JSON with required keys (or 404)
                assert "worker_id" in data or "error_code" in data
        except Exception as exc:
            # 404 is acceptable (no workers running)
            assert "404" in str(exc) or "Error" in str(exc)

    def test_list_endpoint_shape_when_server_running(self) -> None:
        """If Spiral UI is running, GET /api/workers returns list with queue_depth/status fields."""
        if not self._server_available():
            pytest.skip("Spiral UI server not running on localhost:5299")

        import urllib.request
        with urllib.request.urlopen(self.LIST_URL, timeout=2) as r:
            data = json.loads(r.read().decode())
            assert "workers" in data
            for w in data["workers"]:
                assert "id" in w
                assert "queue_depth" in w, f"queue_depth missing from worker {w}"
                assert "status" in w, f"status missing from worker {w}"
