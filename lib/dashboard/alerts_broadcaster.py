#!/usr/bin/env python3
"""alerts_broadcaster.py — Manage WebSocket connections for real-time cost ceiling alerts.

Provides a singleton ConnectionManager to track active WebSocket connections
and broadcast cost ceiling alert messages to all subscribers.
"""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import WebSocket


class AlertsConnectionManager:
    """Manages active WebSocket connections and broadcasts alert messages."""

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
            message: Dictionary with alert data.
                     Required keys: type, severity, current_cost, ceiling, percent_used, timestamp.

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
_alerts_manager = AlertsConnectionManager()


def get_alerts_manager() -> AlertsConnectionManager:
    """Return the singleton AlertsConnectionManager."""
    return _alerts_manager


async def broadcast_cost_alert(current_cost: float, ceiling: float, severity: str = "warning") -> None:
    """Broadcast a cost alert message.

    Args:
        current_cost: Current cumulative cost in USD.
        ceiling: SPIRAL_COST_CEILING in USD.
        severity: Alert severity ('warning' at 80%, 'critical' at 95%).
    """
    manager = get_alerts_manager()

    percent_used = (current_cost / ceiling * 100) if ceiling > 0 else 0

    message = {
        "type": "cost_alert",
        "severity": severity,
        "current_cost": round(current_cost, 4),
        "ceiling": round(ceiling, 4),
        "percent_used": round(percent_used, 2),
        "timestamp": datetime.now().isoformat(),
    }

    await manager.broadcast(message)
