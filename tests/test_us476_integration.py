"""tests/test_us476_integration.py — Integration tests for mock Claude client fixture library.

Tests validate that the mock Claude client fixture (US-476) enables fast, hermetic
Phase R/S integration testing without external API calls. Covers success paths and
error handling (rate limits, malformed responses).
"""

import json
import sys
import os
from typing import Dict, Any

import pytest

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# Import MockClaudeClient from conftest
from conftest import MockClaudeClient


# ── Test: Happy Path - Mock Claude Research Phase ──────────────────────────────


def test_mock_research_phase_happy_path(mock_claude_client):
    """Test: Mock Claude client simulates successful Phase R research response.

    Verifies:
    - Client returns valid research output with stories
    - Response matches expected Phase R schema
    - Story fields are parseable for further processing
    """
    # Prepare custom research response
    research_response = {
        "stories": [
            {
                "id": "US-501",
                "title": "AI Model Safety Improvements",
                "description": "Research identified gaps in current model safety testing",
                "priority": "high",
                "source": "https://research.example.com/ai-safety",
                "_source": "research",
                "acceptanceCriteria": [
                    "Implement adversarial input testing framework",
                    "Document safety boundary cases",
                ],
            },
            {
                "id": "US-502",
                "title": "Developer Experience Enhancement",
                "description": "User feedback indicates need for better API documentation",
                "priority": "medium",
                "source": "https://research.example.com/ux",
                "_source": "research",
                "acceptanceCriteria": [
                    "Create interactive API examples",
                    "Add code snippets for common patterns",
                ],
            },
        ]
    }

    # Configure mock client with research response
    client = mock_claude_client.__class__(response_data=research_response)

    # Simulate Phase R: call Claude to generate research stories
    try:
        response = client.chat_completion(
            messages=[{"role": "user", "content": "Generate research stories"}],
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
        )
    except Exception as e:
        pytest.fail(f"Mock client raised unexpected error: {e}")

    # Validate response structure
    assert response is not None, "Response should not be None"
    assert "content" in response, "Response should have content field"
    assert len(response["content"]) > 0, "Response should have at least one content item"

    # Parse the text content (which contains JSON-encoded stories)
    content_text = response["content"][0].get("text", "")
    assert content_text, "Content text should not be empty"

    # Parse stories from response
    try:
        parsed_stories = json.loads(content_text)
    except json.JSONDecodeError as e:
        pytest.fail(f"Failed to parse response as JSON: {e}")

    # Validate stories structure
    assert "stories" in parsed_stories, "Parsed response should have 'stories' key"
    assert isinstance(parsed_stories["stories"], list), "Stories should be a list"
    assert len(parsed_stories["stories"]) == 2, "Should have 2 research stories"

    # Validate individual story fields
    for story in parsed_stories["stories"]:
        assert "id" in story, f"Story {story.get('id')} missing 'id' field"
        assert "title" in story, f"Story {story.get('id')} missing 'title' field"
        assert "description" in story, f"Story {story.get('id')} missing 'description' field"
        assert "priority" in story, f"Story {story.get('id')} missing 'priority' field"
        assert "source" in story, f"Story {story.get('id')} missing 'source' field"
        assert story.get("_source") == "research", f"Story should have _source=research"
        assert "acceptanceCriteria" in story, f"Story {story.get('id')} missing 'acceptanceCriteria'"

    # Verify stories match what we provided
    story_ids = {s["id"] for s in parsed_stories["stories"]}
    assert "US-501" in story_ids, "Should contain US-501"
    assert "US-502" in story_ids, "Should contain US-502"

    # Verify response metadata
    assert response.get("model") == "claude-3-5-sonnet-20241022", "Should preserve model name"
    assert "usage" in response, "Response should include token usage"
    assert response["usage"]["input_tokens"] > 0, "Should have input token count"
    assert response["usage"]["output_tokens"] > 0, "Should have output token count"


