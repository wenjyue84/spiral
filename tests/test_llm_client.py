#!/usr/bin/env python3
"""
tests/test_llm_client.py — Unit tests for stream_completion (US-416).

Tests the streaming LLM completion client using mocked Anthropic SDK.
Covers:
  - Basic stream accumulation
  - Cache metrics extraction
  - Event emission to spiral_events.jsonl
  - Error handling
  - Usage dict structure
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from llm_client import stream_completion


class MockMessage:
    """Mock Anthropic Message object with usage attributes."""

    def __init__(
        self,
        text: str = "test response",
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        stop_reason: str = "end_turn",
    ):
        self.text = text
        self.usage = MagicMock()
        self.usage.input_tokens = input_tokens
        self.usage.output_tokens = output_tokens
        self.usage.cache_creation_input_tokens = cache_creation_input_tokens
        self.usage.cache_read_input_tokens = cache_read_input_tokens
        self.stop_reason = stop_reason


class MockStream:
    """Mock Anthropic SDK streaming context manager."""

    def __init__(self, chunks: list[str], message: MockMessage):
        self.chunks = chunks
        self.message = message
        self.text_stream = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_final_message(self):
        return self.message

    def get_final_text(self):
        return "".join(self.chunks)


@pytest.fixture
def mock_client():
    """Create a mock Anthropic client."""
    return MagicMock()


@pytest.fixture
def temp_events_file():
    """Create a temporary events file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        temp_path = f.name
    yield temp_path
    try:
        os.unlink(temp_path)
    except OSError:
        pass


class TestStreamCompletion:
    """Tests for stream_completion function."""

    def test_basic_streaming_accumulation(self, mock_client):
        """Test that text chunks are properly accumulated."""
        chunks = ["Hello", " ", "world"]
        message = MockMessage(text="Hello world", output_tokens=2)
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-haiku-4-5-20251001",
        )

        assert text == "Hello world"
        assert usage["output_tokens"] == 2
        assert usage["input_tokens"] == 100

    def test_usage_metrics_extraction(self, mock_client):
        """Test that usage metrics are properly extracted from final message."""
        chunks = ["response"]
        message = MockMessage(
            text="response",
            input_tokens=150,
            output_tokens=75,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=10,
            stop_reason="max_tokens",
        )
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        _, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-6",
        )

        assert usage["input_tokens"] == 150
        assert usage["output_tokens"] == 75
        assert usage["cache_creation_input_tokens"] == 50
        assert usage["cache_read_input_tokens"] == 10
        assert usage["stop_reason"] == "max_tokens"

    def test_cache_metrics_detection(self, mock_client):
        """Test that prompt cache metrics are correctly identified."""
        chunks = ["cached"]
        message = MockMessage(
            text="cached",
            input_tokens=200,
            output_tokens=25,
            cache_creation_input_tokens=100,
            cache_read_input_tokens=0,
        )
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        _, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
        )

        # Cache creation detected (first time storing cache)
        assert usage["cache_creation_input_tokens"] == 100
        assert usage["cache_read_input_tokens"] == 0

    def test_cache_hit_detection(self, mock_client):
        """Test detection of cache hit (cache read tokens > 0)."""
        chunks = ["response"]
        message = MockMessage(
            text="response",
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=500,  # Cache hit!
        )
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        _, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-6",
        )

        assert usage["cache_read_input_tokens"] == 500
        assert usage["cache_creation_input_tokens"] == 0

    def test_event_emission_to_jsonl(self, mock_client, temp_events_file):
        """Test that stream completion events are emitted to spiral_events.jsonl."""
        chunks = ["chunk1", "chunk2", "chunk3"]
        message = MockMessage(text="chunk1chunk2chunk3", output_tokens=3)
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, _ = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=temp_events_file,
            phase="S",
        )

        assert text == "chunk1chunk2chunk3"

        # Read events from file
        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        # Should have at least one stream_complete event
        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert len(complete_events) >= 1

        complete_event = complete_events[0]
        assert complete_event["phase"] == "S"
        assert complete_event["model"] == "claude-haiku-4-5-20251001"
        assert "usage" in complete_event
        assert complete_event["total_chunks"] == 3

    def test_event_includes_usage_metrics(self, mock_client, temp_events_file):
        """Test that usage metrics are included in emitted events."""
        chunks = ["response"]
        message = MockMessage(
            text="response",
            input_tokens=100,
            output_tokens=25,
            cache_read_input_tokens=10,
        )
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-6",
            events_file=temp_events_file,
            phase="R",
        )

        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert len(complete_events) >= 1

        event = complete_events[0]
        assert event["usage"]["input_tokens"] == 100
        assert event["usage"]["output_tokens"] == 25
        assert event["usage"]["cache_read_input_tokens"] == 10

    def test_stream_integration_with_kwargs(self, mock_client):
        """Test that kwargs are properly passed to client.messages.stream."""
        chunks = ["test"]
        message = MockMessage(text="test")
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0.5,
            stop_sequences=["STOP"],
        )

        # Verify kwargs were passed to stream
        mock_client.messages.stream.assert_called_once()
        call_kwargs = mock_client.messages.stream.call_args[1]
        assert call_kwargs["max_tokens"] == 256
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["stop_sequences"] == ["STOP"]

    def test_empty_streaming_response(self, mock_client):
        """Test handling of empty streaming response."""
        chunks = []
        message = MockMessage(text="", output_tokens=0)
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
        )

        assert text == ""
        assert usage["output_tokens"] == 0

    def test_long_streaming_response(self, mock_client):
        """Test accumulation of many small chunks."""
        chunks = ["a"] * 1000
        message = MockMessage(text="a" * 1000, output_tokens=1000)
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
        )

        assert len(text) == 1000
        assert text == "a" * 1000
        assert usage["output_tokens"] == 1000

    def test_missing_usage_attributes(self, mock_client):
        """Test graceful handling when usage attributes are missing."""
        chunks = ["response"]
        # Create a message with None usage
        message = MagicMock()
        message.usage = None
        message.stop_reason = "end_turn"
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
        )

        assert text == "response"
        # Usage should have default values when missing
        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["cache_creation_input_tokens"] == 0
        assert usage["cache_read_input_tokens"] == 0

    def test_streaming_error_handling(self, mock_client, temp_events_file):
        """Test that streaming errors are handled and events emitted."""
        mock_client.messages.stream.side_effect = ValueError("API Error")

        with pytest.raises(ValueError):
            stream_completion(
                client=mock_client,
                messages=[{"role": "user", "content": "test"}],
                model="claude-haiku-4-5-20251001",
                events_file=temp_events_file,
                phase="S",
            )

        # Verify error event was emitted
        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        error_events = [e for e in events if e.get("event_type") == "llm_stream_error"]
        assert len(error_events) >= 1
        assert "API Error" in error_events[0]["error"]

    def test_phase_parameter_in_events(self, mock_client, temp_events_file):
        """Test that phase parameter is correctly recorded in events."""
        chunks = ["response"]
        message = MockMessage(text="response")
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=temp_events_file,
            phase="R",  # Research phase
        )

        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert complete_events[0]["phase"] == "R"

        # Test with different phase
        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=temp_events_file,
            phase="S",  # Story validation phase
        )

        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert complete_events[-1]["phase"] == "S"

    def test_events_file_none_no_errors(self, mock_client):
        """Test that missing events_file doesn't cause errors."""
        chunks = ["response"]
        message = MockMessage(text="response", output_tokens=50)
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        text, usage = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=None,  # No event file
        )

        assert text == "response"
        assert usage["output_tokens"] == 50

    def test_model_in_call_and_events(self, mock_client, temp_events_file):
        """Test that model name is properly used in API call and events."""
        chunks = ["response"]
        message = MockMessage(text="response")
        mock_client.messages.stream.return_value = MockStream(chunks, message)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-opus-4-6",
            events_file=temp_events_file,
        )

        # Check that model was passed to stream call
        call_args = mock_client.messages.stream.call_args
        assert call_args[1]["model"] == "claude-opus-4-6"

        # Check that model is in events
        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert complete_events[0]["model"] == "claude-opus-4-6"


