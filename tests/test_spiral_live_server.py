"""Tests for spiral_live_server.py — SSE worker streaming (US-277, US-230)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import spiral_live_server as _live_mod
from spiral_live_server import SpiralLiveServer, WorkerState, _DONE_SENTINEL


# ── Helper: run async tests without pytest-asyncio ───────────────────────────

def arun(coro):  # type: ignore[no-untyped-def]
    """Run *coro* in a fresh event loop and return the result."""
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Mock writer ───────────────────────────────────────────────────────────────

def _make_writer() -> MagicMock:
    """Return a mock asyncio.StreamWriter that records written bytes."""
    writer = MagicMock()
    writer._written: List[bytes] = []

    def _write(data: bytes) -> None:
        writer._written.append(data)

    writer.write = MagicMock(side_effect=_write)
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


def _get_response_body(writer: MagicMock) -> bytes:
    combined = b"".join(writer._written)
    sep = combined.find(b"\r\n\r\n")
    return combined[sep + 4:] if sep != -1 else b""


def _get_status_code(writer: MagicMock) -> int:
    combined = b"".join(writer._written)
    line = combined.split(b"\r\n")[0].decode()
    return int(line.split(" ")[1])


# ── WorkerState unit tests ────────────────────────────────────────────────────


class TestWorkerState:
    def test_subscribe_running_worker_returns_queue(self) -> None:
        w = WorkerState(worker_id="1", cmd=["echo", "hi"])
        q = w.subscribe()
        assert q is not None
        assert q in w._subscriber_queues

    def test_subscribe_finished_worker_returns_done_immediately(self) -> None:
        w = WorkerState(worker_id="2", cmd=["echo", "hi"])
        w.status = "passed"
        q = w.subscribe()
        # Queue should have done event + sentinel, not be in subscriber list
        assert q not in w._subscriber_queues
        assert q.qsize() == 2
        event = q.get_nowait()
        assert event["type"] == "done"
        assert event["status"] == "passed"
        sentinel = q.get_nowait()
        assert sentinel is _DONE_SENTINEL

    def test_subscribe_failed_worker_returns_failed_done(self) -> None:
        w = WorkerState(worker_id="3", cmd=["false"])
        w.status = "failed"
        q = w.subscribe()
        assert q.qsize() == 2
        event = q.get_nowait()
        assert event["type"] == "done"
        assert event["status"] == "failed"

    def test_broadcast_fans_out_to_all_subscribers(self) -> None:
        async def _run() -> None:
            w = WorkerState(worker_id="4", cmd=["echo", "hi"])
            q1 = w.subscribe()
            q2 = w.subscribe()
            event = {"type": "line", "worker_id": "4", "text": "hello", "stream": "stdout"}
            await w.broadcast(event)
            assert q1.qsize() == 1
            assert q2.qsize() == 1
            assert q1.get_nowait() == event
            assert q2.get_nowait() == event

        arun(_run())

    def test_close_subscribers_sends_sentinel(self) -> None:
        async def _run() -> None:
            w = WorkerState(worker_id="5", cmd=["echo"])
            q = w.subscribe()
            await w.close_subscribers()
            assert q.get_nowait() is _DONE_SENTINEL
            assert w._subscriber_queues == []

        arun(_run())


# ── SpiralLiveServer routing tests ───────────────────────────────────────────


class TestRouting:
    def test_register_project_returns_200(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            body = json.dumps({"name": "my-project", "root": "/tmp/proj"}).encode()
            await server._route("POST", "/api/register-project", {}, body, writer)
            assert _get_status_code(writer) == 200
            response = json.loads(_get_response_body(writer))
            assert response["registered"] == "my-project"
            assert "my-project" in server._projects

        arun(_run())

    def test_register_project_bad_json_still_responds(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("POST", "/api/register-project", {}, b"not-json", writer)
            # Should not crash
            assert _get_status_code(writer) == 200

        arun(_run())

    def test_worker_stream_unknown_returns_404(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("GET", "/api/worker-stream/99", {}, b"", writer)
            assert _get_status_code(writer) == 404
            body = json.loads(_get_response_body(writer))
            assert "not found" in body["error"].lower()

        arun(_run())

    def test_worker_start_bad_json_returns_400(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("POST", "/api/worker-start", {}, b"not-json", writer)
            assert _get_status_code(writer) == 400

        arun(_run())

    def test_worker_start_missing_cmd_returns_400(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            body = json.dumps({"worker_id": "1"}).encode()  # missing 'cmd'
            await server._route("POST", "/api/worker-start", {}, body, writer)
            assert _get_status_code(writer) == 400

        arun(_run())

    def test_index_returns_200(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("GET", "/", {}, b"", writer)
            assert _get_status_code(writer) == 200
            html = _get_response_body(writer).decode()
            assert "SPIRAL Live Dashboard" in html

        arun(_run())

    def test_project_dashboard_returns_200(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("GET", "/my-project", {}, b"", writer)
            assert _get_status_code(writer) == 200
            html = _get_response_body(writer).decode()
            assert "my-project" in html

        arun(_run())

    def test_unknown_path_returns_404(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._route("GET", "/api/unknown/endpoint", {}, b"", writer)
            assert _get_status_code(writer) == 404

        arun(_run())


# ── SSE stream end-to-end tests ───────────────────────────────────────────────


class TestSseStream:
    def test_sse_streams_lines_and_done_event(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            worker = WorkerState(worker_id="w1", cmd=["echo", "hi"])
            server._workers["w1"] = worker

            writer = _make_writer()
            sse_task = asyncio.create_task(
                server._handle_sse_stream("w1", writer)
            )
            # Yield control so the handler can subscribe and write headers
            await asyncio.sleep(0)

            line_event = {"type": "line", "worker_id": "w1", "text": "building...", "stream": "stdout"}
            await worker.broadcast(line_event)

            done_event = {"type": "done", "worker_id": "w1", "status": "passed"}
            await worker.broadcast(done_event)
            await worker.close_subscribers()

            await asyncio.wait_for(sse_task, timeout=2.0)

            combined = b"".join(writer._written).decode()
            assert "text/event-stream" in combined
            assert "building..." in combined
            assert '"type": "done"' in combined
            assert '"status": "passed"' in combined

        arun(_run())

    def test_sse_stream_404_for_unknown_worker(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            writer = _make_writer()
            await server._handle_sse_stream("nonexistent", writer)
            assert _get_status_code(writer) == 404

        arun(_run())

    def test_sse_streams_both_stdout_and_stderr(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            worker = WorkerState(worker_id="w2", cmd=["echo"])
            server._workers["w2"] = worker

            writer = _make_writer()
            sse_task = asyncio.create_task(
                server._handle_sse_stream("w2", writer)
            )
            await asyncio.sleep(0)

            await worker.broadcast(
                {"type": "line", "worker_id": "w2", "text": "out line", "stream": "stdout"}
            )
            await worker.broadcast(
                {"type": "line", "worker_id": "w2", "text": "err line", "stream": "stderr"}
            )
            await worker.broadcast(
                {"type": "done", "worker_id": "w2", "status": "failed"}
            )
            await worker.close_subscribers()

            await asyncio.wait_for(sse_task, timeout=2.0)
            combined = b"".join(writer._written).decode()
            assert "out line" in combined
            assert "err line" in combined
            assert '"status": "failed"' in combined

        arun(_run())


# ── Worker subprocess integration tests ──────────────────────────────────────


class TestWorkerSubprocess:
    def test_run_worker_streams_stdout_and_stderr(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            cmd = [
                sys.executable, "-c",
                "import sys; print('hello stdout'); print('hello stderr', file=sys.stderr)"
            ]
            worker = WorkerState(worker_id="sub1", cmd=cmd)
            server._workers["sub1"] = worker

            q = worker.subscribe()
            await asyncio.wait_for(server._run_worker(worker), timeout=10.0)

            events = []
            while not q.empty():
                item = q.get_nowait()
                if item is not _DONE_SENTINEL:
                    events.append(item)

            texts = [e["text"] for e in events if e.get("type") == "line"]
            done_events = [e for e in events if e.get("type") == "done"]

            assert "hello stdout" in texts
            assert "hello stderr" in texts
            assert done_events
            assert done_events[-1]["status"] == "passed"
            assert worker.status == "passed"

        arun(_run())

    def test_run_worker_sets_failed_on_nonzero_exit(self) -> None:
        async def _run() -> None:
            server = SpiralLiveServer()
            cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
            worker = WorkerState(worker_id="sub2", cmd=cmd)
            server._workers["sub2"] = worker
            q = worker.subscribe()

            await asyncio.wait_for(server._run_worker(worker), timeout=10.0)

            events = []
            while not q.empty():
                item = q.get_nowait()
                if item is not _DONE_SENTINEL:
                    events.append(item)

            done_events = [e for e in events if e.get("type") == "done"]
            assert done_events
            assert done_events[-1]["status"] == "failed"
            assert worker.status == "failed"

        arun(_run())

    def test_run_worker_no_deadlock_with_large_stdout(self) -> None:
        """A subprocess writing 10 MB to stdout must not deadlock (US-230).

        Without concurrent pipe draining the OS pipe-buffer (~64 KB) fills up,
        the child blocks on write, the parent blocks on wait() — deadlock.
        The streaming architecture drains both pipes concurrently so this
        should complete well within the 30-second guard timeout.
        """
        async def _run() -> None:
            # Generate ~10 MB of stdout output (line-buffered)
            big_script = (
                "import sys\n"
                "line = 'x' * 1000 + '\\n'\n"
                "for _ in range(10_000):\n"
                "    sys.stdout.write(line)\n"
                "sys.stdout.flush()\n"
            )
            server = SpiralLiveServer()
            cmd = [sys.executable, "-c", big_script]
            worker = WorkerState(worker_id="big1", cmd=cmd)
            server._workers["big1"] = worker

            q = worker.subscribe()
            # 30s guard — if this hangs we have a real deadlock
            await asyncio.wait_for(server._run_worker(worker), timeout=30.0)

            # Drain queue; collect only line events
            line_count = 0
            while not q.empty():
                item = q.get_nowait()
                if item is not _DONE_SENTINEL and isinstance(item, dict):
                    if item.get("type") == "line":
                        line_count += 1

            assert worker.status == "passed"
            assert line_count >= 1000  # at least some lines must have streamed

        arun(_run())

    def test_run_worker_timeout_sets_timeout_status(self) -> None:
        """A subprocess that hangs must be killed and result in status 'timeout' (US-230)."""
        async def _run() -> None:
            # Subprocess that sleeps forever
            hang_script = "import time; time.sleep(9999)"
            server = SpiralLiveServer()
            cmd = [sys.executable, "-c", hang_script]
            worker = WorkerState(worker_id="hang1", cmd=cmd)
            server._workers["hang1"] = worker

            q = worker.subscribe()

            # Temporarily lower the timeout to 1 second for this test
            original_timeout = _live_mod._SUBPROCESS_TIMEOUT
            _live_mod._SUBPROCESS_TIMEOUT = 1.0
            try:
                # Allow up to 10s for the test itself (timeout fires at 1s)
                await asyncio.wait_for(server._run_worker(worker), timeout=10.0)
            finally:
                _live_mod._SUBPROCESS_TIMEOUT = original_timeout

            # Collect events
            events = []
            while not q.empty():
                item = q.get_nowait()
                if item is not _DONE_SENTINEL and isinstance(item, dict):
                    events.append(item)

            assert worker.status == "timeout"
            done_events = [e for e in events if e.get("type") == "done"]
            assert done_events
            assert done_events[-1]["status"] == "timeout"
            # Should have a stderr line mentioning TIMEOUT
            timeout_lines = [
                e for e in events
                if e.get("type") == "line" and "TIMEOUT" in e.get("text", "")
            ]
            assert timeout_lines, "Expected a TIMEOUT log line broadcast to subscribers"

        arun(_run())
