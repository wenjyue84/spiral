#!/usr/bin/env python3
"""timeline.py — Parse and stream story attempt timeline for swimlane visualization.

Provides:
- parse_timeline() — Parse results.tsv into timeline events grouped by iteration/phase
- TimelineManager — Manage WebSocket connections for real-time phase updates
"""

import asyncio
import csv
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Phase order in SPIRAL pipeline
PHASE_ORDER = ["R", "T", "S", "M", "G", "I", "V", "C"]
PHASE_NAMES = {
    "R": "Research",
    "T": "Test Synthesis",
    "S": "Story Validate",
    "M": "Merge",
    "G": "Human Gate",
    "I": "Implement",
    "V": "Validate",
    "C": "Check Done",
}


@dataclass
class TimelineEvent:
    """Represents a story attempt in the timeline."""

    story_id: str
    iteration: int
    phase: str
    status: str  # pending, running, passed, failed
    start_time: Optional[str]
    end_time: Optional[str]
    duration_ms: int
    model_used: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)


class TimelineManager:
    """Manages WebSocket connections for timeline events."""

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

    async def broadcast(self, event: TimelineEvent) -> None:
        """Broadcast a timeline event to all connected clients."""
        async with self._lock:
            disconnected = []
            message = {
                "event": "phase_change",
                **event.to_dict(),
            }
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)

            # Clean up dead connections
            for conn in disconnected:
                self.active_connections.discard(conn)

    def connection_count(self) -> int:
        """Return number of active connections."""
        return len(self.active_connections)


# Singleton instance
_timeline_manager = TimelineManager()


def get_timeline_manager() -> TimelineManager:
    """Get the timeline manager singleton."""
    return _timeline_manager


def parse_timeline(results_path: Path, iterations_limit: int = 10) -> list[TimelineEvent]:
    """Parse results.tsv and return timeline events grouped by iteration and phase.

    Args:
        results_path: Path to results.tsv file
        iterations_limit: Maximum number of recent iterations to return

    Returns:
        List of TimelineEvent objects sorted by iteration, phase, then story_id
    """
    events: list[TimelineEvent] = []

    if not results_path.exists():
        return events

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return events

            for row in reader:
                try:
                    story_id = row.get("story_id", "unknown")
                    iteration = int(row.get("spiral_iter", 0) or 0)
                    status = row.get("status", "unknown")
                    start_time = row.get("timestamp")
                    duration_sec = float(row.get("duration_sec", 0) or 0)
                    model_used = row.get("model")

                    # Map result status to timeline status
                    if status == "accept":
                        timeline_status = "passed"
                    elif status == "reject":
                        timeline_status = "failed"
                    else:
                        timeline_status = "unknown"

                    # Infer phase from story order in iteration
                    # Phase I is most common in results.tsv (all implementation attempts)
                    phase = "I"

                    event = TimelineEvent(
                        story_id=story_id,
                        iteration=iteration,
                        phase=phase,
                        status=timeline_status,
                        start_time=start_time,
                        end_time=None,  # Not tracked in results.tsv
                        duration_ms=int(duration_sec * 1000),
                        model_used=model_used,
                    )
                    events.append(event)
                except (ValueError, TypeError) as e:
                    logger.debug(f"[timeline] Skipping malformed row: {e}")
                    continue

    except Exception as e:
        logger.error(f"[timeline] Error parsing results.tsv: {e}")

    # Filter to recent iterations and sort
    if events:
        max_iteration = max(e.iteration for e in events)
        min_iteration = max(0, max_iteration - iterations_limit + 1)
        events = [e for e in events if e.iteration >= min_iteration]

    # Sort by iteration (asc), phase order, then story_id
    def sort_key(e: TimelineEvent) -> tuple[int, int, str]:
        phase_idx = PHASE_ORDER.index(e.phase) if e.phase in PHASE_ORDER else 999
        return (e.iteration, phase_idx, e.story_id)

    events.sort(key=sort_key)
    return events


__all__ = [
    "TimelineEvent",
    "TimelineManager",
    "parse_timeline",
    "get_timeline_manager",
    "PHASE_ORDER",
    "PHASE_NAMES",
]
