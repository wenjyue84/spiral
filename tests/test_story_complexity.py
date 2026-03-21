"""Tests for US-642: CLI predict-story-complexity.

Complexity scoring based on semantic similarity and historical retry patterns.
"""

import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "routing"))

from routing.complexity_scorer import (  # noqa: E402
    compute_complexity_score,
    compute_embedding,
    cosine_similarity,
    find_similar_stories,
    load_story_history,
    predict_story_complexity,
)


class TestEmbedding:
    """Test embedding computation."""

    def test_compute_embedding_basic(self) -> None:
        """Test that embedding returns a vector."""
        text = "Add authentication to dashboard"
        emb = compute_embedding(text)
        assert isinstance(emb, list)
        assert len(emb) == 384  # all-MiniLM-L6-v2 output size
        assert all(isinstance(x, float) for x in emb)

    def test_compute_embedding_empty(self) -> None:
        """Test empty text returns zero vector."""
        emb = compute_embedding("")
        assert len(emb) > 0  # Returns a zero vector
        assert all(x == 0.0 for x in emb)

    def test_compute_embedding_consistency(self) -> None:
        """Test same text produces same embedding."""
        text = "Implement caching layer"
        emb1 = compute_embedding(text)
        emb2 = compute_embedding(text)
        assert emb1 == emb2


