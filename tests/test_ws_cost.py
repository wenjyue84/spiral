#!/usr/bin/env python3
"""test_ws_cost.py — Integration tests for /ws/cost WebSocket endpoint.

Tests:
- Happy path: client connects and receives cost-delta message within 2s after story completion
- Edge case: client disconnection doesn't block subsequent broadcasts to other clients
"""

import time
from datetime import datetime
from typing import Any, Protocol

import pytest

from lib.dashboard.cost_broadcaster import broadcast_cost_delta, get_manager


class MockWebSocketProtocol(Protocol):
    """Protocol for mock WebSocket objects in tests."""

    messages: list[dict[str, Any]]
    closed: bool
    client_id: int

    async def send_json(self, data: dict[str, Any]) -> None:
        """Send JSON data."""
        ...

    async def accept(self) -> None:
        """Accept connection."""
        ...


@pytest.mark.asyncio
async def test_websocket_broadcast_cost_delta_within_2s() -> None:
    """Test that broadcast delivers cost-delta message within 2s.

    Simulates:
    1. Client connection to manager
    2. Story completion triggering broadcast
    3. Message verification
    """
    manager = get_manager()

    # Simulate client
    class MockWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []
            self.closed = False

        async def send_json(self, data: dict[str, Any]) -> None:
            self.messages.append(data)

        async def accept(self) -> None:
            pass

    ws = MockWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    try:
        # Simulate story completion
        start_time = time.time()
        story_result = {
            "story_id": "US-565",
            "status": "passed",
            "duration_sec": 5.0,
            "model": "haiku",
            "timestamp": datetime.now().isoformat(),
        }
        await broadcast_cost_delta(story_result)
        elapsed = time.time() - start_time

        # Verify message received within 2s
        assert len(ws.messages) == 1
        assert elapsed <= 2.0, f"Broadcast took {elapsed:.2f}s, expected < 2.0s"

        # Verify message schema
        message = ws.messages[0]
        assert "story_id" in message
        assert "cost_delta" in message
        assert "timestamp" in message
        assert message["story_id"] == "US-565"
        assert isinstance(message["cost_delta"], (int, float))
        assert message["cost_delta"] > 0
    finally:
        # Cleanup
        await manager.disconnect(ws)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_websocket_client_disconnect_does_not_block_broadcasts() -> None:
    """Test that a disconnecting client doesn't block broadcasts to others.

    Scenario:
    1. Two clients connect
    2. Client 1 disconnects
    3. Broadcast message
    4. Verify Client 2 still receives (and is not blocked by Client 1's disconnect)
    """
    manager = get_manager()

    # Simulate two clients
    class MockWebSocket:
        def __init__(self, client_id: int) -> None:
            self.client_id = client_id
            self.messages: list[dict[str, Any]] = []
            self.closed = False

        async def send_json(self, data: dict[str, Any]) -> None:
            self.messages.append(data)

        async def accept(self) -> None:
            pass

    ws1 = MockWebSocket(1)
    ws2 = MockWebSocket(2)

    # Connect both
    await manager.connect(ws1)  # type: ignore[arg-type]
    await manager.connect(ws2)  # type: ignore[arg-type]
    assert manager.connection_count() == 2

    try:
        # Client 1 disconnects
        await manager.disconnect(ws1)  # type: ignore[arg-type]
        assert manager.connection_count() == 1

        # Broadcast a message
        story_result = {
            "story_id": "US-566",
            "status": "passed",
            "duration_sec": 3.0,
            "model": "sonnet",
            "timestamp": datetime.now().isoformat(),
        }
        await broadcast_cost_delta(story_result)

        # Client 2 should receive the message
        assert len(ws2.messages) == 1
        message = ws2.messages[0]
        assert message["story_id"] == "US-566"
        assert "cost_delta" in message
        assert "timestamp" in message

        # Client 1 should not have received it (was disconnected)
        assert len(ws1.messages) == 0
    finally:
        # Cleanup
        await manager.disconnect(ws2)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_websocket_multiple_clients_receive_broadcast() -> None:
    """Test that multiple connected clients all receive the same broadcast.

    Scenario:
    1. Three clients connect
    2. Broadcast a message
    3. Verify all three receive the same message
    """
    manager = get_manager()

    class MockWebSocket:
        def __init__(self, client_id: int) -> None:
            self.client_id = client_id
            self.messages: list[dict[str, Any]] = []
            self.closed = False

        async def send_json(self, data: dict[str, Any]) -> None:
            self.messages.append(data)

        async def accept(self) -> None:
            pass

    # Connect 3 clients
    clients = [MockWebSocket(i) for i in range(3)]
    for ws in clients:
        await manager.connect(ws)  # type: ignore[arg-type]

    assert manager.connection_count() == 3

    try:
        # Broadcast a message
        story_result = {
            "story_id": "US-567",
            "status": "passed",
            "duration_sec": 2.0,
            "model": "haiku",
            "timestamp": datetime.now().isoformat(),
        }
        await broadcast_cost_delta(story_result)

        # All clients should receive the message
        for ws in clients:
            assert len(ws.messages) == 1
            message = ws.messages[0]
            assert message["story_id"] == "US-567"
            assert "cost_delta" in message
            assert "timestamp" in message
            assert message["cost_delta"] > 0
    finally:
        # Cleanup
        for ws in clients:
            await manager.disconnect(ws)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_websocket_message_schema_validation() -> None:
    """Test that all messages conform to the required schema.

    Required fields: story_id, cost_delta, timestamp
    """
    manager = get_manager()

    class MockWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []
            self.closed = False

        async def send_json(self, data: dict[str, Any]) -> None:
            self.messages.append(data)

        async def accept(self) -> None:
            pass

    ws = MockWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    try:
        # Send multiple story completions with different models
        story_results = [
            {
                "story_id": "US-568",
                "status": "passed",
                "duration_sec": 1.0,
                "model": "haiku",
                "timestamp": datetime.now().isoformat(),
            },
            {
                "story_id": "US-569",
                "status": "passed",
                "duration_sec": 5.0,
                "model": "sonnet",
                "timestamp": datetime.now().isoformat(),
            },
            {
                "story_id": "US-570",
                "status": "passed",
                "duration_sec": 20.0,
                "model": "opus",
                "timestamp": datetime.now().isoformat(),
            },
        ]

        for story_result in story_results:
            await broadcast_cost_delta(story_result)

        # Validate all messages
        assert len(ws.messages) == 3
        for idx, message in enumerate(ws.messages):
            # Validate required fields
            required_fields = {"story_id", "cost_delta", "timestamp"}
            assert required_fields.issubset(set(message.keys())), \
                f"Message {idx} missing required fields. Got: {message.keys()}"

            # Validate field types
            assert isinstance(message["story_id"], str)
            assert isinstance(message["cost_delta"], (int, float))
            assert isinstance(message["timestamp"], str)

            # Validate story_id matches expected
            assert message["story_id"] == story_results[idx]["story_id"]
            assert message["cost_delta"] > 0
    finally:
        # Cleanup
        await manager.disconnect(ws)  # type: ignore[arg-type]
