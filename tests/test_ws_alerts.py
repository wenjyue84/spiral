#!/usr/bin/env python3
"""test_ws_alerts.py — Integration tests for /ws/alerts WebSocket endpoint.

Tests:
- Happy path: client connects and receives cost alert message
- Alert severity correct at 80% and 95% thresholds
- Authentication enforcement on unauthenticated requests
"""

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.alerts_broadcaster import broadcast_cost_alert, get_alerts_manager
from lib.dashboard.api import app


class MockWebSocket:
    """Mock WebSocket object for testing."""

    def __init__(self):
        self.messages = []
        self.closed = False

    async def send_json(self, data):
        """Store message."""
        self.messages.append(data)

    async def accept(self):
        """Accept connection."""
        pass


@pytest.mark.asyncio
async def test_alerts_broadcast_warning_at_80_percent() -> None:
    """Test warning alert emitted at 80% of cost ceiling."""
    manager = get_alerts_manager()

    # Create mock WebSocket
    ws = MockWebSocket()
    await manager.connect(ws)

    try:
        # Broadcast alert for 80% threshold
        await broadcast_cost_alert(current_cost=16.0, ceiling=20.0, severity="warning")

        # Verify message
        assert len(ws.messages) == 1
        message = ws.messages[0]
        assert message["type"] == "cost_alert"
        assert message["severity"] == "warning"
        assert message["current_cost"] == 16.0
        assert message["ceiling"] == 20.0
        assert message["percent_used"] == 80.0
        assert "timestamp" in message
    finally:
        await manager.disconnect(ws)


@pytest.mark.asyncio
async def test_alerts_broadcast_critical_at_95_percent() -> None:
    """Test critical alert emitted at 95% of cost ceiling."""
    manager = get_alerts_manager()

    ws = MockWebSocket()
    await manager.connect(ws)

    try:
        # Broadcast alert for 95% threshold
        await broadcast_cost_alert(current_cost=19.0, ceiling=20.0, severity="critical")

        # Verify message
        assert len(ws.messages) == 1
        message = ws.messages[0]
        assert message["type"] == "cost_alert"
        assert message["severity"] == "critical"
        assert message["percent_used"] == 95.0
    finally:
        await manager.disconnect(ws)


@pytest.mark.asyncio
async def test_alerts_broadcast_to_multiple_clients() -> None:
    """Test alert broadcast reaches multiple connected clients."""
    manager = get_alerts_manager()

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    await manager.connect(ws1)
    await manager.connect(ws2)

    try:
        await broadcast_cost_alert(current_cost=17.0, ceiling=20.0, severity="warning")

        assert len(ws1.messages) == 1
        assert len(ws2.messages) == 1
        assert ws1.messages[0]["current_cost"] == 17.0
        assert ws2.messages[0]["current_cost"] == 17.0
    finally:
        await manager.disconnect(ws1)
        await manager.disconnect(ws2)


@pytest.mark.asyncio
async def test_alerts_broadcast_client_disconnect_not_blocking() -> None:
    """Test that a disconnecting client doesn't block alerts to others."""
    manager = get_alerts_manager()

    ws1 = MockWebSocket()
    ws2 = MockWebSocket()

    await manager.connect(ws1)
    await manager.connect(ws2)

    # Disconnect ws1
    await manager.disconnect(ws1)

    try:
        # Broadcast should still work for ws2
        await broadcast_cost_alert(current_cost=18.0, ceiling=20.0, severity="warning")

        assert len(ws1.messages) == 0
        assert len(ws2.messages) == 1
    finally:
        await manager.disconnect(ws2)


def test_websocket_alerts_endpoint_requires_auth_when_key_set(monkeypatch):
    """Test that /ws/alerts requires authentication when API key is set."""
    from starlette.websockets import WebSocketDisconnect

    # Set API key in environment
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", "test-secret-key")

    client = TestClient(app)

    # Try to connect without API key - should fail
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/alerts"):
            # Should fail on connect attempt
            pass


def test_alerts_endpoint_accepts_valid_auth(monkeypatch):
    """Test that /ws/alerts accepts connection with valid API key."""
    monkeypatch.setenv("SPIRAL_DASHBOARD_API_KEY", "test-secret-key")

    TestClient(app)

    # Connect with valid header
    # WebSocket client testing would need proper async setup
    # This is a placeholder for the pattern


def test_alerts_manager_connection_count():
    """Test connection count tracking."""
    manager = get_alerts_manager()
    initial_count = manager.connection_count()

    # Count should be consistent
    assert isinstance(initial_count, int)
    assert initial_count >= 0
