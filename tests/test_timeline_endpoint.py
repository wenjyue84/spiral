"""test_timeline_endpoint.py — Unit and integration tests for timeline endpoint and WebSocket."""

import csv
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app
from lib.dashboard.timeline import (
    PHASE_NAMES,
    PHASE_ORDER,
    TimelineEvent,
    TimelineManager,
    parse_timeline,
)


class TestTimelineEvent:
    """Tests for TimelineEvent dataclass."""

    def test_timeline_event_creation(self) -> None:
        """Test creating a TimelineEvent."""
        event = TimelineEvent(
            story_id="US-123",
            iteration=0,
            phase="I",
            status="passed",
            start_time="2026-03-20T10:00:00Z",
            end_time="2026-03-20T10:05:00Z",
            duration_ms=300000,
            model_used="haiku",
        )
        assert event.story_id == "US-123"
        assert event.iteration == 0
        assert event.phase == "I"
        assert event.status == "passed"

    def test_timeline_event_to_dict(self) -> None:
        """Test converting TimelineEvent to dict."""
        event = TimelineEvent(
            story_id="US-456",
            iteration=1,
            phase="V",
            status="failed",
            start_time="2026-03-20T10:00:00Z",
            end_time=None,
            duration_ms=150000,
            model_used="sonnet",
        )
        d = event.to_dict()
        assert d["story_id"] == "US-456"
        assert d["iteration"] == 1
        assert d["phase"] == "V"
        assert d["status"] == "failed"
        assert d["end_time"] is None


