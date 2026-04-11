"""E2E test for /ws/cost WebSocket endpoint — real-time cost streaming (US-497).

Acceptance criteria for US-1204:
- AC1: E2E test covers the user flow introduced by US-497
- AC2: Test navigates to /ws/cost and asserts on visible state
- AC3: Test passes via FastAPI TestClient (headless WebSocket client)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app
from lib.dashboard.cost_broadcaster import broadcast_cost_delta, get_manager


@pytest.mark.us_497
def test_user_connects_to_ws_cost_endpoint() -> None:
    """AC1/AC2: User navigates to /ws/cost and connection is accepted."""
    client = TestClient(app)
    # Verify endpoint exists and handshake succeeds (no auth configured)
    with client.websocket_connect("/ws/cost") as ws:
        assert ws is not None  # connection established


@pytest.mark.us_497
def test_ws_cost_cost_delta_broadcast_user_flow() -> None:
    """AC1: Full user flow — story completes, cost delta appears within 2s.

    Simulates the Phase I completion event that triggers a broadcast
    to all dashboard clients subscribed to /ws/cost.
    """

    async def _run() -> dict[str, Any]:
        manager = get_manager()
        received: list[dict[str, Any]] = []

        class FakeWS:
            async def send_json(self, data: dict[str, Any]) -> None:
                received.append(data)

            async def accept(self) -> None:
                pass

        ws = FakeWS()
        await manager.connect(ws)  # type: ignore[arg-type]
        try:
            await broadcast_cost_delta(
                {
                    "story_id": "US-497",
                    "status": "passed",
                    "duration_sec": 12.0,
                    "model": "haiku",
                    "timestamp": datetime.now().isoformat(),
                }
            )
        finally:
            await manager.disconnect(ws)  # type: ignore[arg-type]
        return received[0] if received else {}

    msg = asyncio.run(_run())

    # AC2: Assert on visible state — message has expected schema
    assert msg.get("story_id") == "US-497"
    assert "cost_delta" in msg
    assert "timestamp" in msg
    assert isinstance(msg["cost_delta"], float | int)
    assert msg["cost_delta"] > 0


@pytest.mark.us_497
def test_ws_cost_rejects_unauthenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: /ws/cost asserts on visible auth state — unauthenticated user is rejected."""
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", "test-secret")
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/cost", headers={"x-api-key": "wrong"}):
            pass
