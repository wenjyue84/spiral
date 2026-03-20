"""Tests for US-455: routing telemetry emission."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from routing_telemetry import emit_routing_event, emit_routing_events


class TestEmitRoutingEvent:
    def test_event_written_to_file(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        emit_routing_event(events_path, "US-001", 45, "sonnet", 15000)

        with open(events_path, encoding="utf-8") as f:
            line = f.readline()
        record = json.loads(line)

        assert record["type"] == "route_story_assigned"
        assert record["story_id"] == "US-001"
        assert record["complexity_score"] == 45
        assert record["model_tier"] == "sonnet"
        assert record["estimated_tokens"] == 15000
        assert "ts" in record

    def test_multiple_events_appended(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        emit_routing_event(events_path, "US-001", 30, "haiku")
        emit_routing_event(events_path, "US-002", 80, "opus")

        with open(events_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_event_has_required_fields(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        emit_routing_event(events_path, "US-100", 55, "sonnet", 12000)

        with open(events_path, encoding="utf-8") as f:
            record = json.loads(f.readline())

        required = {"ts", "type", "story_id", "complexity_score", "model_tier", "estimated_tokens"}
        assert required.issubset(record.keys())


class TestEmitRoutingEvents:
    def test_batch_emission(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        events = [
            {"story_id": "US-001", "complexity_score": 20, "model_tier": "haiku", "estimated_tokens": 5000},
            {"story_id": "US-002", "complexity_score": 60, "model_tier": "sonnet", "estimated_tokens": 15000},
        ]
        emit_routing_events(events_path, events)

        with open(events_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["story_id"] == "US-001"
        assert json.loads(lines[1])["story_id"] == "US-002"
