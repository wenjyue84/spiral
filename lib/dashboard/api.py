#!/usr/bin/env python3
"""api.py — FastAPI application for SPIRAL self-monitoring dashboard.

Exposes:
- GET /health — Health check endpoint
- GET /profile — Phase duration analytics endpoint
- WebSocket /ws/cost — Real-time cost delta streaming endpoint
"""

import csv
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .cost_broadcaster import get_manager

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="SPIRAL Dashboard API", version="1.0.0")


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


@app.websocket("/ws/cost")
async def websocket_cost_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time cost delta streaming.

    Clients connect to /ws/cost and receive JSON messages of the form:
        {"story_id": "US-123", "cost_usd": 0.25, "timestamp": "2026-03-19T..."}

    Connection is maintained until client disconnects or an error occurs.
    """
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


# Export for use in tests and main application
__all__ = ["app", "get_manager"]
