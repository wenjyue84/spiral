#!/usr/bin/env python3
"""api.py — FastAPI application for SPIRAL self-monitoring dashboard.

Exposes:
- GET /health — Health check endpoint
- GET /profile — Phase duration analytics endpoint
- GET /api/timeline — Story timeline endpoint with phase swimlanes
- GET /api/dashboard/research-sources — Research source credibility tracking endpoint
- WebSocket /ws/cost — Real-time cost delta streaming endpoint
- WebSocket /ws/timeline — Real-time phase transition events
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..analyze_results import parse_research_cache
from ..research_source_scorer import extract_sources
from .cost_broadcaster import get_manager
from .timeline import get_timeline_manager, parse_timeline

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


# Export for use in tests and main application
__all__ = ["app", "get_manager", "get_timeline_manager"]
