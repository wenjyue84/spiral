#!/usr/bin/env python3
"""api.py — FastAPI application for SPIRAL self-monitoring dashboard.

Exposes:
- GET /health — Health check endpoint
- GET /profile — Phase duration analytics endpoint
- GET /api/timeline — Story timeline endpoint with phase swimlanes
- GET /api/dashboard/research-sources — Research source credibility tracking endpoint
- GET /api/dashboard/overview — Unified cross-project metrics endpoint
- GET /api/dashboard/phase-cost-breakdown — Token/cost per phase from results.tsv (US-641)
- WebSocket /ws/cost — Real-time cost delta streaming endpoint
- WebSocket /ws/timeline — Real-time phase transition events
- WebSocket /ws/overview — Real-time cross-project overview updates
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..analyze_results import parse_research_cache
from ..research_source_scorer import extract_sources
from ..spiral.dashboard.aggregator import aggregate_overview
from .alerts_broadcaster import get_alerts_manager
from .cost_broadcaster import get_manager
from .timeline import get_timeline_manager, parse_timeline
from .timeseries_store import query_timeseries

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="SPIRAL Dashboard API", version="1.0.0")


class _APIKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key auth activated when SPIRAL_DASHBOARD_API_KEY env var is set."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        api_key = os.environ.get("SPIRAL_DASHBOARD_API_KEY")
        if api_key and request.url.path != "/health":
            provided = request.headers.get("X-API-Key", "")
            if not provided:
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            if provided != api_key:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)


app.add_middleware(_APIKeyMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/profile")
async def profile() -> dict[str, Any]:
    """Phase duration analytics endpoint.

    Returns JSON with:
    - mean_phase_durations: dict with decompose_secs, impl_secs, verify_secs means
    - slowest_stories: list of top 5 stories by total duration
    - escalation_frequency: dict mapping story_id to escalation count
    """
    results_path = Path(".spiral/results.tsv")

    # Initialize response with defaults
    response: dict[str, Any] = {
        "mean_phase_durations": {
            "decompose_secs": 0.0,
            "impl_secs": 0.0,
            "verify_secs": 0.0,
        },
        "slowest_stories": [],
        "escalation_frequency": {},
    }

    # Return defaults if results.tsv doesn't exist
    if not results_path.exists():
        return response

    try:
        # Parse results.tsv
        decompose_times = []
        impl_times = []
        verify_times = []
        story_durations: dict[str, float] = {}
        escalation_count: dict[str, int] = {}

        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return response

            for row in reader:
                # Calculate mean phase durations
                try:
                    decompose_sec = float(row.get("decompose_secs", 0) or 0)
                    impl_sec = float(row.get("impl_secs", 0) or 0)
                    verify_sec = float(row.get("verify_secs", 0) or 0)

                    decompose_times.append(decompose_sec)
                    impl_times.append(impl_sec)
                    verify_times.append(verify_sec)
                except (ValueError, TypeError):
                    # Skip rows with non-numeric values
                    continue

                # Calculate slowest stories
                story_id = row.get("story_id", "unknown")
                total_duration = decompose_sec + impl_sec + verify_sec
                if story_id in story_durations:
                    story_durations[story_id] += total_duration
                else:
                    story_durations[story_id] = total_duration

                # Calculate escalation frequency
                try:
                    escalation = int(row.get("retry_escalation_count", 0) or 0)
                    if escalation > 0:
                        escalation_count[story_id] = escalation_count.get(story_id, 0) + escalation
                except (ValueError, TypeError):
                    pass

        # Calculate means
        if decompose_times:
            response["mean_phase_durations"]["decompose_secs"] = sum(decompose_times) / len(decompose_times)
        if impl_times:
            response["mean_phase_durations"]["impl_secs"] = sum(impl_times) / len(impl_times)
        if verify_times:
            response["mean_phase_durations"]["verify_secs"] = sum(verify_times) / len(verify_times)

        # Get slowest 5 stories
        slowest = sorted(story_durations.items(), key=lambda x: x[1], reverse=True)[:5]
        response["slowest_stories"] = [{"story_id": sid, "total_duration": duration} for sid, duration in slowest]

        # Set escalation frequency
        response["escalation_frequency"] = escalation_count

    except Exception as e:
        logger.error(f"[/profile] Error parsing results.tsv: {e}")
        # Return defaults on error

    return response


@app.get("/api/timeline")
async def timeline(iterations: int = 3) -> dict[str, Any]:
    """Story Status Timeline Endpoint with Phase Swimlanes.

    Returns story attempt history grouped by iteration and phase.

    Query Parameters:
        iterations: Number of recent iterations to return (default: 3)

    Returns JSON with array of timeline events:
        [{
            "story_id": "US-123",
            "iteration": 0,
            "phase": "I",
            "status": "passed",
            "start_time": "2026-03-20T...",
            "end_time": null,
            "duration_ms": 5000,
            "model_used": "haiku"
        }]
    """
    results_path = Path(".spiral/results.tsv")
    events = parse_timeline(results_path, iterations_limit=max(1, iterations))

    return {
        "iterations_requested": iterations,
        "events": [e.to_dict() for e in events],
        "total_events": len(events),
    }


@app.get("/api/dashboard/research-cache")
async def research_cache_endpoint(
    start_iteration: int = 0,
    end_iteration: Optional[int] = None,
) -> dict[str, Any]:
    """Research cache hit rate trends and time savings endpoint.

    Returns JSON with:
    - hit_rate: fraction of queries served from cache
    - total_queries: total research queries parsed
    - cached: number of cache hits
    - time_saved_seconds: estimated seconds saved by cache hits
    - trend: list of {iteration, hit_rate} per iteration
    """
    results_path = Path(".spiral/results.tsv")
    return parse_research_cache(results_path, start_iteration, end_iteration)


@app.get("/api/dashboard/research-sources")
async def research_sources_endpoint() -> dict[str, Any]:
    """Research Source Authority Tracking Endpoint.

    Extracts research URLs from _research_output.json and scores them by domain credibility.
    Returns array of sources with credibility scores and mention counts.

    Returns JSON array:
        [{
            "url": "https://example.com/article",
            "domain": "example.com",
            "credibility_score": 80,
            "mention_count": 3
        }]

    Sorting:
        - By credibility_score descending (then mention_count descending)
    """
    research_output_path = Path(".spiral/_research_output.json")
    results_path = Path(".spiral/research_sources.json")

    # Handle missing research output file
    if not research_output_path.exists():
        return {"sources": [], "total_sources": 0, "message": "No research output available"}

    try:
        # Load research output
        with open(research_output_path, "r", encoding="utf-8") as f:
            research_data = json.load(f)

        # Extract and score sources
        sources = extract_sources(research_data)

        # Persist results
        results_path.parent.mkdir(parents=True, exist_ok=True)
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2)

        return {
            "sources": sources,
            "total_sources": len(sources),
        }

    except json.JSONDecodeError as e:
        logger.error(f"[/api/dashboard/research-sources] Malformed JSON in _research_output.json: {e}")
        return {
            "sources": [],
            "total_sources": 0,
            "error": f"Malformed JSON in research output: {str(e)}",
        }
    except Exception as e:
        logger.error(f"[/api/dashboard/research-sources] Error processing research sources: {e}")
        return {
            "sources": [],
            "total_sources": 0,
            "error": f"Error processing research sources: {str(e)}",
        }


# Per-token cost rates by model family (US-641)
_PHASE_COST_RATE: dict[str, float] = {"haiku": 2.5e-7, "sonnet": 3e-6, "opus": 1.5e-5}


@app.get("/api/dashboard/phase-cost-breakdown")
async def phase_cost_breakdown() -> dict[str, Any]:
    """Token/cost breakdown per phase from results.tsv (US-641).

    Groups all implementation records as 'Phase I' (results.tsv has no phase_id column).
    Returns model distribution percentages, total tokens, and estimated cost per phase.
    """
    from ..results_tsv import parse_results_tsv

    records = parse_results_tsv("results.tsv")
    phases: dict[str, dict[str, Any]] = {}
    for r in records:
        phase = "Phase I"
        tokens = sum(
            int(v) if v else 0
            for v in (r.cache_read_tokens, r.cache_creation_tokens, r.review_tokens)
        )
        model = r.model or "haiku"
        rate = _PHASE_COST_RATE.get(model.lower().split("-")[0], _PHASE_COST_RATE["haiku"])
        if phase not in phases:
            phases[phase] = {"tokens": 0, "cost": 0.0, "count": 0, "models": {}}
        phases[phase]["tokens"] += tokens
        phases[phase]["cost"] += tokens * rate
        phases[phase]["count"] += 1
        phases[phase]["models"][model] = phases[phase]["models"].get(model, 0) + 1
    result = []
    for phase, d in phases.items():
        n = d["count"] or 1
        result.append({
            "phase": phase,
            "token_count": d["tokens"],
            "cost_usd": round(d["cost"], 6),
            "model_dist": {m: round(c / n, 4) for m, c in d["models"].items()},
            "story_count": d["count"],
        })
    return {"phases": result}


@app.get("/api/dashboard/cost-history")
async def cost_history() -> dict[str, Any]:
    """Historical cost trends by iteration from results.tsv (US-645).

    Groups results.tsv records by spiral_iter and computes total tokens,
    estimated cost, and running cumulative cost per iteration, sorted ascending.
    """
    from ..results_tsv import parse_results_tsv

    records = parse_results_tsv("results.tsv")
    iter_data: dict[int, dict[str, Any]] = {}
    for r in records:
        try:
            iter_num = int(r.spiral_iter)
        except (ValueError, TypeError):
            continue
        tokens = sum(
            int(v) if v else 0
            for v in (r.cache_read_tokens, r.cache_creation_tokens, r.review_tokens)
        )
        model = r.model or "haiku"
        rate = _PHASE_COST_RATE.get(model.lower().split("-")[0], _PHASE_COST_RATE["haiku"])
        if iter_num not in iter_data:
            iter_data[iter_num] = {"tokens": 0, "cost": 0.0}
        iter_data[iter_num]["tokens"] += tokens
        iter_data[iter_num]["cost"] += tokens * rate

    result = []
    cumulative = 0.0
    for iter_num in sorted(iter_data.keys()):
        d = iter_data[iter_num]
        cumulative += d["cost"]
        result.append({
            "iteration": iter_num,
            "total_tokens": d["tokens"],
            "total_cost": round(d["cost"], 6),
            "cumulative_cost": round(cumulative, 6),
        })
    return {"history": result}


@app.get("/api/dashboard/error-breakdown")
async def error_breakdown(
    iterations: int = 5,
    iteration: Optional[int] = None,
) -> dict[str, Any]:
    """Error breakdown by phase and category endpoint.

    Aggregates results.tsv failures by phase (R/T/S/M/I/V/C) and error
    category (timeout, oom, validation_error, model_error, file_conflict).

    Query Parameters:
        iterations: Number of recent iterations to include (default: 5, min: 1).
                    Ignored when `iteration` is specified.
        iteration:  Filter to a single specific iteration number (>= 1).

    Returns:
        {
            "phases": {
                "I": {"timeout": 3, "model_error": 1},
                "R": {"oom": 2}
            },
            "total_errors": 6,
            "iterations_filter": {"mode": "last_n", "n": 5}
        }
    """
    # Validate parameters
    if iteration is not None and iteration < 1:
        raise HTTPException(status_code=422, detail="iteration must be an integer >= 1")
    if iterations < 1:
        raise HTTPException(status_code=422, detail="iterations must be an integer >= 1")

    results_path = Path(".spiral/results.tsv")
    response: dict[str, Any] = {
        "phases": {},
        "total_errors": 0,
        "iterations_filter": (
            {"mode": "single", "iteration": iteration} if iteration is not None else {"mode": "last_n", "n": iterations}
        ),
    }

    if not results_path.exists():
        return response

    # Status values that indicate failure
    failure_statuses = {"failed", "reject", "error", "timeout", "oom", "skip"}

    # Category inference from status when error_type column is absent
    def _infer_category(status: str, model: str) -> str:
        s = status.lower()
        if s in ("timeout",):
            return "timeout"
        if s in ("oom",):
            return "oom"
        if s in ("skip", "skipped"):
            return "validation_error"
        if model:
            return "model_error"
        return "model_error"

    try:
        rows: list[dict[str, str]] = []
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return response
            fields = set(reader.fieldnames)
            has_phase = "phase" in fields
            has_error_type = "error_type" in fields

            for row in reader:
                status = (row.get("status") or "").lower()
                if status not in failure_statuses:
                    continue
                rows.append(dict(row))

        if not rows:
            return response

        # Determine iteration range
        if iteration is not None:
            target_iters = {str(iteration)}
        else:
            iter_nums = sorted(
                {int(r["spiral_iter"]) for r in rows if r.get("spiral_iter", "").isdigit()},
                reverse=True,
            )
            cutoff = iter_nums[iterations - 1] if len(iter_nums) >= iterations else (iter_nums[-1] if iter_nums else 0)
            target_iters = {str(i) for i in iter_nums if i >= cutoff}

        # Aggregate
        phases: dict[str, dict[str, int]] = {}
        story_ids: dict[str, dict[str, list[str]]] = {}
        total = 0
        for row in rows:
            row_iter = row.get("spiral_iter", "")
            if target_iters and row_iter not in target_iters:
                continue

            phase = row.get("phase", "I") if has_phase else "I"
            if not phase:
                phase = "I"

            if has_error_type:
                category = (row.get("error_type") or "model_error").lower()
            else:
                category = _infer_category(
                    row.get("status", ""),
                    row.get("model", ""),
                )

            if phase not in phases:
                phases[phase] = {}
            phases[phase][category] = phases[phase].get(category, 0) + 1

            # Track story IDs per phase/category for drill-down
            sid = row.get("story_id", "")
            if sid:
                if phase not in story_ids:
                    story_ids[phase] = {}
                if category not in story_ids[phase]:
                    story_ids[phase][category] = []
                if sid not in story_ids[phase][category]:
                    story_ids[phase][category].append(sid)

            total += 1

        response["phases"] = phases
        response["story_ids"] = story_ids
        response["total_errors"] = total

    except Exception as e:
        logger.error(f"[/api/dashboard/error-breakdown] Error: {e}")

    return response


@app.get("/api/dashboard/timeseries")
async def timeseries_endpoint(
    metric: str = "phase_duration",
    phase: Optional[str] = None,
    window: str = "30d",
) -> dict[str, Any]:
    """Time-series metrics endpoint for trend analysis.

    Query Parameters:
        metric: 'phase_duration' | 'story_throughput' | 'worker_memory'
        phase: Phase letter filter, e.g. 'R', 'I' (only for phase_duration)
        window: Lookback window, e.g. '30d', '7d', '1d' (default: '30d')

    Returns:
        {"metric": "phase_duration", "phase": "R", "window": "30d",
         "data": [{"timestamp": "...", "value": 12.3}, ...]}
    """
    # Parse window string like "30d", "7d" into days
    window_days = 30
    if window.endswith("d"):
        try:
            window_days = max(1, int(window[:-1]))
        except ValueError:
            window_days = 30

    db_path = Path(".spiral/dashboard.db")
    data = query_timeseries(metric=metric, phase=phase, window_days=window_days, db_path=db_path)
    return {
        "metric": metric,
        "phase": phase,
        "window": window,
        "data": data,
        "total_points": len(data),
    }


@app.websocket("/ws/cost")
async def websocket_cost_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time cost delta streaming.

    Clients connect to /ws/cost and receive JSON messages of the form:
        {"story_id": "US-123", "cost_delta": 0.25, "timestamp": "2026-03-19T..."}

    Requires X-API-Key header if SPIRAL_DASHBOARD_API_KEY is set.
    Connection is maintained until client disconnects or an error occurs.
    """
    # Check authentication if enabled
    api_key = os.environ.get("SPIRAL_DASHBOARD_API_KEY")
    if api_key:
        provided = websocket.headers.get("x-api-key", "")
        if not provided:
            await websocket.close(code=1008, reason="Authentication required")
            return
        if provided != api_key:
            await websocket.close(code=1008, reason="Forbidden")
            return

    manager = get_manager()
    await manager.connect(websocket)
    try:
        # Keep connection alive; receive messages (echo back or ignore)
        while True:
            data = await websocket.receive_text()
            # Echo back or handle client messages if needed
            logger.debug(f"[ws/cost] Received from client: {data}")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.debug("[ws/cost] Client disconnected")
    except Exception as e:
        await manager.disconnect(websocket)
        logger.error(f"[ws/cost] Error: {e}")


