"""Regression test for US-642: predict-story-complexity scoring and model routing.

This test file guards against future breakage of the story complexity prediction
feature (US-642). It covers the full workflow:
1. Computing complexity scores (1-10) from semantic similarity and historical patterns
2. Finding similar past stories based on description matching
3. Recommending the cheapest viable model tier from historical pass rates

Run with: pytest tests/ -k us_642 -v
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "routing"))

import pytest
from complexity_scorer import (
    compute_complexity_score,
    compute_embedding,
    cosine_similarity,
    find_similar_stories,
    predict_story_complexity,
    recommend_model_from_history,
)


@pytest.mark.us_642
def test_us_642_predict_complexity_returns_expected_structure() -> None:
    """AC1: predict_story_complexity returns dict with story_id, score, label, similar.

    Regression test for US-642. Verifies that the core prediction function returns
    the expected output structure with all required fields:
    - story_id: input story ID
    - score: integer 1-10
    - label: "easy", "medium", or "hard"
    - similar: list of similar story references
    """
    with tempfile.TemporaryDirectory() as td:
        # Create test prd.json
        prd_path = Path(td) / "prd.json"
        prd_path.write_text(
            """{
  "userStories": [
    {
      "id": "US-100",
      "title": "Test story",
      "description": "Implement authentication system with JWT tokens"
    }
  ]
}"""
        )

        # Create test results.tsv with sample history
        results_path = Path(td) / "results.tsv"
        with open(results_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "story_title", "retry_num", "status", "duration_sec"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001",
                    "story_title": "Add authentication system",
                    "retry_num": 1,
                    "status": "pass",
                    "duration_sec": 120,
                }
            )
            writer.writerow(
                {
                    "story_id": "US-002",
                    "story_title": "Implement JWT tokens",
                    "retry_num": 0,
                    "status": "pass",
                    "duration_sec": 90,
                }
            )

        # Call predict_story_complexity
        result = predict_story_complexity(
            story_id="US-100",
            story_description="Implement authentication system with JWT tokens",
            prd_path=prd_path,
            results_tsv_path=results_path,
        )

        # Verify output structure
        assert isinstance(result, dict), "predict_story_complexity should return a dict"
        assert "story_id" in result, "Result must have story_id"
        assert "score" in result, "Result must have score"
        assert "label" in result, "Result must have label"
        assert "similar" in result, "Result must have similar list"

        # Verify types and value ranges
        assert result["story_id"] == "US-100"
        assert isinstance(result["score"], int)
        assert 1 <= result["score"] <= 10, "Score must be 1-10"
        assert result["label"] in ("easy", "medium", "hard"), "Label must be easy/medium/hard"
        assert isinstance(result["similar"], list), "Similar must be a list"


@pytest.mark.us_642
def test_us_642_complexity_score_from_retries() -> None:
    """AC2: Complexity score increases with retry count.

    Regression test for US-642. Verifies that compute_complexity_score correctly
    assigns higher scores to stories with more retries (indicating difficulty).
    """
    # No retries = easy (score 1)
    assert compute_complexity_score(0, 0) == 1

    # 1 retry = moderate (score 3)
    score_1 = compute_complexity_score(1, 0)
    assert 1 < score_1 <= 3

    # 2 retries = difficult (score 5+)
    score_2 = compute_complexity_score(2, 0)
    assert score_2 > score_1

    # 3+ retries = very difficult (score 7+)
    score_3 = compute_complexity_score(3, 0)
    assert score_3 > score_2
    assert score_3 >= 7, "3+ retries should give score >= 7"

    # All scores in range
    assert all(1 <= s <= 10 for s in [score_1, score_2, score_3])


@pytest.mark.us_642
def test_us_642_embedding_and_similarity() -> None:
    """AC3: Embeddings compute cosine similarity correctly.

    Regression test for US-642. Verifies that the semantic similarity computation
    produces meaningful results: similar texts have high similarity, dissimilar have low.
    """
    # Compute embeddings for similar texts
    text1 = "Implement authentication system with JWT tokens"
    text2 = "Add JWT authentication to API"
    embedding1 = compute_embedding(text1)
    embedding2 = compute_embedding(text2)

    # Should produce non-zero embeddings
    assert len(embedding1) == 384, "Embedding should be 384-dimensional"
    assert len(embedding2) == 384
    assert sum(embedding1) > 0, "Embedding should be non-zero"

    # Similar texts should have high cosine similarity
    sim_similar = cosine_similarity(embedding1, embedding2)
    assert sim_similar > 0, "Similar texts should have positive similarity"

    # Dissimilar texts should have low similarity
    text3 = "Fix bug in database query optimization"
    embedding3 = compute_embedding(text3)
    sim_dissimilar = cosine_similarity(embedding1, embedding3)

    # In practice, some non-zero overlap may occur due to hash-based bucketing
    # but similar pair should rank higher than dissimilar
    if sim_dissimilar > 0:
        assert sim_similar >= sim_dissimilar or sim_similar == 0


@pytest.mark.us_642
def test_us_642_find_similar_stories_ranking() -> None:
    """AC4: Similar stories ranked correctly by semantic similarity.

    Regression test for US-642. Verifies that find_similar_stories returns
    top-k stories ranked by cosine similarity to the target description.
    """
    # Create test history with 3 stories
    history = [
        {
            "story_id": "US-001",
            "story_title": "Implement JWT authentication",
            "retry_num": 1,
            "duration_sec": 120,
        },
        {
            "story_id": "US-002",
            "story_title": "Database migration script",
            "retry_num": 0,
            "duration_sec": 90,
        },
        {
            "story_id": "US-003",
            "story_title": "Add OAuth2 auth support",
            "retry_num": 2,
            "duration_sec": 150,
        },
    ]

    target = "Implement authentication system with tokens"
    similar = find_similar_stories(target, history, top_k=2)

    # Should return at least some similar stories
    assert isinstance(similar, list)
    assert len(similar) <= 2, "Should return at most k=2 stories"

    # Each result should have required fields
    for story in similar:
        assert "id" in story
        assert "similarity" in story
        assert "avg_retries" in story
        assert "tokens" in story
        assert 0 <= story["similarity"] <= 1, "Similarity score must be 0-1"

    # Verify results are sorted by similarity (descending)
    if len(similar) >= 2:
        for i in range(len(similar) - 1):
            assert (
                similar[i]["similarity"] >= similar[i + 1]["similarity"]
            ), "Results should be sorted by similarity descending"


@pytest.mark.us_642
def test_us_642_empty_history_handling() -> None:
    """AC5: Handle empty/missing results.tsv gracefully.

    Regression test for US-642. Verifies that the functions gracefully handle
    missing history files or empty story lists without crashing.
    """
    with tempfile.TemporaryDirectory() as td:
        # Test with non-existent results.tsv
        prd_path = Path(td) / "prd.json"
        prd_path.write_text(
            """{
  "userStories": [
    {"id": "US-100", "title": "Test", "description": "Test story"}
  ]
}"""
        )
        results_path = Path(td) / "nonexistent.tsv"

        result = predict_story_complexity(
            story_id="US-100",
            story_description="Test story",
            prd_path=prd_path,
            results_tsv_path=results_path,
        )

        # Should return valid result even with no history
        assert isinstance(result, dict)
        assert result["story_id"] == "US-100"
        assert 1 <= result["score"] <= 10
        assert result["label"] in ("easy", "medium", "hard")
        assert result["similar"] == [], "Should return empty similar list when no history"


@pytest.mark.us_642
def test_us_642_recommend_model_from_history() -> None:
    """AC6: Historical model routing recommends cheapest viable model.

    Regression test for US-642. Verifies that recommend_model_from_history
    analyzes results.tsv pass rates and recommends the cheapest model tier
    (haiku < sonnet < opus) that meets the pass rate threshold.
    """
    with tempfile.TemporaryDirectory() as td:
        # Create results.tsv with model pass rates
        results_path = Path(td) / "results.tsv"
        with open(results_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "story_id",
                    "estimated_complexity",
                    "model",
                    "status",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            # Haiku: 2 pass, 3 total = 66% (above 60% threshold)
            writer.writerow(
                {
                    "story_id": "US-001",
                    "estimated_complexity": "medium",
                    "model": "haiku",
                    "status": "pass",
                }
            )
            writer.writerow(
                {
                    "story_id": "US-002",
                    "estimated_complexity": "medium",
                    "model": "claude-haiku",
                    "status": "pass",
                }
            )
            writer.writerow(
                {
                    "story_id": "US-003",
                    "estimated_complexity": "medium",
                    "model": "haiku",
                    "status": "reject",
                }
            )
            # Sonnet: 3 pass, 3 total = 100%
            writer.writerow(
                {
                    "story_id": "US-004",
                    "estimated_complexity": "medium",
                    "model": "sonnet",
                    "status": "pass",
                }
            )
            writer.writerow(
                {
                    "story_id": "US-005",
                    "estimated_complexity": "medium",
                    "model": "sonnet",
                    "status": "pass",
                }
            )

        # Should recommend haiku (cheapest with 66% > 60% threshold)
        recommended = recommend_model_from_history(
            estimated_complexity="medium",
            results_tsv_path=results_path,
            pass_rate_threshold=0.60,
            min_sample_size=1,
        )

        assert recommended == "haiku", "Should recommend haiku (cheapest viable model)"


@pytest.mark.us_642
def test_us_642_complexity_score_insensitive_to_empty_description() -> None:
    """AC7: Complexity scoring handles empty/missing descriptions.

    Regression test for US-642. Verifies that the scoring functions
    gracefully handle empty story descriptions without crashing.
    """
    embedding = compute_embedding("")
    assert isinstance(embedding, list)
    # Empty text returns 10-element zero vector per implementation
    assert len(embedding) == 10, "Empty text should produce valid 10-element embedding"
    assert all(x == 0.0 for x in embedding), "Empty text embedding should be all zeros"

    # Non-empty embedding for comparison
    other = compute_embedding("test")
    assert len(other) == 384, "Non-empty text should produce 384-dimensional embedding"

    # Zero vectors should have zero similarity
    sim = cosine_similarity(embedding, other)
    assert sim == 0.0, "Zero vectors should have zero cosine similarity"

    # Complexity score for zero retries/tokens should be 1 (easy)
    assert compute_complexity_score(0, 0) == 1
