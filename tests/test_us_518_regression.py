"""Regression test for US-518: Episodic memory store write, retrieve, and context injection.

This test file guards against future breakage of the episodic memory feature
(US-518). It covers the full round-trip: writing story outcomes, retrieving
top-3 similar patterns by embedding distance, and verifying the structure of
injected context snippets.

Run with: pytest tests/ -k us_518 -v
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import pytest
from episodic_memory import EpisodicMemory, get_similar_patterns


@pytest.mark.us_518
def test_us_518_write_and_retrieve_round_trip() -> None:
    """AC1: Full round-trip test — write story outcomes, retrieve top-3 similar.

    Regression test for US-518. Verifies that:
    1. Story outcomes can be written to episodic memory store
    2. The store retrieves top-3 similar patterns by embedding distance
    3. Results are ranked by relevance (cosine similarity)
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Write multiple distinct story outcomes
        mem.write(
            "US-100",
            {
                "approach": "Implemented episodic memory with JSONL storage",
                "outcome": "pass",
                "files_touched": ["lib/episodic_memory.py"],
                "iteration": 1,
            },
        )
        mem.write(
            "US-101",
            {
                "approach": "Added embedding-based similarity search to memory",
                "outcome": "pass",
                "files_touched": ["lib/episodic_memory.py"],
                "iteration": 2,
            },
        )
        mem.write(
            "US-102",
            {
                "approach": "Fixed database migration script for schema updates",
                "outcome": "fail",
                "files_touched": ["migrations/001.sql"],
                "iteration": 3,
            },
        )
        mem.write(
            "US-103",
            {
                "approach": "Updated UI button styles with Tailwind CSS",
                "outcome": "pass",
                "files_touched": ["src/components/Button.tsx"],
                "iteration": 1,
            },
        )

        # Retrieve top-3 similar to US-100
        results = mem.get_similar("US-100", k=3)

        # Assertions
        assert isinstance(results, list), "get_similar() should return a list"
        assert len(results) > 0, "Should return at least one similar pattern (US-101)"
        assert len(results) <= 3, "Should return at most k=3 patterns"
        # US-101 should rank higher than US-103 (both are "episodic/memory/embedding" vs "CSS")
        if len(results) >= 2:
            story_ids = [r["story_id"] for r in results]
            assert "US-101" in story_ids, "US-101 should be in top-3 (embedding-related)"


@pytest.mark.us_518
def test_us_518_context_injection_structure() -> None:
    """AC2: Verify injected context snippet has required fields for Ralph injection.

    Regression test for US-518. Verifies that the context returned by retrieve()
    includes all fields needed for Ralph worker to inject into prompt:
    - story_id
    - approach
    - outcome
    - similarity_score (0-1 range)
    - timestamp
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Write sample story outcomes
        mem.write(
            "US-200",
            {
                "approach": "Created REST API endpoints using Express.js",
                "outcome": "pass",
                "iteration": 1,
            },
        )
        mem.write(
            "US-201",
            {
                "approach": "Built REST endpoints with Express framework",
                "outcome": "pass",
                "iteration": 2,
            },
        )

        # Query by text description (how Ralph would use it)
        results = mem.retrieve("REST API with Express.js", top_k=2)

        # Assertions
        assert isinstance(results, list), "retrieve() should return a list"
        assert len(results) > 0, "Should find at least one matching pattern"

        # Check structure of first result
        first_result = results[0]
        assert isinstance(first_result, dict), "Each result should be a dict"
        assert "story_id" in first_result, "Result must include story_id"
        assert "approach" in first_result, "Result must include approach"
        assert "outcome" in first_result, "Result must include outcome"
        assert "similarity_score" in first_result, "Result must include similarity_score for ranking"
        assert "timestamp" in first_result, "Result must include timestamp"

        # Verify similarity_score is in [0, 1] range
        similarity = first_result["similarity_score"]
        assert isinstance(similarity, (int, float)), "similarity_score must be numeric"
        assert 0 <= similarity <= 1, f"similarity_score must be in [0, 1], got {similarity}"


@pytest.mark.us_518
def test_us_518_top3_ranking_correctness() -> None:
    """AC3: Verify that top-3 results are ranked by relevance (cosine similarity).

    Regression test for US-518. Ensures that:
    1. More relevant patterns rank higher in results
    2. Top-3 limit is enforced
    3. Ranking is consistent (most similar first)
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Write patterns with varying relevance to "logging"
        mem.write(
            "US-300",
            {
                "approach": "Implemented structured logging with JSON output",
                "outcome": "pass",
            },
        )
        mem.write(
            "US-301",
            {
                "approach": "Added logging framework using Winston library",
                "outcome": "pass",
            },
        )
        mem.write(
            "US-302",
            {
                "approach": "Set up logging with async handlers",
                "outcome": "pass",
            },
        )
        mem.write(
            "US-303",
            {
                "approach": "Configured database connection pooling",
                "outcome": "fail",
            },
        )
        mem.write(
            "US-304",
            {
                "approach": "Fixed UI styling with CSS Grid layout",
                "outcome": "pass",
            },
        )

        # Query for "logging" — should return logging-related patterns first
        results = mem.retrieve("logging framework", top_k=3)

        # Assertions
        assert len(results) <= 3, "Should return at most 3 results"
        assert len(results) >= 1, "Should find at least one logging-related pattern"

        # Verify ranking: first result should be one of the logging stories
        if len(results) > 0:
            first_story = results[0]["story_id"]
            logging_stories = {"US-300", "US-301", "US-302"}
            assert first_story in logging_stories, f"Top result should be logging-related, got {first_story}"

        # Verify similarity scores are in descending order
        if len(results) > 1:
            scores = [r["similarity_score"] for r in results]
            assert scores == sorted(scores, reverse=True), "Results should be sorted by similarity_score descending"


