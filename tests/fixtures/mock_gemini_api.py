"""Mock Gemini API for testing Phase R research cache behavior."""

from __future__ import annotations

from typing import Any


class MockGeminiAPI:
    """Mock Gemini API client that tracks call count and injects responses.

    Used for testing cache hit/miss behavior and TTL expiry.
    """

    def __init__(self) -> None:
        """Initialize mock API with call count at zero."""
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    def __call__(self, query: str, story_title: str = "") -> dict[str, Any]:
        """Mock API call that increments call count and returns response.

        Args:
            query: Research query string
            story_title: Story title for context

        Returns:
            Mock response dictionary with research content
        """
        self.call_count += 1
        response = {
            "research": f"Mock research result for: {query}",
            "story_title": story_title,
            "call_number": self.call_count,
        }
        self.calls.append({"query": query, "story_title": story_title, "response": response})
        return response

    def reset(self) -> None:
        """Reset call count and call history."""
        self.call_count = 0
        self.calls = []