class TestTimelineParser:
    """Tests for parse_timeline function."""

    def test_parse_timeline_empty(self) -> None:
        """Test parsing empty results.tsv."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as f:
            f.write("timestamp\tspiral_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\n")
            f.flush()
            path = Path(f.name)

        try:
            events = parse_timeline(path)
            assert events == []
        finally:
            path.unlink()

    def test_parse_timeline_single_story(self) -> None:
        """Test parsing results.tsv with a single story."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "spiral_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:00:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-123",
                    "story_title": "Test Story",
                    "status": "accept",
                    "duration_sec": "120.5",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            events = parse_timeline(path)
            assert len(events) == 1
            event = events[0]
            assert event.story_id == "US-123"
            assert event.iteration == 0
            assert event.phase == "I"
            assert event.status == "passed"
            assert event.duration_ms == 120500
            assert event.model_used == "haiku"
        finally:
            path.unlink()

    def test_parse_timeline_multiple_stories(self) -> None:
        """Test parsing results.tsv with multiple stories."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "spiral_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:00:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-123",
                    "story_title": "Story 1",
                    "status": "accept",
                    "duration_sec": "100",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:05:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-124",
                    "story_title": "Story 2",
                    "status": "reject",
                    "duration_sec": "50",
                    "model": "sonnet",
                    "retry_num": "1",
                    "commit_sha": "def456",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            events = parse_timeline(path)
            assert len(events) == 2
            assert events[0].story_id == "US-123"
            assert events[0].status == "passed"
            assert events[1].story_id == "US-124"
            assert events[1].status == "failed"
        finally:
            path.unlink()

    def test_parse_timeline_iteration_filtering(self) -> None:
        """Test that parse_timeline filters to recent iterations."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "spiral_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            # Add stories from iterations 0-5
            for iter_num in range(6):
                writer.writerow(
                    {
                        "timestamp": "2026-03-20T10:00:00Z",
                        "spiral_iter": str(iter_num),
                        "story_id": f"US-{iter_num}",
                        "story_title": f"Story {iter_num}",
                        "status": "accept",
                        "duration_sec": "100",
                        "model": "haiku",
                        "retry_num": "0",
                        "commit_sha": "abc123",
                    }
                )
            f.flush()
            path = Path(f.name)

        try:
            # Request 3 iterations, should get iterations 3, 4, 5 (most recent 3)
            events = parse_timeline(path, iterations_limit=3)
            iterations = set(e.iteration for e in events)
            assert iterations == {3, 4, 5}
        finally:
            path.unlink()

    def test_parse_timeline_sorting(self) -> None:
        """Test that timeline events are sorted correctly."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "spiral_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            # Add out-of-order stories
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:00:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-200",
                    "story_title": "Story Z",
                    "status": "accept",
                    "duration_sec": "100",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:00:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-100",
                    "story_title": "Story A",
                    "status": "accept",
                    "duration_sec": "100",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            events = parse_timeline(path)
            # Should be sorted by story_id within same iteration/phase
            story_ids = [e.story_id for e in events]
            assert story_ids == ["US-100", "US-200"]
        finally:
            path.unlink()


class TestTimelineManager:
    """Tests for TimelineManager class."""

    @pytest.mark.asyncio
    async def test_timeline_manager_connect_disconnect(self) -> None:
        """Test connecting and disconnecting from timeline manager."""
        manager = TimelineManager()

        # Mock WebSocket
        class MockWebSocket:
            async def accept(self) -> None:
                pass

            async def send_json(self, data: dict[str, Any]) -> None:
                pass

        ws = MockWebSocket()
        await manager.connect(ws)
        assert manager.connection_count() == 1

        await manager.disconnect(ws)
        assert manager.connection_count() == 0

    @pytest.mark.asyncio
    async def test_timeline_manager_broadcast(self) -> None:
        """Test broadcasting timeline events."""
        manager = TimelineManager()
        received_messages: list[dict[str, Any]] = []

        class MockWebSocket:
            async def accept(self) -> None:
                pass

            async def send_json(self, data: dict[str, Any]) -> None:
                received_messages.append(data)

        ws = MockWebSocket()
        await manager.connect(ws)

        event = TimelineEvent(
            story_id="US-123",
            iteration=0,
            phase="I",
            status="passed",
            start_time="2026-03-20T10:00:00Z",
            end_time=None,
            duration_ms=100000,
            model_used="haiku",
        )

        await manager.broadcast(event)
        assert len(received_messages) == 1
        assert received_messages[0]["event"] == "phase_change"
        assert received_messages[0]["story_id"] == "US-123"


class TestTimelineEndpoint:
    """Tests for /api/timeline endpoint."""

    def test_timeline_endpoint_no_data(self) -> None:
        """Test timeline endpoint when no results.tsv exists."""
        client = TestClient(app)

        # Use a non-existent path
        import lib.dashboard.api as api_module

        old_path = api_module.Path

        def mock_path(p: str) -> Path:
            if p == ".spiral/results.tsv":
                return Path("/nonexistent/path/results.tsv")
            return old_path(p)

        api_module.Path = mock_path  # type: ignore
        try:
            response = client.get("/api/timeline?iterations=3")
            assert response.status_code == 200
            data = response.json()
            assert data["iterations_requested"] == 3
            assert data["events"] == []
            assert data["total_events"] == 0
        finally:
            api_module.Path = old_path  # type: ignore

    def test_timeline_endpoint_with_data(self) -> None:
        """Test timeline endpoint with data."""
        client = TestClient(app)

        # Create temporary results.tsv
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".tsv", dir=".spiral") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "spiral_iter",
                    "story_id",
                    "story_title",
                    "status",
                    "duration_sec",
                    "model",
                    "retry_num",
                    "commit_sha",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "timestamp": "2026-03-20T10:00:00Z",
                    "spiral_iter": "0",
                    "story_id": "US-123",
                    "story_title": "Test Story",
                    "status": "accept",
                    "duration_sec": "120",
                    "model": "haiku",
                    "retry_num": "0",
                    "commit_sha": "abc123",
                }
            )
            f.flush()

        try:
            # Mock the results.tsv path
            Path(".spiral/results.tsv")
            temp_path = Path(f.name)

            # Use the temp file path directly
            import lib.dashboard.api as api_module

            old_get = api_module.Path

            def mock_path(p: str) -> Path:
                if p == ".spiral/results.tsv":
                    return temp_path
                return old_get(p)

            api_module.Path = mock_path  # type: ignore

            response = client.get("/api/timeline?iterations=3")
            assert response.status_code == 200
            data = response.json()
            assert data["iterations_requested"] == 3
            assert len(data["events"]) > 0
            assert data["total_events"] > 0

        finally:
            api_module.Path = old_get  # type: ignore
            temp_path.unlink()

    def test_timeline_endpoint_iterations_param(self) -> None:
        """Test timeline endpoint with different iterations parameter."""
        client = TestClient(app)
        response = client.get("/api/timeline?iterations=5")
        assert response.status_code == 200
        data = response.json()
        assert data["iterations_requested"] == 5

    def test_timeline_endpoint_default_iterations(self) -> None:
        """Test timeline endpoint uses default iterations=3."""
        client = TestClient(app)
        response = client.get("/api/timeline")
        assert response.status_code == 200
        data = response.json()
        assert data["iterations_requested"] == 3


class TestTimelineConstants:
    """Tests for timeline constants."""

    def test_phase_order_contains_all_phases(self) -> None:
        """Test PHASE_ORDER contains expected phases."""
        assert PHASE_ORDER == ["A", "R", "T", "S", "E", "M", "X", "G", "I", "V", "C", "L"]

    def test_phase_names_all_phases(self) -> None:
        """Test PHASE_NAMES has entries for all phases."""
        for phase in PHASE_ORDER:
            assert phase in PHASE_NAMES
            assert isinstance(PHASE_NAMES[phase], str)

    def test_phase_names_not_empty(self) -> None:
        """Test PHASE_NAMES values are not empty."""
        for phase_name in PHASE_NAMES.values():
            assert len(phase_name) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