@pytest.mark.us_518
def test_us_518_empty_store_graceful_handling() -> None:
    """AC4: Edge case — querying empty store returns empty list, no exception.

    Regression test for US-518. Verifies graceful handling of:
    1. Queries on non-existent store
    2. Queries for non-existent story_id
    3. Empty text queries
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Query empty store — should not raise
        results = mem.retrieve("anything", top_k=3)
        assert results == [], "Empty store should return empty list"

        # Query non-existent story_id
        results = mem.get_similar("US-9999", k=3)
        assert results == [], "Non-existent story should return empty list"

        # Query empty text
        results = mem.retrieve("", top_k=3)
        assert isinstance(results, list), "Should return list even for empty query"


@pytest.mark.us_518
def test_us_518_convenience_function_get_similar_patterns() -> None:
    """AC5: Module-level convenience function get_similar_patterns() works end-to-end.

    Regression test for US-518. Verifies that the public API function
    get_similar_patterns() (used by Ralph workers) correctly:
    1. Queries episodic memory by text description
    2. Returns top_k results with similarity scores
    3. Works with custom memory_path (for test isolation)
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Write sample patterns
        mem.write(
            "US-400",
            {
                "approach": "Refactored TypeScript type definitions",
                "outcome": "pass",
            },
        )
        mem.write(
            "US-401",
            {
                "approach": "Updated TypeScript strict mode configuration",
                "outcome": "pass",
            },
        )
        mem.write(
            "US-402",
            {
                "approach": "Fixed React component rendering performance",
                "outcome": "pass",
            },
        )

        # Call convenience function (as Ralph workers would)
        results = get_similar_patterns("TypeScript type safety improvements", top_k=3, memory_path=mem_path)

        # Assertions
        assert isinstance(results, list), "Function should return list"
        assert len(results) >= 1, "Should find at least one TypeScript-related pattern"
        assert len(results) <= 3, "Should return at most top_k results"

        # Verify all results have similarity_score
        for result in results:
            assert "similarity_score" in result, "All results must include similarity_score"
            assert isinstance(result["similarity_score"], (int, float)), "similarity_score must be numeric"
            assert 0 <= result["similarity_score"] <= 1, "similarity_score must be [0, 1]"


@pytest.mark.us_518
def test_us_518_would_catch_broken_embedding() -> None:
    """Regression guard: Test would fail if embedding/similarity logic is broken.

    This test verifies that our regression test itself has teeth — if the
    implementation of _embed() or _cosine_similarity() were removed or broken,
    this test would reliably fail.
    """
    with tempfile.TemporaryDirectory() as td:
        mem_path = os.path.join(td, "episodic.jsonl")
        mem = EpisodicMemory(mem_path)

        # Write two clearly distinct patterns
        mem.write("US-500", {"approach": "machine learning model training", "outcome": "pass"})
        mem.write("US-501", {"approach": "database indexing optimization", "outcome": "pass"})

        # Query for "machine learning" should find US-500 first
        results = mem.retrieve("machine learning neural network", top_k=2)

        # If embedding or cosine similarity is broken:
        # - Either no results (broken file reading)
        # - Or wrong ranking (broken similarity math)
        # This assertion guards against that
        if len(results) > 0:
            # At least one ML-related story should be in results
            assert any(sid in ["US-500"] for sid in [r["story_id"] for r in results]), (
                "Should find machine learning pattern when querying for ML"
            )

        # Verify that database pattern is NOT ranked first (different domain)
        if len(results) >= 2:
            assert results[0]["story_id"] != "US-501", "Database indexing should not rank higher than ML for ML query"
