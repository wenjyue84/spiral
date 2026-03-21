#!/usr/bin/env python3
"""spiral_live_server.py — Live streaming server for SPIRAL worker output via SSE.

Serves an HTTP server on port 5300 (SPIRAL_DASHBOARD_PORT) with:
  - GET /api/worker-stream/{worker_id}  → SSE stream of worker stdout+stderr
  - POST /api/worker-start              → Start a worker subprocess, return worker_id
  - POST /api/register-project          → Register project info
  - GET /{project_name}                 → 302 redirect to Vite React dashboard
  - GET /                               → Index page listing projects

SSE event format:
  data: {"type": "line", "worker_id": "1", "text": "...", "stream": "stdout|stderr"}\\n\\n
  data: {"type": "done", "worker_id": "1", "status": "passed|failed"}\\n\\n

stdlib-only — no external dependencies.

PORT SEPARATION (do NOT change without updating both servers):
  - Port 5299: Vite React dashboard (spiral-ui/) — full UI with 11 tabs
  - Port 5300: This Python SSE server — worker streaming APIs + redirect to Vite
  Never start this server on port 5299; that port belongs to the Vite dev server.

Usage:
    python lib/spiral_live_server.py [--port 5300] [--host 0.0.0.0]
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from asyncio import Queue
from dataclasses import dataclass, field
from html import escape
from typing import Any, List, Optional

# research_source_scorer lives in lib/ (parent of lib/ui/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from research_source_scorer import extract_sources

# ── Configuration ─────────────────────────────────────────────────────────────

# Hard timeout (seconds) for each worker subprocess. Prevents hung workers that
# never terminate. Set SPIRAL_SUBPROCESS_TIMEOUT=0 to disable (not recommended).
_SUBPROCESS_TIMEOUT: float = float(os.environ.get("SPIRAL_SUBPROCESS_TIMEOUT", "300"))

# Optional auth token for dashboard access. If set, all requests must include
# Authorization: Bearer <token> header. Set SPIRAL_DASHBOARD_AUTH_TOKEN to enable.
_AUTH_TOKEN: Optional[str] = os.environ.get("SPIRAL_DASHBOARD_AUTH_TOKEN")

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

    def _check_auth(self, headers: dict[str, str]) -> tuple[bool, str]:
        """Validate Authorization header if auth is enabled.

        Returns: (is_valid, error_message)
        - If auth not enabled: (True, "")
        - If auth enabled but header missing/invalid: (False, "Unauthorized")
        """
        if not _AUTH_TOKEN:
            return True, ""

        auth_header = headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, "Unauthorized"

        token = auth_header[7:]  # Strip "Bearer "
        if token != _AUTH_TOKEN:
            return False, "Unauthorized"

        return True, ""

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
            # Capture narrowed stream references so the closure sees StreamReader, not Optional.
            stdout_stream: asyncio.StreamReader = proc.stdout
            stderr_stream: asyncio.StreamReader = proc.stderr

            # Read both streams concurrently to prevent OS pipe-buffer deadlock,
            # then wait for the process to exit — all under a hard timeout.
            # asyncio.TaskGroup enforces structured concurrency: if one pipe-reader
            # fails, the sibling is cancelled immediately rather than left dangling.
            async def _drain_and_wait() -> int:
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._stream_pipe(worker, stdout_stream, "stdout"))
                        tg.create_task(self._stream_pipe(worker, stderr_stream, "stderr"))
                except* Exception:
                    # Pipe-reading errors are non-fatal; the process exit code is authoritative.
                    pass
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

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
                body = await asyncio.wait_for(reader.readexactly(content_length), timeout=10.0)

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
        # Check auth for protected endpoints (dashboard, API)
        auth_required = not (path == "/health" and method == "GET")
        if auth_required:
            is_valid, error_msg = self._check_auth(headers)
            if not is_valid:
                await self._send_error(writer, 401, error_msg)
                return

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

        # --- Workers status ---
        if path.split("?")[0] == "/api/workers-status" and method == "GET":
            await self._handle_workers_status(path, writer)
            return

        # --- Worker pool (US-481: /api/workers endpoint) ---
        if path.split("?")[0] == "/api/workers" and method == "GET":
            await self._handle_api_workers(path, writer)
            return

        # --- System memory (memory pressure / watchdog status) ---
        if path.split("?")[0] == "/api/system-memory" and method == "GET":
            await self._handle_system_memory(writer)
            return

        # --- Research sources (US-548) ---
        if path.split("?")[0] == "/api/dashboard/research-sources" and method == "GET":
            await self._handle_research_sources(path, writer)
            return

        # --- Project progress (/{project}/progress) ---
        m_prog = re.match(r"^/([^/?]+)/progress$", path)
        if m_prog and method == "GET":
            await self._handle_project_progress(m_prog.group(1), writer)
            return

        # --- Project dashboard (redirect to Vite React app) ---
        # The full dashboard with 11 tabs (progress, tokens, skills, constitution,
        # etc.) lives in the Vite React app on port 5299. This server only handles
        # SSE/API endpoints, so redirect /{project} to the React app.
        m2 = re.match(r"^/([^/?]+)$", path)
        if m2 and method == "GET":
            await self._handle_project_dashboard(m2.group(1), writer)
            return

        await self._send_error(writer, 404, "Not Found")

    # ── Route handlers ────────────────────────────────────────────────────────

    async def _handle_sse_stream(self, worker_id: str, writer: asyncio.StreamWriter) -> None:
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

    async def _handle_worker_start(self, body: bytes, writer: asyncio.StreamWriter) -> None:
        """Start a new worker subprocess from a JSON request body."""
        try:
            data = json.loads(body.decode("utf-8"))
            worker_id = str(data["worker_id"])
            cmd = [str(c) for c in data["cmd"]]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            await self._send_json(writer, 400, {"error": f"Bad request: {exc}"})
            return

        if worker_id in self._workers and self._workers[worker_id].status == "running":
            await self._send_json(writer, 409, {"error": f"Worker '{worker_id}' already running"})
            return

        self.start_worker(worker_id, cmd)
        await self._send_json(writer, 200, {"worker_id": worker_id, "status": "started"})

    async def _handle_register_project(self, body: bytes, writer: asyncio.StreamWriter) -> None:
        """Accept a project registration (called by spiral.sh on startup)."""
        try:
            data = json.loads(body.decode("utf-8"))
            name = str(data.get("name", "unknown"))
            root = str(data.get("root", ""))
        except (json.JSONDecodeError, TypeError):
            name, root = "unknown", ""
        self._projects[name] = {"name": name, "root": root}
        await self._send_json(writer, 200, {"registered": name})

    async def _handle_workers_status(self, path: str, writer: asyncio.StreamWriter) -> None:
        """Return JSON array of live worker states read from heartbeat files."""
        qs = path.partition("?")[2]
        params = urllib.parse.parse_qs(qs)
        project_name = params.get("project_name", [""])[0]

        heartbeat_dir = os.path.join(".spiral", "workers")
        if project_name and project_name in self._projects:
            root = self._projects[project_name].get("root", "")
            if root:
                heartbeat_dir = os.path.join(root, ".spiral", "workers")

        workers: list[dict[str, Any]] = []
        now = time.time()
        for hb_file in glob.glob(os.path.join(heartbeat_dir, "worker_*.heartbeat")):
            try:
                with open(hb_file) as f:
                    data = json.load(f)
                age_sec = int(now - data.get("ts", now))
                data["heartbeat_age_sec"] = age_sec
                data["stale"] = age_sec > 120
                data["worker_id"] = os.path.basename(hb_file).replace("worker_", "").replace(".heartbeat", "")
                workers.append(data)
            except Exception:
                pass

        workers.sort(key=lambda w: w.get("worker_id", "0"))
        await self._send_json(writer, 200, {"workers": workers, "ts": now})

    async def _handle_api_workers(self, path: str, writer: asyncio.StreamWriter) -> None:
        """Return JSON array of worker pool status from heartbeat files (US-481).

        Returns: [{worker_id, current_story, elapsed_time_sec, state, mem_mb, phase, completed, pid, paused, status_reason}]
        where state is one of: 'alive' (heartbeat fresh), 'timeout' (>5min stale), 'queued' (worktree exists but no heartbeat)
        """
        workers_dir = ".spiral-workers"
        scratch_dir = ".spiral"
        now = time.time()
        timeout_threshold_sec = 300  # 5 minutes
        workers: list[dict[str, Any]] = []

        # Scan .spiral-workers/ directory for worker-N subdirectories
        if not os.path.isdir(workers_dir):
            await self._send_json(writer, 200, workers)
            return

        try:
            worker_subdirs = [d for d in os.listdir(workers_dir) if os.path.isdir(os.path.join(workers_dir, d))]
        except OSError:
            await self._send_json(writer, 200, workers)
            return

        for worker_subdir in worker_subdirs:
            heartbeat_file = os.path.join(workers_dir, worker_subdir, ".heartbeat")

            # Extract worker number for pause file detection
            worker_num = worker_subdir.replace("worker-", "").replace("worker_", "")

            # Check for pause file
            pause_file = os.path.join(scratch_dir, f"_worker_pause_{worker_num}")
            is_paused = os.path.exists(pause_file)

            try:
                with open(heartbeat_file, encoding="utf-8") as f:
                    hb_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                # Worktree exists but no heartbeat — mark as queued
                status_reason = "Paused — memory pressure" if is_paused else "Waiting for resources to launch"
                worker_entry = {
                    "worker_id": worker_subdir,
                    "current_story": None,
                    "elapsed_time_sec": 0,
                    "state": "paused" if is_paused else "queued",
                    "mem_mb": None,
                    "phase": None,
                    "completed": 0,
                    "pid": None,
                    "paused": is_paused,
                    "status_reason": status_reason,
                }
                workers.append(worker_entry)
                continue

            # Extract fields from heartbeat JSON
            ts = hb_data.get("ts")
            if ts is None:
                continue

            elapsed_time_sec = int(now - ts)
            story_id = hb_data.get("storyId", "unknown")

            # Determine state: alive or timeout (based on 5-min threshold)
            if is_paused:
                state = "paused"
            elif elapsed_time_sec > timeout_threshold_sec:
                state = "timeout"
            else:
                state = "alive"

            # Build status reason
            status_reason = ""
            if is_paused:
                status_reason = "Paused — memory pressure"
            elif state == "timeout":
                status_reason = f"No heartbeat for {elapsed_time_sec}s"

            worker_entry = {
                "worker_id": worker_subdir,
                "current_story": story_id,
                "elapsed_time_sec": elapsed_time_sec,
                "state": state,
                "mem_mb": hb_data.get("memMb"),
                "phase": hb_data.get("phase"),
                "completed": hb_data.get("completed", 0),
                "pid": hb_data.get("pid"),
                "paused": is_paused,
                "status_reason": status_reason,
            }
            workers.append(worker_entry)

        # Sort by worker_id for consistent ordering
        workers.sort(key=lambda w: str(w.get("worker_id", "")))
        await self._send_json(writer, 200, workers)

    async def _handle_system_memory(self, writer: asyncio.StreamWriter) -> None:
        """Return system memory status from the watchdog pressure file.

        Reads .spiral/_memory_pressure.json and enriches with derived fields.
        Returns watchdog_running: false when pressure file is missing or stale (>120s).
        """
        pressure_file = os.path.join(".spiral", "_memory_pressure.json")
        level_labels = {0: "Normal", 1: "Elevated", 2: "High", 3: "Critical", 4: "Emergency"}

        try:
            with open(pressure_file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            await self._send_json(
                writer,
                200,
                {
                    "watchdog_running": False,
                    "level": None,
                    "level_label": None,
                    "free_mb": None,
                    "total_mb": None,
                    "used_mb": None,
                    "free_pct": None,
                    "recommended_workers": None,
                    "per_worker_budget_mb": 1536,
                    "config_hints": ["Memory watchdog not running — start SPIRAL to enable monitoring"],
                },
            )
            return

        # Check staleness via ts field
        ts_str = data.get("ts", "")
        stale = False
        if ts_str:
            try:
                from datetime import datetime, timezone

                ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_sec = (datetime.now(timezone.utc) - ts_dt).total_seconds()
                stale = age_sec > 120
            except (ValueError, TypeError):
                stale = True
        else:
            stale = True

        if stale:
            await self._send_json(
                writer,
                200,
                {
                    "watchdog_running": False,
                    "level": data.get("level"),
                    "level_label": level_labels.get(data.get("level", -1)),
                    "free_mb": data.get("free_mb"),
                    "total_mb": data.get("total_mb"),
                    "used_mb": None,
                    "free_pct": None,
                    "recommended_workers": data.get("recommended_workers"),
                    "per_worker_budget_mb": 1536,
                    "config_hints": ["Memory watchdog data is stale (>120s) — watchdog may have stopped"],
                },
            )
            return

        level = data.get("level", 0)
        free_mb = data.get("free_mb", 0)
        total_mb = data.get("total_mb")
        recommended_workers = data.get("recommended_workers", 0)

        # Compute derived fields
        used_mb = (total_mb - free_mb) if total_mb else None
        free_pct = int((free_mb / total_mb) * 100) if total_mb and total_mb > 0 else None

        # Build config hints
        hints = []
        per_worker_budget = 1536
        if free_mb and free_mb > 0:
            capacity = max(1, free_mb // per_worker_budget)
            hints.append(f"Free RAM supports ~{capacity} workers at {per_worker_budget} MB each")
        if level >= 2:
            hints.append("Consider reducing SPIRAL_RALPH_WORKERS or closing other applications")
        if level >= 3:
            hints.append("Model routing forced to haiku — reduce memory pressure for better models")
        rec_model = data.get("recommended_model", "")
        if rec_model:
            hints.append(f"Recommended model: {rec_model}")
        skip = data.get("skip_phases", [])
        if skip:
            hints.append(f"Phases skipped due to pressure: {', '.join(skip)}")

        await self._send_json(
            writer,
            200,
            {
                "watchdog_running": True,
                "level": level,
                "level_label": level_labels.get(level, "Unknown"),
                "free_mb": free_mb,
                "total_mb": total_mb,
                "used_mb": used_mb,
                "free_pct": free_pct,
                "recommended_workers": recommended_workers,
                "per_worker_budget_mb": per_worker_budget,
                "config_hints": hints,
            },
        )

    async def _handle_research_sources(self, path: str, writer: asyncio.StreamWriter) -> None:
        """Return scored research sources from _research_output.json (US-548).

        Reads .spiral/_research_output.json, extracts all URLs, scores them by
        domain authority, and returns [{url, domain, credibility_score, mention_count}].
        Supports ?project_name= to resolve project-specific scratch dir.
        """
        qs = path.partition("?")[2]
        params = urllib.parse.parse_qs(qs)
        project_name = params.get("project_name", [""])[0]

        scratch_dir = ".spiral"
        if project_name and project_name in self._projects:
            root = self._projects[project_name].get("root", "")
            if root:
                scratch_dir = os.path.join(root, ".spiral")

        research_file = os.path.join(scratch_dir, "_research_output.json")

        try:
            with open(research_file, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError):
            await self._send_json(writer, 200, {"sources": [], "error": "No research output found"})
            return

        sources = extract_sources(data)
        await self._send_json(writer, 200, {"sources": sources})

    async def _handle_project_progress(self, project_name: str, writer: asyncio.StreamWriter) -> None:
        """Return progress summary for a project by reading its prd.json."""
        # Resolve project root
        root = ""
        combined: dict[str, dict] = {}  # type: ignore[type-arg]
        registry_path = os.path.join(os.path.expanduser("~"), ".spiral", "ui-projects.json")
        try:
            with open(registry_path, encoding="utf-8") as f:
                reg = json.load(f)
            for name, r in reg.items():
                combined[name] = {"name": name, "root": str(r)}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        combined.update(self._projects)
        if project_name in combined:
            root = combined[project_name].get("root", "")

        if not root:
            await self._send_error(writer, 404, f"Project '{project_name}' not registered")
            return

        # Normalize Git Bash paths (/c/Users/...) to Windows (C:/Users/...)
        if re.match(r"^/[a-zA-Z]/", root):
            root = root[1].upper() + ":" + root[2:]

        prd_path = os.path.join(root, "prd.json")
        try:
            with open(prd_path, encoding="utf-8") as f:
                prd = json.load(f)
        except (OSError, json.JSONDecodeError):
            await self._send_error(writer, 500, f"Cannot read prd.json at {prd_path}")
            return

        stories = prd.get("userStories", [])
        total = len(stories)
        passed = sum(1 for s in stories if s.get("passes"))
        pending = sum(1 for s in stories if not s.get("passes") and not s.get("_skipped") and not s.get("_decomposed"))
        skipped = sum(1 for s in stories if s.get("_skipped"))
        pass_pct = round(passed / total * 100, 1) if total else 0.0

        # Read checkpoint for iteration info
        checkpoint_path = os.path.join(root, ".spiral", "_checkpoint.json")
        iteration = 0
        run_id = ""
        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                cp = json.load(f)
            iteration = cp.get("iteration", 0)
            run_id = cp.get("run_id", "")
        except (OSError, json.JSONDecodeError):
            pass

        # Build pending stories list
        pending_stories = [
            {"id": s.get("id", "?"), "title": s.get("title", ""), "priority": s.get("priority", 99)}
            for s in stories
            if not s.get("passes") and not s.get("_skipped") and not s.get("_decomposed")
        ]
        pending_stories.sort(key=lambda x: x["priority"])

        progress_html = _PROGRESS_HTML.replace("{{PROJECT}}", escape(project_name))
        progress_html = progress_html.replace("{{TOTAL}}", str(total))
        progress_html = progress_html.replace("{{PASSED}}", str(passed))
        progress_html = progress_html.replace("{{PENDING}}", str(pending))
        progress_html = progress_html.replace("{{SKIPPED}}", str(skipped))
        progress_html = progress_html.replace("{{PASS_PCT}}", str(pass_pct))
        progress_html = progress_html.replace("{{ITERATION}}", str(iteration))
        progress_html = progress_html.replace("{{RUN_ID}}", escape(run_id))

        rows = ""
        for s in pending_stories:
            rows += f'<tr><td>{escape(str(s["id"]))}</td><td>{escape(s["title"])}</td><td>{s["priority"]}</td></tr>\n'
        progress_html = progress_html.replace("{{PENDING_ROWS}}", rows if rows else '<tr><td colspan="3">All stories complete!</td></tr>')

        await self._send_html(writer, 200, progress_html)

    async def _handle_index(self, writer: asyncio.StreamWriter) -> None:
        """Return HTML index listing registered projects."""
        # Merge persistent registry (~/.spiral/ui-projects.json) with in-memory projects
        combined: dict[str, dict] = {}  # type: ignore[type-arg]
        registry_path = os.path.join(os.path.expanduser("~"), ".spiral", "ui-projects.json")
        try:
            with open(registry_path, encoding="utf-8") as f:
                reg = json.load(f)
            for name, root in reg.items():
                combined[name] = {"name": name, "root": str(root)}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        combined.update(self._projects)  # in-memory takes precedence

        rows = ""
        for name in sorted(combined):
            rows += f'<li><a href="/{escape(name)}">{escape(name)}</a></li>\n'
        if not rows:
            rows = "<li><em>No projects registered yet. Run <code>spiral.sh</code> to register.</em></li>\n"
        html = _INDEX_HTML.replace("{{ROWS}}", rows)
        await self._send_html(writer, 200, html)

    async def _handle_project_dashboard(self, project_name: str, writer: asyncio.StreamWriter) -> None:
        """Redirect to the Vite React dashboard which has the full UI (11 tabs).

        The full project dashboard (progress, tokens, skills, constitution, etc.)
        lives in the Vite React app (spiral-ui/, port 5299 by default). This Python
        server only handles SSE streaming APIs and worker management — it should NOT
        render its own dashboard HTML for /{project_name} routes.

        Previously this method rendered a basic HTML page with only worker cards,
        which caused confusion when users visited port 5300 expecting the full
        tabbed dashboard. The redirect ensures users always land on the correct UI
        regardless of which port they visit.
        """
        # Resolve the Vite React dashboard port from env, defaulting to 5299.
        # SPIRAL_VITE_PORT is the canonical var; SPIRAL_UI_PORT kept for compat.
        vite_port = os.environ.get("SPIRAL_VITE_PORT") or os.environ.get("SPIRAL_UI_PORT", "5299")
        redirect_url = f"http://localhost:{vite_port}/{urllib.parse.quote(project_name)}"
        await self._send_redirect(writer, redirect_url)

    # ── Low-level response helpers ────────────────────────────────────────────

    async def _send_redirect(self, writer: asyncio.StreamWriter, url: str) -> None:
        """Send a 302 Found redirect to the given URL."""
        body = f'<a href="{escape(url)}">Redirecting to dashboard…</a>'.encode("utf-8")
        response = (
            "HTTP/1.1 302 Found\r\n"
            f"Location: {url}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(response.encode("utf-8"))
        writer.write(body)
        await writer.drain()

    async def _send_html(self, writer: asyncio.StreamWriter, status: int, html: str) -> None:
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
        self,
        writer: asyncio.StreamWriter,
        status: int,
        data: Any,
    ) -> None:
        body = json.dumps(data).encode("utf-8")
        phrase = {200: "OK", 400: "Bad Request", 404: "Not Found", 409: "Conflict", 500: "Internal Server Error"}.get(
            status, "Unknown"
        )
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

    async def _send_error(self, writer: asyncio.StreamWriter, status: int, message: str) -> None:
        await self._send_json(writer, status, {"error": message})

    # ── Server lifecycle ──────────────────────────────────────────────────────

    async def serve(self) -> None:
        """Start the server and run until interrupted."""
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname() if server.sockets else (self.host, self.port)
        print(
            f"[spiral_live_server] Listening on http://{addr[0]}:{addr[1]}/",
            flush=True,
        )
        async with server:
            await server.serve_forever()


# ── HTML Templates ────────────────────────────────────────────────────────────

_PROGRESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SPIRAL Progress — {{PROJECT}}</title>
<meta http-equiv="refresh" content="30">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',monospace;background:#0d1117;color:#c9d1d9;padding:2rem}
h1{color:#58a6ff;margin-bottom:.5rem;font-size:1.4rem}
h2{color:#8b949e;margin-bottom:1rem;font-size:1rem;font-weight:normal}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:2rem}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem;text-align:center}
.stat-value{font-size:2rem;font-weight:bold;color:#e6edf3}
.stat-label{font-size:.75rem;color:#8b949e;margin-top:.25rem}
.stat-pass .stat-value{color:#56d364}
.stat-pct .stat-value{color:#58a6ff}
.stat-pending .stat-value{color:#e3b341}
.stat-skip .stat-value{color:#8b949e}
.progress-bar{background:#21262d;border-radius:4px;height:24px;margin-bottom:2rem;overflow:hidden;position:relative}
.progress-fill{background:linear-gradient(90deg,#238636,#56d364);height:100%;transition:width .5s;border-radius:4px}
.progress-text{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:.8rem;font-weight:bold;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.5)}
table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden}
th{background:#21262d;color:#8b949e;text-align:left;padding:.5rem .75rem;font-size:.75rem;text-transform:uppercase}
td{padding:.5rem .75rem;border-top:1px solid #30363d;font-size:.85rem}
tr:hover td{background:#1c2128}
.back{color:#58a6ff;text-decoration:none;font-size:.85rem;display:inline-block;margin-bottom:1rem}
.back:hover{text-decoration:underline}
.meta{color:#8b949e;font-size:.75rem;margin-bottom:1.5rem}
</style>
</head>
<body>
<a class="back" href="/">&larr; All projects</a> &middot; <a class="back" href="/{{PROJECT}}">Live dashboard</a>
<h1>{{PROJECT}} — Progress</h1>
<p class="meta">Run {{RUN_ID}} &middot; Iteration {{ITERATION}} &middot; Auto-refreshes every 30s</p>
<div class="stats">
  <div class="stat stat-pass"><div class="stat-value">{{PASSED}}</div><div class="stat-label">Passed</div></div>
  <div class="stat stat-pending"><div class="stat-value">{{PENDING}}</div><div class="stat-label">Pending</div></div>
  <div class="stat stat-skip"><div class="stat-value">{{SKIPPED}}</div><div class="stat-label">Skipped</div></div>
  <div class="stat stat-pct"><div class="stat-value">{{PASS_PCT}}%</div><div class="stat-label">Pass Rate</div></div>
</div>
<div class="progress-bar"><div class="progress-fill" style="width:{{PASS_PCT}}%"></div><div class="progress-text">{{PASSED}} / {{TOTAL}}</div></div>
<h2>Pending Stories</h2>
<table>
<thead><tr><th>ID</th><th>Title</th><th>Priority</th></tr></thead>
<tbody>
{{PENDING_ROWS}}
</tbody>
</table>
</body>
</html>
"""

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
  <div class="worker-meta" id="meta-{{WID}}">
    <span class="meta-story">\u2013</span>
    <span class="meta-phase">\u2013</span>
    <span class="meta-completed">0 done</span>
    <span class="meta-mem">\u2013 MB</span>
    <span class="meta-hb">hb \u2013s ago</span>
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
.worker-meta{display:flex;gap:8px;padding:6px 10px;background:#161b22;border-bottom:1px solid #30363d;font-size:11px;font-family:monospace;flex-wrap:wrap;align-items:center}
.meta-story{color:#58a6ff;font-weight:bold}
.meta-phase{color:#d2a8ff;background:#2d1f66;padding:1px 6px;border-radius:10px}
.meta-completed{color:#56d364}
.meta-mem{color:#8b949e}
.meta-hb{color:#8b949e}
.meta-hb.stale{color:#f85149}
.meta-hb.warn{color:#e3b341}
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
  // Poll heartbeat status every 5s to update metadata bars
  var PROJECT_NAME = "{{PROJECT}}";
  function pollWorkersStatus() {
    fetch("/api/workers-status?project_name=" + encodeURIComponent(PROJECT_NAME))
      .then(function(r){ return r.json(); })
      .then(function(data){
        data.workers.forEach(function(w){
          var meta = document.getElementById("meta-" + w.worker_id);
          if (!meta) return;
          meta.querySelector(".meta-story").textContent = w.storyId || "\u2013";
          meta.querySelector(".meta-phase").textContent = w.phase || "\u2013";
          meta.querySelector(".meta-completed").textContent = (w.completed != null ? w.completed : 0) + " done";
          meta.querySelector(".meta-mem").textContent = w.memMb ? w.memMb + " MB" : "\u2013 MB";
          var hbEl = meta.querySelector(".meta-hb");
          hbEl.textContent = "hb " + w.heartbeat_age_sec + "s ago";
          hbEl.className = "meta-hb" + (w.stale ? " stale" : w.heartbeat_age_sec > 60 ? " warn" : "");
        });
      })
      .catch(function(){});
  }
  setInterval(pollWorkersStatus, 5000);
  pollWorkersStatus();
})();
</script>
</body>
</html>
"""


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SPIRAL live SSE streaming server (US-277, US-481)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")

    # PORT ALLOCATION:
    #   5299 = Vite React dashboard (spiral-ui/) — DO NOT use for this server
    #   5300 = This Python SSE server (default)
    # SPIRAL_DASHBOARD_PORT overrides the default. SPIRAL_UI_PORT is legacy compat.
    default_port_str = __import__("os").environ.get("SPIRAL_DASHBOARD_PORT") or "5300"
    parser.add_argument(
        "--port",
        type=int,
        default=int(default_port_str),
        help="Port to listen on (default: $SPIRAL_DASHBOARD_PORT or 5300)",
    )
    args = parser.parse_args()

    # Guard: warn if started on the Vite React dashboard port (5299) to prevent
    # this server from shadowing the full tabbed UI. This was the root cause of
    # the dashboard showing a bare worker page instead of the 11-tab React app.
    vite_port = int(os.environ.get("SPIRAL_VITE_PORT", "5299"))
    if args.port == vite_port:
        print(
            f"[spiral_live_server] WARNING: Port {args.port} is reserved for the "
            f"Vite React dashboard (spiral-ui/). This server should run on a "
            f"different port (default 5300). The React dashboard will not be "
            f"reachable while this server occupies port {args.port}.",
            flush=True,
        )

    server = SpiralLiveServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        print("\n[spiral_live_server] Stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
