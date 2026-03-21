#!/usr/bin/env python3
"""story_broadcaster.py — Manage WebSocket connections for real-time story phase change events.

Provides a singleton StoryUpdatesManager to track active WebSocket connections,
manage per-client subscriptions, and broadcast story phase transition events.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket


class StoryUpdatesManager:
    """Manages WebSocket connections and broadcasts story phase change events.

    Clients can subscribe to specific story IDs or '*' for all updates.
    Each connection stores its subscription filter.
    """

    def __init__(self) -> None:
        # Maps websocket -> set of story_ids or {'*'} for all
        self._subscriptions: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Register a new WebSocket connection (no subscription yet)."""
        await websocket.accept()
        async with self._lock:
            self._subscriptions[websocket] = set()

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        async with self._lock:
            self._subscriptions.pop(websocket, None)

    async def subscribe(self, websocket: WebSocket, story_ids: list[str] | str) -> None:
        """Register subscription filter for a connected client.

        Args:
            websocket: The connected WebSocket.
            story_ids: List of story IDs (e.g., ['US-001', 'US-002']) or '*' for all.
        """
        async with self._lock:
            if websocket not in self._subscriptions:
                return
            if story_ids == "*" or story_ids == ["*"]:
                self._subscriptions[websocket] = {"*"}
            else:
                ids = story_ids if isinstance(story_ids, list) else [story_ids]
                self._subscriptions[websocket] = set(ids)

    async def broadcast_phase_change(
        self,
        story_id: str,
        from_phase: str,
        to_phase: str,
        timestamp: str | None = None,
    ) -> None:
        """Broadcast a story phase change event to subscribed clients.

        Args:
            story_id: The story ID that changed phase (e.g., 'US-001').
            from_phase: Previous phase label (e.g., 'S').
            to_phase: New phase label (e.g., 'M').
            timestamp: ISO8601 UTC timestamp; defaults to now.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        message: dict[str, Any] = {
            "story_id": story_id,
            "from_phase": from_phase,
            "to_phase": to_phase,
            "timestamp": timestamp,
        }

        async with self._lock:
            disconnected = []
            for ws, sub in self._subscriptions.items():
                if "*" in sub or story_id in sub:
                    try:
                        await ws.send_json(message)
                    except Exception:
                        disconnected.append(ws)

            for ws in disconnected:
                self._subscriptions.pop(ws, None)

    def connection_count(self) -> int:
        """Return number of active connections."""
        return len(self._subscriptions)


# Singleton instance
_story_updates_manager = StoryUpdatesManager()


def get_story_updates_manager() -> StoryUpdatesManager:
    """Return the singleton StoryUpdatesManager."""
    return _story_updates_manager


async def broadcast_phase_change(
    story_id: str,
    from_phase: str,
    to_phase: str,
    timestamp: str | None = None,
) -> None:
    """Module-level helper: broadcast a story phase change to all subscribers.

    Args:
        story_id: Story ID that changed phase.
        from_phase: Previous phase.
        to_phase: New phase.
        timestamp: Optional ISO8601 UTC timestamp.
    """
    manager = get_story_updates_manager()
    await manager.broadcast_phase_change(story_id, from_phase, to_phase, timestamp)