@app.websocket("/ws/timeline")
async def websocket_timeline_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time phase transition events.

    Clients connect to /ws/timeline and receive JSON messages of the form:
        {
            "event": "phase_change",
            "story_id": "US-123",
            "iteration": 0,
            "phase": "I",
            "status": "running",
            "start_time": "2026-03-20T...",
            "end_time": null,
            "duration_ms": 0,
            "model_used": "haiku"
        }

    Connection is maintained until client disconnects or an error occurs.
    """
    manager = get_timeline_manager()
    await manager.connect(websocket)
    try:
        # Keep connection alive; receive messages (echo back or ignore)
        while True:
            data = await websocket.receive_text()
            # Echo back or handle client messages if needed
            logger.debug(f"[ws/timeline] Received from client: {data}")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.debug("[ws/timeline] Client disconnected")
    except Exception as e:
        await manager.disconnect(websocket)
        logger.error(f"[ws/timeline] Error: {e}")


@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time cost ceiling alerts.

    Clients connect to /ws/alerts and receive JSON messages of the form:
        {
            "type": "cost_alert",
            "severity": "warning"|"critical",
            "current_cost": 15.5,
            "ceiling": 20.0,
            "percent_used": 77.5,
            "timestamp": "2026-03-20T..."
        }

    Requires X-API-Key header if SPIRAL_DASHBOARD_API_KEY is set.
    Connection is maintained until client disconnects or an error occurs.
    """
    # Check authentication if enabled
    api_key = os.environ.get("SPIRAL_DASHBOARD_API_KEY")
    if api_key:
        provided = websocket.headers.get("x-api-key", "")
        if not provided:
            await websocket.close(code=1008, reason="Authentication required")
            return
        if provided != api_key:
            await websocket.close(code=1008, reason="Forbidden")
            return

    manager = get_alerts_manager()
    await manager.connect(websocket)
    try:
        # Keep connection alive; receive messages (echo back or ignore)
        while True:
            data = await websocket.receive_text()
            # Echo back or handle client messages if needed
            logger.debug(f"[ws/alerts] Received from client: {data}")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.debug("[ws/alerts] Client disconnected")
    except Exception as e:
        await manager.disconnect(websocket)
        logger.error(f"[ws/alerts] Error: {e}")