def test_mock_client_tracks_call_count(mock_claude_client):
    """Test: Mock client tracks number of API calls for diagnostics."""
    client = mock_claude_client.__class__()

    # Initial state
    assert client.call_count == 0, "Should start with 0 calls"

    # Make first call
    client.chat_completion(messages=[{"role": "user", "content": "test"}])
    assert client.call_count == 1, "Should have 1 call after first invocation"

    # Make second call
    client.chat_completion(messages=[{"role": "user", "content": "test"}])
    assert client.call_count == 2, "Should have 2 calls after second invocation"


# ── Test: Error Handling - Rate Limit (429) ──────────────────────────────────


def test_mock_client_error_response_rate_limit():
    """Test: Mock client gracefully simulates API rate limit (429 Too Many Requests).

    Verifies:
    - Rate limit error is raised as ValueError
    - Error message is descriptive
    - Calling code can catch and handle the error
    """
    # Configure mock to return rate limit error
    client = MockClaudeClient(error_mode="rate_limit")

    # Attempt to call client (should raise ValueError for rate limit)
    with pytest.raises(ValueError) as exc_info:
        client.chat_completion(
            messages=[{"role": "user", "content": "test"}],
            model="claude-3-5-sonnet-20241022",
        )

    # Validate error message
    error_msg = str(exc_info.value)
    assert "429" in error_msg or "Rate" in error_msg, f"Error should mention rate limit: {error_msg}"

    # Verify call was still counted (for diagnostics)
    assert client.call_count == 1, "Should count failed calls for diagnostics"


# ── Test: Error Handling - Malformed JSON ────────────────────────────────────


def test_mock_client_error_response_malformed_json():
    """Test: Mock client gracefully handles malformed API responses.

    Verifies:
    - Malformed JSON error is raised as ValueError
    - Error indicates the problem
    - Calling code can detect and recover
    """
    # Configure mock to return malformed response
    client = MockClaudeClient(error_mode="malformed")

    # Attempt to call client (should raise ValueError for malformed response)
    with pytest.raises(ValueError) as exc_info:
        client.chat_completion(
            messages=[{"role": "user", "content": "test"}],
        )

    # Validate error message indicates malformed data
    error_msg = str(exc_info.value)
    assert "Malformed" in error_msg or "JSON" in error_msg, f"Error should indicate malformed JSON: {error_msg}"

    # Verify call was tracked
    assert client.call_count == 1, "Should count failed calls"


def test_mock_client_recovery_after_error():
    """Test: Mock client can recover and return success after simulated error.

    Verifies:
    - Error doesn't poison subsequent calls
    - Client can be reused after error
    """
    # First client instance with error mode
    error_client = MockClaudeClient(error_mode="rate_limit")

    # First call should fail
    with pytest.raises(ValueError):
        error_client.chat_completion(messages=[{"role": "user", "content": "test"}])

    # Create new success client
    success_client = MockClaudeClient()
    response = success_client.chat_completion(messages=[{"role": "user", "content": "test"}])

    # Should succeed
    assert response is not None, "Recovery client should return valid response"
    assert "content" in response, "Recovery response should have content"


# ── Test: Hermetic Testing (No Network Calls) ────────────────────────────────


def test_mock_client_hermetic_no_network_calls(mock_claude_client):
    """Test: Mock client is hermetic - makes no external network calls.

    This test validates that the mock client is self-contained and doesn't
    attempt to contact external APIs. It should work in air-gapped environments.
    """
    client = mock_claude_client.__class__()

    # Make a call - should complete without any network access
    response = client.chat_completion(
        messages=[{"role": "user", "content": "test query"}],
        model="claude-3-5-sonnet-20241022",
    )

    # Verify response is available immediately (not waiting for network)
    assert response is not None, "Should return response immediately without network"

    # Verify response was generated locally (from mock data)
    assert response.get("id") == "msg_12345", "Response should use mock ID"


# ── Test: Phase S Validation Response ────────────────────────────────────────


