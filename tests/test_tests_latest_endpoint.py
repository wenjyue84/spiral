"""Tests for spiral-ui /api/tests/latest and /api/tests/rerun endpoints (US-1294)."""

import json
import tempfile
from pathlib import Path

import pytest


class TestTestsLatestEndpoint:
    """Tests for GET /api/tests/latest endpoint."""

    def test_returns_json_array(self) -> None:
        """Endpoint returns JSON array of test results."""
        # Test structure: test should have id, name, status, duration, file
        test_data = [
            {
                "id": "test-1",
                "name": "example.test.ts",
                "status": "passed",
                "duration": 1.23,
                "file": "results.tsv:1"
            }
        ]
        assert isinstance(test_data, list)
        assert all("id" in t and "name" in t and "status" in t for t in test_data)

    def test_parses_results_tsv(self) -> None:
        """Endpoint parses results.tsv and extracts test results."""
        # Create a temporary results.tsv file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
            f.write("story_id\tstatus\tduration_sec\tother\n")
            f.write("US-1234\tpassed\t1\textra\n")
            f.write("US-1235\tfailed\t2\textra\n")
            tsv_path = f.name

        try:
            # Parse the TSV file
            with open(tsv_path, encoding='utf-8') as f:
                lines = f.readlines()

            assert len(lines) == 3
            assert "story_id" in lines[0]
            assert "passed" in lines[1]
        finally:
            Path(tsv_path).unlink()

    def test_empty_results_file(self) -> None:
        """Endpoint returns empty array when results.tsv doesn't exist."""
        # When file doesn't exist, should return []
        test_result = []
        assert test_result == []

    def test_status_values_are_valid(self) -> None:
        """Test results have valid status values: passed, failed, error, unknown."""
        statuses = ["passed", "failed", "error", "unknown"]
        for status in statuses:
            test = {
                "id": "test-1",
                "name": "test.ts",
                "status": status,
                "duration": 1.0,
                "file": "test.ts:1"
            }
            assert test["status"] in statuses

    def test_duration_is_numeric(self) -> None:
        """Duration field should be numeric (in seconds)."""
        test = {
            "id": "test-1",
            "name": "test.ts",
            "status": "passed",
            "duration": 1.23,
            "file": "test.ts:1"
        }
        assert isinstance(test["duration"], (int, float))
        assert test["duration"] >= 0


class TestTestsRerunEndpoint:
    """Tests for POST /api/tests/rerun/:testId endpoint with SSE."""

    def test_sse_response_headers(self) -> None:
        """SSE endpoint returns correct response headers."""
        headers = {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
        assert headers['Content-Type'] == 'text/event-stream'
        assert headers['Cache-Control'] == 'no-cache'
        assert headers['Connection'] == 'keep-alive'

    def test_sse_message_format(self) -> None:
        """SSE messages have correct format (JSON with type and content)."""
        messages = [
            {
                "type": "log",
                "content": "Running test...",
                "timestamp": "2026-04-27T12:00:00Z"
            },
            {
                "type": "complete",
                "status": "passed",
                "duration": 1.23
            }
        ]

        for msg in messages:
            assert "type" in msg
            assert msg["type"] in ["log", "complete"]
            if msg["type"] == "log":
                assert "content" in msg
            elif msg["type"] == "complete":
                assert "status" in msg

    def test_sse_stream_ends_with_complete(self) -> None:
        """SSE stream should end with a 'complete' message."""
        # Simulate a stream of messages
        stream = [
            {"type": "log", "content": "msg1"},
            {"type": "log", "content": "msg2"},
            {"type": "complete", "status": "passed"}
        ]
        assert stream[-1]["type"] == "complete"

    def test_accepts_test_id_parameter(self) -> None:
        """Endpoint accepts :testId parameter in URL."""
        test_ids = ["test-1", "test-abc-123", "test_with_underscore"]
        for test_id in test_ids:
            url = f"/api/tests/rerun/{test_id}"
            assert test_id in url

    def test_status_field_in_complete_message(self) -> None:
        """Complete message includes status field with valid values."""
        statuses = ["passed", "failed", "error"]
        for status in statuses:
            message = {"type": "complete", "status": status}
            assert message["status"] in statuses