class TestSimilarity:
    """Test cosine similarity computation."""

    def test_cosine_similarity_identical(self) -> None:
        """Test identical vectors have similarity 1.0."""
        vec = [1.0, 0.0, 0.0]
        sim = cosine_similarity(vec, vec)
        assert sim == 1.0

    def test_cosine_similarity_orthogonal(self) -> None:
        """Test orthogonal vectors have similarity 0.0."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        assert sim == 0.0

    def test_cosine_similarity_partial(self) -> None:
        """Test partially similar vectors."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 1.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        assert 0.5 < sim < 1.0

    def test_cosine_similarity_zero_vector(self) -> None:
        """Test zero vector returns 0 similarity."""
        vec1 = [0.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        assert sim == 0.0

    def test_cosine_similarity_mismatched_length(self) -> None:
        """Test mismatched vector lengths return 0."""
        vec1 = [1.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        assert sim == 0.0


class TestComplexityScore:
    """Test complexity score derivation."""

    def test_score_no_retries(self) -> None:
        """Test score for 0 retries is 1 (easy)."""
        score = compute_complexity_score(0, 0)
        assert score == 1

    def test_score_one_retry(self) -> None:
        """Test score for 1 retry is moderate (2-3)."""
        score = compute_complexity_score(1, 0)
        assert 2 <= score <= 3

    def test_score_two_retries(self) -> None:
        """Test score for 2 retries is higher (4-6)."""
        score = compute_complexity_score(2, 0)
        assert 4 <= score <= 6

    def test_score_three_plus_retries(self) -> None:
        """Test score for 3+ retries is high (7-10)."""
        score = compute_complexity_score(3, 0)
        assert 7 <= score <= 10

    def test_score_high_tokens(self) -> None:
        """Test high token usage increases score."""
        score_low = compute_complexity_score(0, 0)
        score_high = compute_complexity_score(0, 100001)
        assert score_high > score_low

    def test_score_range(self) -> None:
        """Test score is always in range 1-10."""
        for retries in range(0, 6):
            for tokens in [0, 50000, 100000, 200000]:
                score = compute_complexity_score(retries, tokens)
                assert 1 <= score <= 10


class TestLoadHistory:
    """Test loading story history from results.tsv."""

    def test_load_empty_results(self, tmp_path: Path) -> None:
        """Test loading non-existent file returns empty list."""
        tsv_path = tmp_path / "results.tsv"
        history = load_story_history(tsv_path)
        assert history == []

    def test_load_results_tsv(self, tmp_path: Path) -> None:
        """Test loading valid results.tsv."""
        tsv_path = tmp_path / "results.tsv"
        with open(tsv_path, "w", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, delimiter="\t", fieldnames=["story_id", "story_title", "retry_num", "status", "duration_sec"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001",
                    "story_title": "Add auth",
                    "retry_num": "0",
                    "status": "pass",
                    "duration_sec": "120",
                }
            )
            writer.writerow(
                {
                    "story_id": "US-002",
                    "story_title": "Fix bug",
                    "retry_num": "2",
                    "status": "pass",
                    "duration_sec": "300",
                }
            )

        history = load_story_history(tsv_path)
        assert len(history) == 2
        assert history[0]["story_id"] == "US-001"
        assert history[0]["retry_num"] == 0
        assert history[1]["retry_num"] == 2

    def test_load_results_tsv_missing_fields(self, tmp_path: Path) -> None:
        """Test loading TSV with missing optional fields."""
        tsv_path = tmp_path / "results.tsv"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("story_id\tstory_title\n")
            f.write("US-001\tAdd auth\n")

        history = load_story_history(tsv_path)
        assert len(history) == 1
        assert history[0]["story_id"] == "US-001"
        assert history[0]["retry_num"] == 0  # Default


class TestFindSimilarStories:
    """Test finding similar stories from history."""

    def test_find_similar_empty_history(self) -> None:
        """Test with empty history returns empty list."""
        similar = find_similar_stories("Add dashboard", [], top_k=3)
        assert similar == []

    def test_find_similar_basic(self) -> None:
        """Test finding similar stories."""
        history = [
            {
                "story_id": "US-001",
                "story_title": "Add dashboard",
                "retry_num": 0,
                "duration_sec": 100,
            },
            {
                "story_id": "US-002",
                "story_title": "Add authentication",
                "retry_num": 1,
                "duration_sec": 150,
            },
            {
                "story_id": "US-003",
                "story_title": "Fix database",
                "retry_num": 2,
                "duration_sec": 200,
            },
        ]
        similar = find_similar_stories("Add admin panel", history, top_k=2)
        assert len(similar) <= 2
        assert all("similarity" in s for s in similar)
        assert all("id" in s for s in similar)
        assert all("avg_retries" in s for s in similar)

    def test_find_similar_top_k(self) -> None:
        """Test top_k parameter limits results."""
        history = [
            {"story_id": f"US-{i:03d}", "story_title": f"Story {i}", "retry_num": 0, "duration_sec": 100}
            for i in range(10)
        ]
        similar = find_similar_stories("Story", history, top_k=3)
        assert len(similar) <= 3


class TestPredictComplexity:
    """Test predict_story_complexity function."""

    def test_predict_basic(self, tmp_path: Path) -> None:
        """Test basic complexity prediction."""
        prd_path = tmp_path / "prd.json"
        results_path = tmp_path / "results.tsv"

        # Create prd.json
        prd_data = {
            "userStories": [
                {
                    "id": "US-100",
                    "description": "Add dashboard with real-time metrics",
                }
            ]
        }
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd_data, f)

        # Create results.tsv
        with open(results_path, "w", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, delimiter="\t", fieldnames=["story_id", "story_title", "retry_num", "status", "duration_sec"]
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001",
                    "story_title": "Dashboard setup",
                    "retry_num": "1",
                    "status": "pass",
                    "duration_sec": "120",
                }
            )

        result = predict_story_complexity(
            story_id="US-100",
            story_description="Add dashboard with real-time metrics",
            prd_path=prd_path,
            results_tsv_path=results_path,
        )

        assert result["story_id"] == "US-100"
        assert 1 <= result["score"] <= 10
        assert result["label"] in ["easy", "medium", "hard"]
        assert isinstance(result["similar"], list)

    def test_predict_score_correlates_with_history(self, tmp_path: Path) -> None:
        """Test that high scores correlate with retry_count >= 2 in history."""
        prd_path = tmp_path / "prd.json"
        results_path = tmp_path / "results.tsv"

        prd_data = {
            "userStories": [
                {
                    "id": "US-999",
                    "description": "Complex feature needing fixes",
                }
            ]
        }
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump(prd_data, f)

        # Create results with high-retry stories
        with open(results_path, "w", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, delimiter="\t", fieldnames=["story_id", "story_title", "retry_num", "status", "duration_sec"]
            )
            writer.writeheader()
            for i in range(5):
                writer.writerow(
                    {
                        "story_id": f"US-{i:03d}",
                        "story_title": "Complex feature",
                        "retry_num": "2",
                        "status": "pass",
                        "duration_sec": "300",
                    }
                )

        result = predict_story_complexity(
            story_id="US-999",
            story_description="Complex feature needing fixes",
            prd_path=prd_path,
            results_tsv_path=results_path,
        )

        # With avg_retries >= 2 in similar stories, score should be higher
        if result["similar"]:
            avg_retries = sum(s["avg_retries"] for s in result["similar"]) / len(result["similar"])
            if avg_retries >= 2:
                assert result["score"] >= 4, f"Expected score >= 4 for avg_retries={avg_retries}"