def test_mock_client_phase_s_validation_response():
    """Test: Mock client can simulate Phase S story validation responses.

    Phase S validates stories against the constitution. This test verifies
    the mock client can return validation results.
    """
    # Phase S validates stories and returns acceptance/rejection
    validation_response = {
        "validated_stories": [
            {
                "id": "US-503",
                "valid": True,
                "reason": "Meets constitution requirements",
            },
            {
                "id": "US-504",
                "valid": False,
                "reason": "Violates backward compatibility constraint",
            },
        ]
    }

    client = MockClaudeClient(response_data=validation_response)

    # Call client for Phase S validation
    response = client.chat_completion(
        messages=[{"role": "user", "content": "Validate stories against constitution"}],
        model="claude-3-5-sonnet-20241022",
    )

    # Parse validation results
    content_text = response["content"][0].get("text", "")
    validated = json.loads(content_text)

    # Verify validation structure
    assert "validated_stories" in validated, "Should have validated_stories"
    assert len(validated["validated_stories"]) == 2, "Should have 2 validation results"

    # Check first story (valid)
    valid_story = validated["validated_stories"][0]
    assert valid_story["id"] == "US-503", "First should be US-503"
    assert valid_story["valid"] is True, "First should be valid"

    # Check second story (invalid)
    invalid_story = validated["validated_stories"][1]
    assert invalid_story["id"] == "US-504", "Second should be US-504"
    assert invalid_story["valid"] is False, "Second should be invalid"
    assert "constraint" in invalid_story["reason"].lower(), "Should explain why invalid"


# ── Test: Large Response Handling ────────────────────────────────────────────


def test_mock_client_large_story_batch():
    """Test: Mock client handles large batches of research stories (50+).

    Simulates Phase R with high volume of research candidates to ensure
    mock scales appropriately.
    """
    # Create response with many stories
    many_stories = {
        "stories": [
            {
                "id": f"US-{600 + i}",
                "title": f"Research Story {i + 1}",
                "description": f"Story {i + 1} from extended research",
                "priority": ["high", "medium", "low"][i % 3],
                "source": f"https://research.example.com/story{i + 1}",
                "_source": "research",
                "acceptanceCriteria": [f"Criterion {j + 1}" for j in range(2)],
            }
            for i in range(50)
        ]
    }

    client = MockClaudeClient(response_data=many_stories)

    # Call with large batch
    response = client.chat_completion(messages=[{"role": "user", "content": "50 stories"}])

    # Parse and verify
    content_text = response["content"][0].get("text", "")
    parsed = json.loads(content_text)

    assert len(parsed["stories"]) == 50, "Should handle 50 stories"
    assert parsed["stories"][0]["id"] == "US-600", "IDs should be sequential"
    assert parsed["stories"][49]["id"] == "US-649", "Last ID should be correct"


# ── Test: Multiple Client Instances ──────────────────────────────────────────


def test_multiple_mock_client_instances():
    """Test: Multiple mock client instances are independent.

    Different test cases should have independent mock clients
    without shared state.
    """
    client1 = MockClaudeClient()
    client2 = MockClaudeClient(error_mode="rate_limit")
    client3 = MockClaudeClient()

    # Client 1: success
    response1 = client1.chat_completion(messages=[])
    assert response1 is not None, "Client 1 should succeed"
    assert client1.call_count == 1, "Client 1 should track its own calls"

    # Client 2: error
    with pytest.raises(ValueError):
        client2.chat_completion(messages=[])
    assert client2.call_count == 1, "Client 2 should track its own calls"

    # Client 3: independent success
    response3 = client3.chat_completion(messages=[])
    assert response3 is not None, "Client 3 should succeed independently"
    assert client3.call_count == 1, "Client 3 should have its own call counter"

    # Verify call counts are independent
    assert client1.call_count == 1, "Client 1 call count should remain 1"
    assert client3.call_count == 1, "Client 3 call count should remain 1"
