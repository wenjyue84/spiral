"""US-455: Routing telemetry emission for spiral_events.jsonl."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def emit_routing_event(
    events_path: str,
    story_id: str,
    complexity_score: int,
    model_tier: str,
    estimated_tokens: int = 0,
) -> None:
    """Append a single route_story_assigned event to the events JSONL file."""
    record = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "type": "route_story_assigned",
        "story_id": story_id,
        "complexity_score": complexity_score,
        "model_tier": model_tier,
        "estimated_tokens": estimated_tokens,
    }
    parent = os.path.dirname(os.path.abspath(events_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(events_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def emit_routing_events(
    events_path: str,
    events: list[dict],
) -> None:
    """Emit multiple routing telemetry events."""
    for ev in events:
        emit_routing_event(
            events_path,
            story_id=ev["story_id"],
            complexity_score=ev["complexity_score"],
            model_tier=ev["model_tier"],
            estimated_tokens=ev.get("estimated_tokens", 0),
        )
    if events:
        print(f"[router] Emitted {len(events)} routing telemetry events to {events_path}")