class TestStreamCompletionIntegration:
    """Integration tests with more realistic scenarios."""

    def test_json_response_accumulation(self, mock_client):
        """Test streaming a JSON response that gets accumulated properly."""
        json_chunks = [
            '{"accepted": ',
            "true",
            ', "reason": "',
            "looks good",
            '"}',
        ]
        message = MockMessage(text='{"accepted": true, "reason": "looks good"}')
        mock_client.messages.stream.return_value = MockStream(json_chunks, message)

        text, _ = stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "validate this"}],
            model="claude-haiku-4-5-20251001",
        )

        # Verify accumulated text is valid JSON
        parsed = json.loads(text)
        assert parsed["accepted"] is True
        assert parsed["reason"] == "looks good"

    def test_multiple_calls_with_different_metrics(self, mock_client, temp_events_file):
        """Test multiple stream calls with different cache behaviors."""
        # First call: cache creation
        chunks1 = ["response1"]
        message1 = MockMessage(
            text="response1",
            cache_creation_input_tokens=100,
            cache_read_input_tokens=0,
        )
        mock_client.messages.stream.return_value = MockStream(chunks1, message1)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=temp_events_file,
        )

        # Second call: cache hit
        chunks2 = ["response2"]
        message2 = MockMessage(
            text="response2",
            cache_creation_input_tokens=0,
            cache_read_input_tokens=100,
        )
        mock_client.messages.stream.return_value = MockStream(chunks2, message2)

        stream_completion(
            client=mock_client,
            messages=[{"role": "user", "content": "test"}],
            model="claude-haiku-4-5-20251001",
            events_file=temp_events_file,
        )

        # Verify both calls recorded correct cache metrics
        with open(temp_events_file, "r") as f:
            events = [json.loads(line) for line in f if line.strip()]

        complete_events = [e for e in events if e.get("event_type") == "llm_stream_complete"]
        assert len(complete_events) == 2
        assert complete_events[0]["usage"]["cache_creation_input_tokens"] == 100
        assert complete_events[1]["usage"]["cache_read_input_tokens"] == 100
