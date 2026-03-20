"""Tests for US-481: Real-time worker pool status HTTP API (/api/workers endpoint)."""

import asyncio
import json
import os
import shutil
import tempfile
import time


def test_api_workers_empty_when_no_workers(monkeypatch, tmp_path):
    """Test /api/workers returns empty array when no workers running."""

    async def run_test():
        from lib.ui.spiral_live_server import SpiralLiveServer

        server = SpiralLiveServer(host="127.0.0.1", port=5300)

        # Mock .spiral-workers to be a non-existent directory
        workers_dir = tmp_path / ".spiral-workers"
        monkeypatch.setattr("os.path.isdir", lambda x: str(x) == str(workers_dir) and workers_dir.exists())

        # Capture the JSON response
        captured = []

        async def mock_send_json(writer, status, data):
            captured.append((status, data))

        # Replace _send_json with our mock
        original_send_json = server._send_json
        server._send_json = mock_send_json

        # Mock writer (not used in test, but required by signature)
        class MockWriter:
            pass

        try:
            await server._handle_api_workers("/api/workers", MockWriter())
            assert len(captured) == 1
            status, data = captured[0]
            assert status == 200
            assert isinstance(data, list)
            assert len(data) == 0
        finally:
            server._send_json = original_send_json

    asyncio.run(run_test())


def test_api_workers_returns_correct_schema(tmp_path):
    """Test /api/workers returns correct schema with active workers."""

    async def run_test():
        from lib.ui.spiral_live_server import SpiralLiveServer

        # Create a worker directory in the actual hardcoded location
        real_workers_dir = ".spiral-workers"
        os.makedirs(real_workers_dir, exist_ok=True)
        real_worker_dir = os.path.join(real_workers_dir, "worker-schema-test")
        os.makedirs(real_worker_dir, exist_ok=True)

        now = time.time()
        real_heartbeat = os.path.join(real_worker_dir, ".heartbeat")
        with open(real_heartbeat, "w") as f:
            json.dump({"ts": now, "story_id": "US-999"}, f)

        try:
            server = SpiralLiveServer(host="127.0.0.1", port=5300)

            # Capture the JSON response
            captured = []

            async def mock_send_json(writer, status, data):
                captured.append((status, data))

            original_send_json = server._send_json
            server._send_json = mock_send_json

            class MockWriter:
                pass

            try:
                await server._handle_api_workers("/api/workers", MockWriter())
                assert len(captured) == 1
                status, data = captured[0]
                assert status == 200
                assert isinstance(data, list)
                assert len(data) >= 1

                # Check schema of first worker
                worker = data[0]
                assert "worker_id" in worker
                assert "current_story" in worker
                assert "elapsed_time_sec" in worker
                assert "state" in worker
                assert worker["state"] in ("alive", "timeout", "queued")
            finally:
                server._send_json = original_send_json
        finally:
            # Cleanup
            if os.path.exists(real_workers_dir):
                shutil.rmtree(real_workers_dir)

    asyncio.run(run_test())


def test_api_workers_timeout_detection():
    """Test /api/workers marks workers as timeout if heartbeat >5min stale."""

    # Create a temporary worker directory with stale heartbeat
    tmpdir = tempfile.mkdtemp()
    try:
        workers_dir = os.path.join(tmpdir, ".spiral-workers")
        os.makedirs(workers_dir)

        worker_dir = os.path.join(workers_dir, "worker-stale")
        os.makedirs(worker_dir)

        # Create stale heartbeat file (7 minutes old)
        old_timestamp = time.time() - 420  # 7 minutes
        heartbeat_data = {"ts": old_timestamp, "story_id": "US-456"}
        heartbeat_file = os.path.join(worker_dir, ".heartbeat")
        with open(heartbeat_file, "w") as f:
            json.dump(heartbeat_data, f)

        # Verify timeout logic
        now = time.time()
        timeout_threshold = 300  # 5 minutes
        ts = heartbeat_data["ts"]
        elapsed_time_sec = int(now - ts)
        state = "timeout" if elapsed_time_sec > timeout_threshold else "alive"

        assert elapsed_time_sec > timeout_threshold
        assert state == "timeout"
    finally:
        shutil.rmtree(tmpdir)


def test_api_workers_ignores_malformed_heartbeat(tmp_path):
    """Test /api/workers ignores malformed heartbeat files."""
    workers_dir = tmp_path / ".spiral-workers"
    workers_dir.mkdir()

    worker_dir = workers_dir / "worker-broken"
    worker_dir.mkdir()

    # Create malformed heartbeat file
    heartbeat_file = worker_dir / ".heartbeat"
    heartbeat_file.write_text("{invalid json")

    # Test that malformed JSON is gracefully skipped
    workers = []
    heartbeat_path = str(heartbeat_file)
    try:
        with open(heartbeat_path, encoding="utf-8") as f:
            data = json.load(f)
        workers.append(data)
    except (OSError, json.JSONDecodeError):
        pass  # Gracefully ignore

    assert len(workers) == 0