def _discover_results_paths() -> list[Path]:
    """Discover all results.tsv files in the current project and known sub-project dirs.

    Looks for:
    1. .spiral/results.tsv (primary single-project location)
    2. results.tsv (legacy root location)
    3. .spiral-workers/*/results.tsv (parallel worker directories)
    """
    candidates: list[Path] = [
        Path(".spiral/results.tsv"),
        Path("results.tsv"),
    ]
    # Include worker worktree results when parallel workers are used
    for worker_tsv in Path(".spiral-workers").glob("*/results.tsv"):
        candidates.append(worker_tsv)

    return [p for p in candidates if p.exists()]


@app.get("/api/dashboard/overview")
async def dashboard_overview() -> dict[str, Any]:
    """Unified cross-project metrics endpoint.

    Aggregates metrics from all discovered results.tsv files (root project and
    sub-projects / parallel workers). Reads fresh data on each call so the
    response always reflects the latest state.

    Returns:
        {
            "totalCost": float,           # summed estimated cost (USD)
            "storiesPassed": int,         # keep-status rows across all projects
            "avgPhaseTime": float,        # mean duration_sec (seconds)
            "blockerCount": int,          # non-keep rows (failures/rejects)
            "slowestSubProject": str,     # sub-project directory with highest avg duration
            "escalationPct": float,       # fraction of rows with retry_num >= 1
            "subProjectCount": int,       # number of results.tsv files included
        }
    """
    paths = _discover_results_paths()
    return aggregate_overview(paths)


