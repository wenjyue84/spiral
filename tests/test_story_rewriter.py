#!/usr/bin/env python3
"""
tests/test_story_rewriter.py — Unit tests for lib.story_rewriter (US-776)

Verifies that constitution-failing stories can be rewritten with haiku
while preserving original intent.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add lib to path
sys.path.insert(0, "lib")

from story_rewriter import rewrite_story


@pytest.fixture
def vague_story():
    """A story that violates constitution with vague language."""
    return {
        "id": "US-999",
        "title": "Improve the system",
        "description": "Make things better and faster",
        "acceptanceCriteria": ["System is improved", "It should be faster"],
    }


@pytest.fixture
def already_rewritten_story():
    """A story that was already rewritten once."""
    return {
        "id": "US-1000",
        "title": "Concrete Title",
        "description": "Specific goal",
        "acceptanceCriteria": ["Test passes"],
        "_rewritten": True,
    }


def test_rewrite_vague_story_returns_concrete_version(vague_story):
    """Test that a vague story gets rewritten with concrete ACs."""
    api_response = {
        "content": [
            {
                "text": json.dumps(
                    {
                        "title": "Add performance monitoring dashboard to system",
                        "acceptanceCriteria": [
                            "Dashboard displays CPU usage every 5 seconds",
                            "Memory usage chart updates in real-time",
                            "Tests verify dashboard updates within 100ms",
                        ],
                    }
                )
            }
        ]
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: api_response)

        result = rewrite_story(vague_story, "test-api-key")

        assert result is not None
        assert result["_rewritten"] is True
        assert "monitoring dashboard" in result["title"]
        assert len(result["acceptanceCriteria"]) == 3
        assert all(ac for ac in result["acceptanceCriteria"])


def test_already_rewritten_story_returns_none(already_rewritten_story):
    """Test that max 1 rewrite is enforced via _rewritten flag."""
    result = rewrite_story(already_rewritten_story, "test-api-key")
    assert result is None


def test_rewrite_handles_api_failure(vague_story):
    """Test that failed API calls return None gracefully."""
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500)

        result = rewrite_story(vague_story, "test-api-key")
        assert result is None


def test_rewrite_preserves_story_id_and_description(vague_story):
    """Test that rewrite preserves original id and description."""
    api_response = {
        "content": [
            {
                "text": json.dumps(
                    {
                        "title": "New Title",
                        "acceptanceCriteria": ["AC1"],
                    }
                )
            }
        ]
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: api_response)

        result = rewrite_story(vague_story, "test-api-key")

        assert result["id"] == "US-999"
        assert result["description"] == vague_story["description"]


def test_rewrite_parses_markdown_json(vague_story):
    """Test that rewrite handles JSON wrapped in markdown code blocks."""
    api_response = {
        "content": [
            {
                "text": """```json
{
  "title": "New Title",
  "acceptanceCriteria": ["AC1", "AC2"]
}
```"""
            }
        ]
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: api_response)

        result = rewrite_story(vague_story, "test-api-key")

        assert result is not None
        assert result["title"] == "New Title"
        assert len(result["acceptanceCriteria"]) == 2
