#!/usr/bin/env python3
"""spiral_live_server.py — Live streaming server for SPIRAL worker output via SSE.

Serves an HTTP server on port 5299 (SPIRAL_UI_PORT) with:
  - GET /api/worker-stream/{worker_id}  → SSE stream of worker stdout+stderr
  - POST /api/worker-start              → Start a worker subprocess, return worker_id
  - POST /api/register-project          → Register project info
  - GET /{project_name}                 → Live dashboard HTML
  - GET /                               → Index page listing projects

SSE event format:
  data: {"type": "line", "worker_id": "1", "text": "...", "stream": "stdout|stderr"}\\n\\n
  data: {"type": "done", "worker_id": "1", "status": "passed|failed"}\\n\\n

stdlib-only — no external dependencies.

Usage:
    python lib/spiral_live_server.py [--port 5299] [--host 0.0.0.0]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from asyncio import Queue
from dataclasses import dataclass, field
from html import escape
from typing import List, Optional

# ── Configuration ─────────────────────────────────────────────────────────────

# Hard timeout (seconds) for each worker subprocess. Prevents hung workers that
# never terminate. Set SPIRAL_SUBPROCESS_TIMEOUT=0 to disable (not recommended).
_SUBPROCESS_TIMEOUT: float = float(os.environ.get("SPIRAL_SUBPROCESS_TIMEOUT", "300"))

# ── Data Structures ───────────────────────────────────────────────────────────

_DONE_SENTINEL = object()  # Marks end of a worker's output queue


@dataclass
class WorkerState:
    """Tracks a single running (or finished) worker process."""

    worker_id: str
    cmd: List[str]
    process: Optional[asyncio.subprocess.Process] = None
    status: str = "running"  # running | passed | failed | timeout
    # Each SSE subscriber gets its own Queue; broadcaster fans-out to all
    _subscriber_queues: List[Queue] = field(default_factory=list)  # type: ignore[type-arg]
    _broadcast_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    def subscribe(self) -> Queue:  # type: ignore[type-arg]
        """Return a new per-subscriber queue pre-loaded with done sentinel if finished."""
        q: Queue = Queue()  # type: ignore[type-arg]
        if self.status != "running":
            # Worker already finished — send done immediately
            done_evt = {"type": "done", "worker_id": self.worker_id, "status": self.status}
            q.put_nowait(done_evt)
            q.put_nowait(_DONE_SENTINEL)
        else:
            self._subscriber_queues.append(q)
        return q

    async def broadcast(self, event: object) -> None:
        """Fan-out an event (dict or sentinel) to all subscriber queues."""
        for q in list(self._subscriber_queues):
            await q.put(event)

    async def close_subscribers(self) -> None:
        """Send sentinel to all subscriber queues and clear the list."""
        for q in list(self._subscriber_queues):
            await q.put(_DONE_SENTINEL)
        self._subscriber_queues.clear()


# ── Server ────────────────────────────────────────────────────────────────────

class SpiralLiveServer:
    """Asyncio-based HTTP server with SSE worker-stream support."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5299) -> None:
        self.host = host
        self.port = port
        self._workers: dict[str, WorkerState] = {}
        self._projects: dict[str, dict] = {}  # type: ignore[type-arg]

    # ── Worker management ────────────────────────────────────────────────────

    async def _stream_pipe(
        self,
        worker: WorkerState,
        reader: asyncio.StreamReader,
        stream_name: str,
    ) -> None:
        """Read lines from *reader* and broadcast them as SSE line events."""
        while True:
            try:
                raw = await reader.readline()
            except Exception:
                break
            if not raw:
                break
            text = raw.decode("utf-8", errors="replace").rstrip("\n\r")
            event = {
                "type": "line",
                "worker_id": worker.worker_id,
                "text": text,
                "stream": stream_name,
            }
            await worker.broadcast(event)

    async def _run_worker(self, worker: WorkerState) -> None:
        """Spawn the worker subprocess and stream stdout+stderr concurrently.

        Uses asyncio.wait_for() to enforce SPIRAL_SUBPROCESS_TIMEOUT so that a
        hung subprocess cannot block the event loop indefinitely.  A TimeoutError
        results in worker.status == "timeout" (distinct from "failed").
        """
        cmd_prefix = " ".join(worker.cmd[:3])  # for log messages
        try:
            proc = await asyncio.create_subprocess_exec(
                *worker.cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            worker.process = proc

            assert proc.stdout is not None
            assert proc.stderr is not None

            # Read both streams concurrently to prevent OS pipe-buffer deadlock,
            # then wait for the process to exit — all under a hard timeout.
            stdout_task = asyncio.create_task(
                self._stream_pipe(worker, proc.stdout, "stdout")
            )
            stderr_task = asyncio.create_task(
                self._stream_pipe(worker, proc.stderr, "stderr")
            )

            async def _drain_and_wait() -> int:
                await asyncio.gather(stdout_task, stderr_task)
                return await proc.wait()

            timeout = _SUBPROCESS_TIMEOUT if _SUBPROCESS_TIMEOUT > 0 else None
            returncode = await asyncio.wait_for(_drain_and_wait(), timeout=timeout)
            worker.status = "passed" if returncode == 0 else "failed"

        except asyncio.TimeoutError:
            logging.warning(
                "[spiral_live_server] worker %s timed out after %.0fs (cmd: %s)",
                worker.worker_id,
                _SUBPROCESS_TIMEOUT,
                cmd_prefix,
            )
            timeout_event = {
                "type": "line",
                "worker_id": worker.worker_id,
                "text": (
                    f"[spiral_live_server] TIMEOUT: worker exceeded "
                    f"{_SUBPROCESS_TIMEOUT:.0f}s limit (cmd: {cmd_prefix})"
                ),
                "stream": "stderr",
            }
            await worker.broadcast(timeout_event)
            worker.status = "timeout"
            # Kill the process and drain to avoid zombie
            if worker.process is not None:
                try:
                    worker.process.kill()
                    await worker.process.communicate()
                except Exception:
                    pass

        except Exception as exc:
            # Broadcast error line so clients can see the failure
            err_event = {
                "type": "line",
                "worker_id": worker.worker_id,
                "text": f"[spiral_live_server] ERROR launching worker: {exc}",
                "stream": "stderr",
            }
            await worker.broadcast(err_event)
            worker.status = "failed"
        finally:
            done_event = {
                "type": "done",
                "worker_id": worker.worker_id,
                "status": worker.status,
            }
            await worker.broadcast(done_event)
            await worker.close_subscribers()

    def start_worker(self, worker_id: str, cmd: List[str]) -> WorkerState:
        """Register and schedule a new worker subprocess."""
        worker = WorkerState(worker_id=worker_id, cmd=cmd)
        self._workers[worker_id] = worker
        worker._broadcast_task = asyncio.ensure_future(self._run_worker(worker))
        return worker

    # ── HTTP handling ─────────────────────────────────────────────────────────

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Dispatch incoming HTTP request to the appropriate handler."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not request_line:
                writer.close()
                return
            decoded = request_line.decode("utf-8", errors="replace").strip()
            parts = decoded.split(" ")
            if len(parts) < 2:
                writer.close()
                return
            method, path = parts[0], parts[1]

            # Read headers
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" in line:
                    k, _, v = line.decode("utf-8", errors="replace").partition(":")
                    headers[k.strip().lower()] = v.strip()

            # Read body for POST requests
            body = b""
            content_length = int(headers.get("content-length", "0"))
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=10.0
                )

            # Route
            await self._route(method, path, headers, body, writer)
        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            try:
                await self._send_error(writer, 500, "Internal Server Error")
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Route request to the correct handler."""
        # --- SSE stream ---
        m = re.match(r"^/api/worker-stream/([^/?]+)$", path)
        if m and method == "GET":
            await self._handle_sse_stream(m.group(1), writer)
            return

        # --- Worker start ---
        if path == "/api/worker-start" and method == "POST":
            await self._handle_worker_start(body, writer)
            return

        # --- Register project ---
        if path == "/api/register-project" and method == "POST":
            await self._handle_register_project(body, writer)
            return

        # --- Dashboard index ---
        if path in ("/", "") and method == "GET":
            await self._handle_index(writer)
            return

        # --- Project dashboard ---
        m2 = re.match(r"^/([^/?]+)$", path)
        if m2 and method == "GET":
            await self._handle_project_dashboard(m2.group(1), writer)
            return

        await self._send_error(writer, 404, "Not Found")

    # ── Route handlers ────────────────────────────────────────────────────────

    async def _handle_sse_stream(
        self, worker_id: str, writer: asyncio.StreamWriter
    ) -> None:
        """Stream worker output as Server-Sent Events."""
        if worker_id not in self._workers:
            await self._send_error(writer, 404, f"Worker '{worker_id}' not found")
            return

        worker = self._workers[worker_id]
        queue = worker.subscribe()

        # SSE response headers
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "\r\n"
        )
        writer.write(response.encode("utf-8"))
        await writer.drain()

        try:
            while True:
                item = await queue.get()
                if item is _DONE_SENTINEL:
                    break
                payload = json.dumps(item)
                sse = f"data: {payload}\n\n"
                writer.write(sse.encode("utf-8"))
                await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected — remove from subscriber list
            if queue in worker._subscriber_queues:
                worker._subscriber_queues.remove(queue)

    async def _handle_worker_start(
        self, body: bytes, writer: asyncio.StreamWriter
    ) -> None:
        """Start a new worker subprocess from a JSON request body."""
        try:
            data = json.loads(body.decode("utf-8"))
            worker_id = str(data["worker_id"])
            cmd = [str(c) for c in data["cmd"]]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            await self._send_json(writer, 400, {"error": f"Bad request: {exc}"})
            return

        if worker_id in self._workers and self._workers[worker_id].status == "running":
            await self._send_json(
                writer, 409, {"error": f"Worker '{worker_id}' already running"}
            )
            return

        self.start_worker(worker_id, cmd)
        await self._send_json(
            writer, 200, {"worker_id": worker_id, "status": "started"}
        )

    async def _handle_register_project(
        self, body: bytes, writer: asyncio.StreamWriter
    ) -> None:
        """Accept a project registration (called by spiral.sh on startup)."""
        try:
            data = json.loads(body.decode("utf-8"))
            name = str(data.get("name", "unknown"))
            root = str(data.get("root", ""))
        except (json.JSONDecodeError, TypeError):
            name, root = "unknown", ""
        self._projects[name] = {"name": name, "root": root}
        await self._send_json(writer, 200, {"registered": name})

    async def _handle_index(self, writer: asyncio.StreamWriter) -> None:
        """Return HTML index listing registered projects."""
        rows = ""
        for name in sorted(self._projects):
            rows += f'<li><a href="/{escape(name)}">{escape(name)}</a></li>\n'
        if not rows:
            rows = "<li><em>No projects registered yet. Run <code>spiral.sh</code> to register.</em></li>\n"
        html = _INDEX_HTML.replace("{{ROWS}}", rows)
        await self._send_html(writer, 200, html)

    async def _handle_project_dashboard(
        self, project_name: str, writer: asyncio.StreamWriter
    ) -> None:
        """Return per-project live dashboard HTML."""
        active_workers = [
            w for w in self._workers.values()
        ]
        worker_cards = ""
        for w in active_workers:
            wid = escape(w.worker_id)
            status_cls = "status-running" if w.status == "running" else (
                "status-passed" if w.status == "passed" else "status-failed"
            )
            worker_cards += _WORKER_CARD_TMPL.replace("{{WID}}", wid).replace(
                "{{STATUS_CLS}}", status_cls
            ).replace("{{STATUS}}", escape(w.status))
        if not worker_cards:
            worker_cards = '<p class="no-workers">No active workers. Start SPIRAL to see live output here.</p>'
        html = _DASHBOARD_HTML.replace(
            "{{PROJECT}}", escape(project_name)
        ).replace("{{WORKER_CARDS}}", worker_cards)
        await self._send_html(writer, 200, html)

    # ── Low-level response helpers ────────────────────────────────────────────

    async def _send_html(
        self, writer: asyncio.StreamWriter, status: int, html: str
    ) -> None:
        body = html.encode("utf-8")
        response = (
            f"HTTP/1.1 {status} OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(response.encode("utf-8"))
        writer.write(body)
        await writer.drain()

    async def _send_json(
        self, writer: asyncio.StreamWriter, status: int, data: dict  # type: ignore[type-arg]
    ) -> None:
        body = json.dumps(data).encode("utf-8")
        phrase = {200: "OK", 400: "Bad Request", 404: "Not Found",
                  409: "Conflict", 500: "Internal Server Error"}.get(status, "Unknown")
        response = (
            f"HTTP/1.1 {status} {phrase}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(response.encode("utf-8"))
        writer.write(body)
        await writer.drain()

    async def _send_error(
        self, writer: asyncio.StreamWriter, status: int, message: str
    ) -> None:
        await self._send_json(writer, status, {"error": message})

    # ── Server lifecycle ──────────────────────────────────────────────────────

    async def serve(self) -> None:
        """Start the server and run until interrupted."""
        server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        addr = server.sockets[0].getsockname() if server.sockets else (self.host, self.port)
        print(
            f"[spiral_live_server] Listening on http://{addr[0]}:{addr[1]}/",
            flush=True,
        )
        async with server:
            await server.serve_forever()


# ── HTML Templates ────────────────────────────────────────────────────────────

_INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SPIRAL Live Dashboard</title>
<style>
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:2rem}
h1{color:#58a6ff}
a{color:#58a6ff}
ul{list-style:none;padding:0}
li{margin:.5rem 0}
</style>
</head>
<body>
<h1>SPIRAL Live Dashboard</h1>
<h2>Projects</h2>
<ul>
{{ROWS}}
</ul>
</body>
</html>
"""