@app.websocket("/ws/overview")
async def websocket_overview_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time cross-project overview updates.

    Clients connect to /ws/overview and receive the current overview payload
    as a JSON message immediately on connect, then on every client ping.

    Message format:
        {"totalCost": ..., "storiesPassed": ..., "avgPhaseTime": ...,
         "blockerCount": ..., "slowestSubProject": "...", "escalationPct": ...,
         "subProjectCount": ...}
    """
    # Check auth if enabled
    api_key = os.environ.get("SPIRAL_DASHBOARD_API_KEY")
    if api_key:
        provided = websocket.headers.get("x-api-key", "")
        if not provided:
            await websocket.close(code=1008, reason="Authentication required")
            return
        if provided != api_key:
            await websocket.close(code=1008, reason="Forbidden")
            return

    await websocket.accept()
    try:
        # Send current metrics immediately on connect
        paths = _discover_results_paths()
        await websocket.send_json(aggregate_overview(paths))

        # Refresh and push on every client message (acts as a poll trigger)
        while True:
            await websocket.receive_text()
            paths = _discover_results_paths()
            await websocket.send_json(aggregate_overview(paths))
    except WebSocketDisconnect:
        logger.debug("[ws/overview] Client disconnected")
    except Exception as e:
        logger.error(f"[ws/overview] Error: {e}")


# Export for use in tests and main application
__all__ = ["app", "get_manager", "get_timeline_manager", "get_alerts_manager"]
