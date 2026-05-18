"""Tests for lib.research_replay module."""

import json
import tempfile

import pytest

from lib.research_replay import (
    ResearchResult,
    calculate_quality_delta,
    calculate_source_similarity,
    calculate_summary_similarity,
    load_story_research,
    replay_research_queries,
)


@pytest.fixture
def mock_cache_file() -> str:
    """Create a temporary cache file with test research data."""
    cache_data = {
        "cached_queries": [
            {
                "query": "Python async/await patterns",
                "result": json.dumps(
                    {
                        "summary": "Async patterns in Python: using async def and await keywords",
                        "sources": [
                            "https://docs.python.org/async",
                            "https://realpython.com/async-io",
                        ],
                    }
                ),
                "story_id": "US-001",
                "iteration": 1,
                "tokens": ["python", "async"],
            },
            {
                "query": "React hooks state management",
                "result": json.dumps(
                    {
                        "summary": "React hooks provide state and lifecycle features",
                        "sources": [
                            "https://react.dev/reference/react",
                            "https://github.com/react",
                        ],
                    }
                ),
                "story_id": "US-002",
                "iteration": 1,
                "tokens": ["react", "hooks"],
            },
        ]
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(cache_data, f)
        return f.name


def test_load_story_research_found(mock_cache_file: str) -> None:
    """Test loading research for a story that exists in cache."""
    results = load_story_research("US-001", mock_cache_file)
    assert len(results) == 1
    assert results[0].query == "Python async/await patterns"
    assert len(results[0].sources) == 2
    assert "https://docs.python.org/async" in results[0].sources


def test_load_story_research_not_found(mock_cache_file: str) -> None:
    """Test loading research for a story not in cache."""
    results = load_story_research("US-999", mock_cache_file)
    assert len(results) == 0


def test_load_story_research_missing_file() -> None:
    """Test loading from non-existent cache file."""
    results = load_story_research("US-001", "/nonexistent/path.json")
    assert len(results) == 0


def test_calculate_source_similarity_identical() -> None:
    """Test source similarity when URLs are identical."""
    sources = ["https://example.com/a", "https://example.com/b"]
    similarity = calculate_source_similarity(sources, sources)
    assert similarity == 1.0


def test_calculate_source_similarity_partial() -> None:
    """Test source similarity with partial overlap."""
    original = ["https://a.com", "https://b.com", "https://c.com"]
    new = ["https://a.com", "https://b.com", "https://d.com"]
    similarity = calculate_source_similarity(original, new)
    # Intersection = 2, Union = 4, Jaccard = 2/4 = 0.5
    assert similarity == pytest.approx(0.5, rel=0.01)


def test_calculate_source_similarity_disjoint() -> None:
    """Test source similarity with no overlap."""
    original = ["https://a.com", "https://b.com"]
    new = ["https://c.com", "https://d.com"]
    similarity = calculate_source_similarity(original, new)
    assert similarity == 0.0


def test_calculate_source_similarity_empty() -> None:
    """Test source similarity when both are empty."""
    similarity = calculate_source_similarity([], [])
    assert similarity == 1.0


def test_calculate_summary_similarity_identical() -> None:
    """Test summary similarity when text is identical."""
    summary = "This is a test summary about research findings."
    similarity = calculate_summary_similarity(summary, summary)
    assert similarity == 1.0


def test_calculate_summary_similarity_different() -> None:
    """Test summary similarity when text is mostly different."""
    original = "Python is a programming language"
    new = "JavaScript is a web language"
    similarity = calculate_summary_similarity(original, new)
    # Some words overlap (is, a, language), so not 0.0 but less than 0.7
    assert 0.0 < similarity < 0.7


def test_calculate_summary_similarity_empty() -> None:
    """Test summary similarity when both are empty."""
    similarity = calculate_summary_similarity("", "")
    assert similarity == 1.0


def test_calculate_quality_delta_no_change() -> None:
    """Test quality delta when research hasn't changed."""
    original = [
        ResearchResult(
            query="test query",
            summary="This is a summary",
            sources=["https://a.com", "https://b.com"],
        )
    ]
    new = [
        ResearchResult(
            query="test query",
            summary="This is a summary",
            sources=["https://a.com", "https://b.com"],
        )
    ]

    delta = calculate_quality_delta(original, new)
    assert delta.source_similarity == 1.0
    assert delta.summary_similarity == 1.0
    assert delta.combined_delta == 1.0
    assert delta.flag_rerun is False


def test_calculate_quality_delta_minor_change() -> None:
    """Test quality delta with minor changes (< 15% degradation)."""
    original = [
        ResearchResult(
            query="test query",
            summary="Original summary with detailed information",
            sources=["https://a.com", "https://b.com", "https://c.com"],
        )
    ]
    new = [
        ResearchResult(
            query="test query",
            summary="Original summary with detailed information updated",
            sources=["https://a.com", "https://b.com", "https://c.com"],
        )
    ]

    delta = calculate_quality_delta(original, new)
    # Source: 100% match, Summary: ~95% match, Combined: ~97%
    # Should NOT flag for rerun (quality is stable)
    assert delta.combined_delta > 0.85
    assert delta.flag_rerun is False


def test_calculate_quality_delta_major_degradation() -> None:
    """Test quality delta with major degradation (> 15%).

    This is the main acceptance criterion test: delta > 15% should flag rerun.
    """
    original = [
        ResearchResult(
            query="Python async patterns",
            summary="Comprehensive guide to Python async/await with examples",
            sources=[
                "https://docs.python.org",
                "https://realpython.com",
                "https://pep495.example.com",
            ],
        )
    ]
    new = [
        ResearchResult(
            query="Python async patterns",
            summary="JavaScript async patterns explained",
            sources=[
                "https://mdn.org",
                "https://developer.mozilla.org",
                "https://stackoverflow.com",
            ],
        )
    ]

    delta = calculate_quality_delta(original, new)
    # Source similarity: 0 (no overlap)
    # Summary similarity: low (different topics but some word overlap)
    # Combined delta: < 0.25 (flagged for rerun)
    assert delta.source_similarity == 0.0
    assert delta.summary_similarity < 0.5
    assert delta.combined_delta < 0.85
    assert delta.flag_rerun is True


def test_calculate_quality_delta_empty_results() -> None:
    """Test quality delta with empty result lists."""
    delta = calculate_quality_delta([], [])
    assert delta.combined_delta == 0.0
    assert delta.flag_rerun is True


def test_replay_research_queries_basic(mock_cache_file: str) -> None:
    """Test replaying research queries against mock Gemini API."""
    original = load_story_research("US-001", mock_cache_file)
    assert len(original) == 1

    new = replay_research_queries(original)
    assert len(new) == 1
    assert new[0].query == original[0].query


def test_delta_detection() -> None:
    """Main acceptance criterion test: detect research quality delta.

    Verifies that:
    1. High delta (< 15% degradation) is detected
    2. Flag is set when delta exceeds threshold
    3. Report is generated
    """
    original = [
        ResearchResult(
            query="machine learning algorithms",
            summary="Overview of supervised and unsupervised learning algorithms",
            sources=[
                "https://scikit-learn.org",
                "https://tensorflow.org",
                "https://pytorch.org",
            ],
        )
    ]

    # Simulate degraded results (different sources, different summary)
    new = [
        ResearchResult(
            query="machine learning algorithms",
            summary="Web development frameworks and tools for modern apps",
            sources=[
                "https://react.dev",
                "https://vue.js",
                "https://angular.io",
            ],
        )
    ]

    delta = calculate_quality_delta(original, new)

    # Verify AC1: Source ranking changes detected (0% overlap)
    assert delta.source_similarity == 0.0

    # Verify AC2: Summary divergence detected (< 50% similarity)
    assert delta.summary_similarity < 0.5

    # Verify AC3: Quality delta > 15% triggers flag
    assert delta.combined_delta < 0.85
    assert delta.flag_rerun is True
    assert "FLAG" in delta.report or "flag" in delta.report.lower()


def test_quality_delta_with_multiple_queries() -> None:
    """Test quality delta calculation with multiple original queries."""
    original = [
        ResearchResult(
            query="query1",
            summary="summary1",
            sources=["https://a.com", "https://b.com"],
        ),
        ResearchResult(
            query="query2",
            summary="summary2",
            sources=["https://c.com", "https://d.com"],
        ),
    ]

    new = [
        ResearchResult(
            query="query1",
            summary="summary1",
            sources=["https://a.com", "https://b.com"],
        ),
        ResearchResult(
            query="query2",
            summary="different_summary",
            sources=["https://e.com", "https://f.com"],
        ),
    ]

    delta = calculate_quality_delta(original, new)
    # First query matches perfectly, second is different
    # Average source: (1.0 + 0.0) / 2 = 0.5
    assert delta.source_similarity == pytest.approx(0.5, rel=0.01)
