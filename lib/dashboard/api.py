#!/usr/bin/env python3
"""api.py — FastAPI application for SPIRAL self-monitoring dashboard.

Exposes:
- GET /health — Health check endpoint
- WebSocket /ws/cost — Real-time cost delta streaming endpoint
"""

import asyncio
import logging
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