@pytest.fixture
def fixture_15_stories(tmp_path: Path) -> tuple[Path, Path]:
    """Fixture: Create prd.json and results.tsv with 15 diverse stories."""
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    # Create prd.json with 15 stories
    prd_data = {
        "userStories": [
            {"id": "US-100", "description": "Add authentication layer"},
            {"id": "US-101", "description": "Fix critical bug in auth"},
            {"id": "US-102", "description": "Implement caching"},
            {"id": "US-103", "description": "Fix caching issues"},
            {"id": "US-104", "description": "Fix more caching issues"},
            {"id": "US-105", "description": "Add dashboard"},
            {"id": "US-106", "description": "Add admin dashboard"},
            {"id": "US-107", "description": "Fix admin dashboard"},
            {"id": "US-108", "description": "Add API"},
            {"id": "US-109", "description": "Fix API"},
            {"id": "US-110", "description": "Improve performance"},
            {"id": "US-111", "description": "Refactor database layer"},
            {"id": "US-112", "description": "Fix database issues"},
            {"id": "US-113", "description": "Add monitoring"},
            {"id": "US-114", "description": "Fix monitoring"},
        ]
    }
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f)

    # Create results.tsv with varying retry counts
    retry_counts = [0, 0, 1, 1, 2, 2, 2, 3, 3, 3, 1, 2, 3, 0, 1]
    with open(results_path, "w", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, delimiter="\t", fieldnames=["story_id", "story_title", "retry_num", "status", "duration_sec"]
        )
        writer.writeheader()
        for i, retry_count in enumerate(retry_counts):
            writer.writerow(
                {
                    "story_id": f"US-{i:03d}",
                    "story_title": prd_data["userStories"][i]["description"],
                    "retry_num": str(retry_count),
                    "status": "pass",
                    "duration_sec": str(100 + retry_count * 50),
                }
            )

    return prd_path, results_path


class TestWith15StoryFixture:
    """Test predict_story_complexity with 15-story fixture."""

    def test_fixture_has_15_stories(self, fixture_15_stories: tuple[Path, Path]) -> None:
        """Verify fixture has 15 stories."""
        prd_path, results_path = fixture_15_stories
        history = load_story_history(results_path)
        assert len(history) == 15

    def test_predict_all_15_stories(self, fixture_15_stories: tuple[Path, Path]) -> None:
        """Test predicting complexity for all 15 fixture stories."""
        prd_path, results_path = fixture_15_stories

        with open(prd_path, encoding="utf-8") as f:
            prd_data = json.load(f)

        for story in prd_data["userStories"]:
            story_id = story["id"]
            description = story["description"]
            result = predict_story_complexity(
                story_id=story_id,
                story_description=description,
                prd_path=prd_path,
                results_tsv_path=results_path,
            )

            assert result["story_id"] == story_id
            assert 1 <= result["score"] <= 10
            assert result["label"] in ["easy", "medium", "hard"]

    def test_high_scores_correlate_with_retries(self, fixture_15_stories: tuple[Path, Path]) -> None:
        """Test that high scores correlate with retry_count >= 2."""
        prd_path, results_path = fixture_15_stories
        history = load_story_history(results_path)

        with open(prd_path, encoding="utf-8") as f:
            prd_data = json.load(f)

        # Stories with retry_num >= 2
        high_retry_stories = [s for s in history if s["retry_num"] >= 2]
        assert len(high_retry_stories) > 0, "Fixture should have stories with retry >= 2"

        # Sample a high-retry story
        high_retry_story_id = high_retry_stories[0]["story_id"]
        idx = int(high_retry_story_id.split("-")[1])
        story_desc = prd_data["userStories"][idx]["description"]

        result = predict_story_complexity(
            story_id=high_retry_story_id,
            story_description=story_desc,
            prd_path=prd_path,
            results_tsv_path=results_path,
        )

        # With similar stories having high retries, score should be moderate-to-high
        assert result["score"] >= 2, f"Expected score >= 2 for story {high_retry_story_id}"
