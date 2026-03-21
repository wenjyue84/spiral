#!/usr/bin/env python3
"""test_ws_story_updates.py — Integration tests for /ws/story-updates WebSocket endpoint.

Tests:
- Wildcard subscriber receives all phase change events
- Specific story_id subscriber receives matching events only
- Integration test: 2 connected clients both receive broadcast on Phase C update
- Non-subscribed story_id is filtered out
"""

import pytest

from lib.dashboard.story_broadcaster import (
    StoryUpdatesManager,
    broadcast_phase_change,
    get_story_updates_manager,
)


class MockWebSocket:
    """Mock WebSocket object matching FastAPI WebSocket interface for testing."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.closed: bool = False
        self.accepted: bool = False

    async def accept(self) -> None:
        """Accept connection."""
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        """Store sent message."""
        self.messages.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close connection."""
        self.closed = True


class TestStoryUpdatesManager:
    """Unit tests for StoryUpdatesManager subscription and broadcast logic."""

    @pytest.mark.asyncio
    async def test_wildcard_subscriber_receives_all_events(self) -> None:
        """Wildcard subscriber gets broadcasts for any story_id."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, "*")

        await manager.broadcast_phase_change("US-001", "S", "M")

        assert len(ws.messages) == 1
        assert ws.messages[0]["story_id"] == "US-001"
        assert ws.messages[0]["from_phase"] == "S"
        assert ws.messages[0]["to_phase"] == "M"

    @pytest.mark.asyncio
    async def test_wildcard_as_list_also_receives_all(self) -> None:
        """Wildcard passed as ['*'] also subscribes to all events."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, ["*"])

        await manager.broadcast_phase_change("US-999", "R", "S")

        assert len(ws.messages) == 1
        assert ws.messages[0]["story_id"] == "US-999"

    @pytest.mark.asyncio
    async def test_specific_subscriber_receives_matching_story(self) -> None:
        """Client subscribed to specific story_id receives matching events."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, ["US-001", "US-002"])

        await manager.broadcast_phase_change("US-001", "M", "I")

        assert len(ws.messages) == 1
        assert ws.messages[0]["story_id"] == "US-001"

    @pytest.mark.asyncio
    async def test_specific_subscriber_filters_non_matching_story(self) -> None:
        """Client subscribed to specific stories does NOT receive events for others."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, ["US-001", "US-002"])

        # US-999 is not subscribed
        await manager.broadcast_phase_change("US-999", "S", "M")

        assert len(ws.messages) == 0

    @pytest.mark.asyncio
    async def test_broadcast_includes_timestamp(self) -> None:
        """Broadcast message always includes a timestamp field."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, "*")

        await manager.broadcast_phase_change("US-010", "I", "V")

        assert len(ws.messages) == 1
        assert "timestamp" in ws.messages[0]
        assert ws.messages[0]["timestamp"] != ""

    @pytest.mark.asyncio
    async def test_broadcast_uses_provided_timestamp(self) -> None:
        """Broadcast uses provided timestamp when given."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, "*")

        ts = "2026-03-21T14:32:01Z"
        await manager.broadcast_phase_change("US-001", "S", "M", timestamp=ts)

        assert ws.messages[0]["timestamp"] == ts

    @pytest.mark.asyncio
    async def test_disconnect_removes_subscription(self) -> None:
        """Disconnected client no longer receives broadcasts."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, "*")
        await manager.disconnect(ws)

        await manager.broadcast_phase_change("US-001", "S", "M")

        assert len(ws.messages) == 0

    @pytest.mark.asyncio
    async def test_unsubscribed_client_receives_nothing(self) -> None:
        """Connected but unsubscribed client receives no broadcasts."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)
        # No subscribe call

        await manager.broadcast_phase_change("US-001", "S", "M")

        assert len(ws.messages) == 0


class TestStoryUpdatesIntegration:
    """Integration tests simulating Phase C story phase transitions."""

    @pytest.mark.asyncio
    async def test_two_clients_both_receive_phase_change_broadcast(self) -> None:
        """Integration: 2 connected clients both receive phase change from Phase C mock.

        Simulates Phase C updating prd.json story phase and broadcasting event.
        """
        manager = StoryUpdatesManager()

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        # Both clients connect and subscribe to all events
        await manager.connect(ws1)
        await manager.subscribe(ws1, "*")
        await manager.connect(ws2)
        await manager.subscribe(ws2, "*")

        # Simulate Phase C detecting story phase transition S -> M
        story_id = "US-001"
        from_phase = "S"
        to_phase = "M"
        timestamp = "2026-03-21T14:32:01Z"

        await manager.broadcast_phase_change(story_id, from_phase, to_phase, timestamp)

        # Both clients receive the event
        assert len(ws1.messages) == 1
        assert len(ws2.messages) == 1

        for ws in (ws1, ws2):
            msg = ws.messages[0]
            assert msg["story_id"] == story_id
            assert msg["from_phase"] == from_phase
            assert msg["to_phase"] == to_phase
            assert msg["timestamp"] == timestamp

    @pytest.mark.asyncio
    async def test_two_clients_with_different_subscriptions(self) -> None:
        """Integration: 2 clients with different subscriptions receive correctly filtered events."""
        manager = StoryUpdatesManager()

        ws1 = MockWebSocket()
        ws2 = MockWebSocket()

        await manager.connect(ws1)
        await manager.subscribe(ws1, ["US-001"])  # only US-001

        await manager.connect(ws2)
        await manager.subscribe(ws2, "*")  # all events

        # Phase change for US-001
        await manager.broadcast_phase_change("US-001", "S", "M")
        # Phase change for US-002
        await manager.broadcast_phase_change("US-002", "M", "I")

        # ws1 only gets US-001
        assert len(ws1.messages) == 1
        assert ws1.messages[0]["story_id"] == "US-001"

        # ws2 gets both
        assert len(ws2.messages) == 2

    @pytest.mark.asyncio
    async def test_module_level_broadcast_reaches_singleton_manager(self) -> None:
        """Module-level broadcast_phase_change uses the singleton manager."""
        manager = get_story_updates_manager()

        ws = MockWebSocket()
        await manager.connect(ws)
        await manager.subscribe(ws, "*")

        try:
            await broadcast_phase_change("US-042", "V", "C", "2026-03-21T00:00:00Z")

            assert len(ws.messages) == 1
            assert ws.messages[0]["story_id"] == "US-042"
            assert ws.messages[0]["from_phase"] == "V"
            assert ws.messages[0]["to_phase"] == "C"
        finally:
            await manager.disconnect(ws)

    @pytest.mark.asyncio
    async def test_phase_c_story_subscribe_message_format(self) -> None:
        """Validate the subscribe message format from Phase C client: story_ids list and wildcard."""
        manager = StoryUpdatesManager()
        ws = MockWebSocket()
        await manager.connect(ws)

        # Subscribe via list format
        await manager.subscribe(ws, ["US-001", "US-002"])
        await manager.broadcast_phase_change("US-001", "S", "M")
        assert len(ws.messages) == 1

        # Resubscribe via wildcard
        await manager.subscribe(ws, "*")
        await manager.broadcast_phase_change("US-999", "M", "I")
        assert len(ws.messages) == 2
