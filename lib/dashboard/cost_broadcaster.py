#!/usr/bin/env python3
"""cost_broadcaster.py — Manage WebSocket connections for real-time cost deltas.

Provides a singleton ConnectionManager to track active WebSocket connections
and broadcast cost delta messages to all subscribers when results.tsv is updated.
"""

import asyncio
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients.

        Args:
            message: Dictionary with cost delta data (e.g., {"story_id": "US-123", "cost_usd": 0.25})

        Raises:
            Exception: If any client connection fails (logged but doesn't stop broadcast to others).
        """
        async with self._lock:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    # Client disconnected or error occurred; mark for cleanup
                    disconnected.append(connection)

            # Clean up dead connections
            for conn in disconnected:
                self.active_connections.discard(conn)

    def connection_count(self) -> int:
        """Return number of active connections."""
        return len(self.active_connections)


# Singleton instance
_manager = ConnectionManager()


def get_manager() -> ConnectionManager:
    """Return the singleton ConnectionManager."""
    return _manager


async def broadcast_cost_delta(story_result: dict[str, Any]) -> None:
    """Broadcast a cost delta message based on a story result row.

    Args:
        story_result: Dict with story telemetry (from results.tsv row).
                     Expected to have: story_id, status, duration_sec, model, etc.
    """
    # Calculate cost from tokens if available, otherwise use duration estimate
    # This is a simple model; in production would use detailed cost calculations
    manager = get_manager()

    # Extract key fields
    story_id = story_result.get("story_id", "unknown")
    status = story_result.get("status", "unknown")
    timestamp = story_result.get("timestamp", "")

    # Calculate cost estimate based on model and duration
    # Rough cost calculation: $0.003/minute for haiku, $0.015/minute for sonnet, $0.075/minute for opus
    model = story_result.get("model", "haiku")
    duration_sec = float(story_result.get("duration_sec", 0))
    duration_min = duration_sec / 60.0

    cost_per_min = {"haiku": 0.003, "sonnet": 0.015, "opus": 0.075}.get(model, 0.005)
    cost_usd = cost_per_min * max(duration_min, 0.05)  # Minimum $0.0002.5

    message = {
        "story_id": story_id,
        "status": status,
        "cost_usd": round(cost_usd, 6),
        "model": model,
        "duration_sec": duration_sec,
        "timestamp": timestamp,
    }

    await manager.broadcast(message)
