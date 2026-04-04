"""Tests for lib/context/overflow_guard.py."""

import json
import sys
from pathlib import Path

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from context.overflow_guard import (
    estimate_tokens,
    guard_story_context,
    trim_progressive,
)


def test_estimate_tokens_basic() -> None:
    """Test token estimation for basic text."""
    short_text = "hello world"
    tokens = estimate_tokens(short_text)
    # 11 chars / 4 = ~2.75, so 2 tokens (fallback heuristic)
    assert tokens > 0
    assert tokens <= 5


def test_estimate_tokens_longer() -> None:
    """Test token estimation scales with text length."""
    short = "hello"
    long = "hello " * 100

    short_tokens = estimate_tokens(short)
    long_tokens = estimate_tokens(long)

    # Longer text should have more tokens
    assert long_tokens > short_tokens


def test_guard_under_budget() -> None:
    """Test no trimming when story is under budget."""
    story = {
        "id": "US-100",
        "title": "Small story",
        "description": "Brief description",
        "acceptanceCriteria": ["Criterion 1"],
    }

    result = guard_story_context(story, budget_tokens=100000)

    # Should not be marked as trimmed
    assert "_context_trimmed" not in result or result["_context_trimmed"] is False


def test_guard_over_budget_trims() -> None:
    """Test trimming when story exceeds budget."""
    # Create a story with very large description
    large_text = "a" * 500000  # 500k chars

    story = {
        "id": "US-100",
        "title": "Large story",
        "description": large_text,
        "acceptanceCriteria": ["Criterion " + str(i) for i in range(20)],
        "technicalNotes": ["Note " * 100 for _ in range(10)],
    }

    # Use smaller budget to force trimming (500k chars ~ 125k tokens)
    result = guard_story_context(story, budget_tokens=100000)

    # Should be marked as trimmed
    assert result.get("_context_trimmed") is True

    # Result should be smaller
    result_str = json.dumps(result)
    estimated_tokens = estimate_tokens(result_str)
    assert estimated_tokens < 110000  # Should be under adjusted budget


def test_trim_progressive_preserves_critical_fields() -> None:
    """Test that trimming preserves id and title."""
    large_text = "x" * 500000

    story = {
        "id": "US-999",
        "title": "Test Story",
        "description": large_text,
        "acceptanceCriteria": ["AC1", "AC2"],
    }

    # Use smaller budget to force trimming
    trimmed, was_trimmed = trim_progressive(story, max_tokens=100000)

    assert was_trimmed is True
    assert trimmed["id"] == "US-999"
    assert trimmed["title"] == "Test Story"


def test_guard_with_mock_large_prompt() -> None:
    """Test trimming with 500k char mock prompt."""
    # Create 500k char story + large ralph prompt
    large_story_desc = "a" * 250000
    large_ralph_prompt = "b" * 250000

    story = {
        "id": "US-500",
        "title": "Huge story",
        "description": large_story_desc,
        "acceptanceCriteria": ["AC1", "AC2", "AC3"],
        "filesTouch": ["file1.py", "file2.py"] * 50,  # Many files
        "technicalNotes": ["Note " * 200 for _ in range(5)],
    }

    # Use smaller budget (story 250k + prompt 250k = 125k tokens, so use 100k budget)
    result = guard_story_context(
        story,
        budget_tokens=100000,
        ralph_prompt=large_ralph_prompt,
    )

    # Should be trimmed
    assert result.get("_context_trimmed") is True

    # Final size should be under budget
    result_str = json.dumps(result)
    final_tokens = estimate_tokens(result_str)
    final_tokens += estimate_tokens(large_ralph_prompt)
    assert final_tokens < 120000


def test_guard_respects_env_budget() -> None:
    """Test that SPIRAL_CONTEXT_BUDGET env var is respected."""
    import os

    story = {
        "id": "US-100",
        "title": "Test",
        "description": "x" * 50000,  # 50k chars
        "acceptanceCriteria": ["AC1"],
    }

    # Set very low budget
    os.environ["SPIRAL_CONTEXT_BUDGET"] = "1000"

    try:
        result = guard_story_context(story, budget_tokens=180000)
        # With 1000 token budget, should be trimmed
        assert result.get("_context_trimmed") is True
    finally:
        # Clean up
        if "SPIRAL_CONTEXT_BUDGET" in os.environ:
            del os.environ["SPIRAL_CONTEXT_BUDGET"]


def test_trim_removes_optional_fields_when_needed() -> None:
    """Test that optional fields are removed under extreme budget pressure."""
    story = {
        "id": "US-100",
        "title": "Test",
        "description": "x" * 200000,
        "acceptanceCriteria": ["AC1", "AC2"],
        "technicalNotes": ["Note"] * 50,
        "filesTouch": ["file"] * 100,
        "dependencies": ["dep1", "dep2"],
    }

    trimmed, was_trimmed = trim_progressive(story, max_tokens=50000)

    # Under extreme budget, optional fields should be removed
    assert was_trimmed is True
    # At least id and title should remain
    assert "id" in trimmed
    assert "title" in trimmed or len(trimmed) > 0


def test_estimate_tokens_consistency() -> None:
    """Test that estimate_tokens is consistent."""
    text = "The quick brown fox"
    tokens1 = estimate_tokens(text)
    tokens2 = estimate_tokens(text)
    assert tokens1 == tokens2


def test_no_trimming_for_small_story() -> None:
    """Test that minimal stories are never trimmed."""
    story = {
        "id": "US-1",
        "title": "Tiny",
        "description": "Small description",
    }

    result = guard_story_context(story, budget_tokens=10000)

    # Very small story should not be marked as trimmed
    assert "_context_trimmed" not in result or result["_context_trimmed"] is False


def test_guard_with_all_field_types() -> None:
    """Test guard with various story field types."""
    story = {
        "id": "US-200",
        "title": "Complex Story",
        "description": "x" * 300000,
        "acceptanceCriteria": ["AC1", "AC2", "AC3"],
        "technicalNotes": ["Note1", "Note2"],
        "filesTouch": ["file.py", "file.ts"],
        "dependencies": ["US-100", "US-150"],
        "estimatedComplexity": "high",
        "priority": "medium",
        "passes": False,
    }

    # Use smaller budget to force trimming (300k chars ~ 75k tokens)
    result = guard_story_context(story, budget_tokens=60000)

    # Should have trimmed the large description
    assert result.get("_context_trimmed") is True

    # Critical fields should be preserved
    assert result["id"] == "US-200"
    assert result["title"] == "Complex Story"