_WORKER_CARD_TMPL = """\
<div class="worker-card" id="card-{{WID}}">
  <div class="worker-header">
    <span class="worker-id">Worker {{WID}}</span>
    <span class="worker-status {{STATUS_CLS}}">{{STATUS}}</span>
  </div>
  <div class="console" id="console-{{WID}}"></div>
</div>
"""

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SPIRAL — {{PROJECT}}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:1rem}
h1{color:#58a6ff;margin-bottom:1rem;font-size:1.2rem}
.workers-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:1rem}
.worker-card{background:#161b22;border:1px solid #30363d;border-radius:6px;overflow:hidden}
.worker-header{display:flex;justify-content:space-between;align-items:center;
  padding:.5rem .75rem;background:#21262d;border-bottom:1px solid #30363d}
.worker-id{font-weight:bold;color:#e6edf3}
.worker-status{font-size:.8rem;padding:.1rem .5rem;border-radius:12px;font-weight:bold}
.status-running{background:#1f4e3d;color:#3fb950}
.status-passed{background:#1a3d1a;color:#56d364}
.status-failed{background:#4e1a1a;color:#f85149}
.console{height:320px;overflow-y:auto;padding:.5rem;font-size:.8rem;
  line-height:1.4;background:#0d1117;color:#c9d1d9;white-space:pre-wrap;word-break:break-all}
.console .err{color:#f85149}
.no-workers{color:#8b949e;padding:1rem}
</style>
</head>
<body>
<h1>SPIRAL Live — {{PROJECT}}</h1>
<div class="workers-grid" id="workers-grid">
{{WORKER_CARDS}}
</div>
<script>
(function(){
  "use strict";
  // Connect SSE for each worker card already in the DOM
  function connectWorker(wid) {
    var console_el = document.getElementById("console-" + wid);
    var card = document.getElementById("card-" + wid);
    var status_el = card ? card.querySelector(".worker-status") : null;
    if (!console_el) return;
    var es = new EventSource("/api/worker-stream/" + encodeURIComponent(wid));
    es.onmessage = function(evt) {
      try {
        var data = JSON.parse(evt.data);
        if (data.type === "line") {
          var line = document.createElement("span");
          line.textContent = data.text + "\\n";
          if (data.stream === "stderr") line.className = "err";
          console_el.appendChild(line);
          console_el.scrollTop = console_el.scrollHeight;
        } else if (data.type === "done") {
          if (status_el) {
            status_el.textContent = data.status;
            status_el.className = "worker-status " + (data.status === "passed" ? "status-passed" : "status-failed");
          }
          es.close();
        }
      } catch(e) {}
    };
    es.onerror = function() { es.close(); };
  }
  // Connect all existing workers
  var cards = document.querySelectorAll(".worker-card");
  for (var i = 0; i < cards.length; i++) {
    var wid = cards[i].id.replace("card-", "");
    connectWorker(wid);
  }
})();
</script>
</body>
</html>
"""


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SPIRAL live SSE streaming server (US-277)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(__import__("os").environ.get("SPIRAL_UI_PORT", "5299")),
        help="Port to listen on (default: $SPIRAL_UI_PORT or 5299)",
    )
    args = parser.parse_args()

    server = SpiralLiveServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        print("\n[spiral_live_server] Stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
