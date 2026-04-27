"""Tests for hint recommender (US-1299)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from hint_recommender import (
    analyze_story_cohort,
    enrich_stories_with_hints,
    suggest_hints_from_history,
)


def _write_results_tsv(path: str, records: list[dict[str, str]]) -> None:
    """Write sample results.tsv for testing."""
    headers = [
        "timestamp",
        "spiral_iter",
        "ralph_iter",
        "story_id",
        "story_title",
        "status",
        "duration_sec",
        "model",
        "retry_num",
        "estimatedComplexity",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(headers) + "\n")
        for record in records:
            row = [record.get(h, "") for h in headers]
            f.write("\t".join(row) + "\n")


def _write_prd_json(path: str, stories: list[dict[str, str]]) -> None:
    """Write sample prd.json for testing."""
    prd = {"userStories": stories}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prd, f)


class TestSuggestHintsSchema:
    """Test schema of suggest_hints_from_history() output."""

    def test_suggest_hints_schema(self, tmp_path: Path) -> None:
        """Test that suggest_hints_from_history returns correct schema."""
        results = [
            {
                "story_id": "US-100",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-101",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
        ]

        story = {
            "id": "US-102",
            "title": "Test Story",
            "description": "Test description",
            "estimatedComplexity": "small",
            "filesTouch": ["file1.py", "file2.py"],
        }

        hints = suggest_hints_from_history(story, results)

        # Assert required keys exist
        assert "decomposition_suggested" in hints
        assert "recommended_model" in hints
        assert "recommended_retries" in hints

        # Assert types
        assert isinstance(hints["decomposition_suggested"], (bool, str))
        assert isinstance(hints["recommended_model"], str)
        assert isinstance(hints["recommended_retries"], int)


class TestLowHaikuPassRateEscalatesModel:
    """Test model escalation when haiku pass rate is low."""

    def test_low_haiku_pass_rate_escalates_model(self, tmp_path: Path) -> None:
        """Test that recommended_model is 'sonnet' when haiku pass rate < 50%."""
        # Create results.tsv with 3 haiku failures and 1 success (25% pass rate)
        results = [
            {
                "story_id": "US-001",
                "status": "reject",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-002",
                "status": "reject",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-003",
                "status": "reject",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-004",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-005",
                "status": "pass",
                "model": "sonnet",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
        ]

        story = {
            "id": "US-100",
            "title": "Small complexity story",
            "description": "Test",
            "estimatedComplexity": "small",
            "filesTouch": ["file.py"],
        }

        hints = suggest_hints_from_history(story, results)

        # With 25% haiku pass rate (1/4), should escalate to sonnet
        assert hints["recommended_model"] == "sonnet"


class TestHintsPersistToPrd:
    """Test that hints are persisted to prd.json structure."""

    def test_hints_persisted_to_prd(self, tmp_path: Path) -> None:
        """Test that enrich_stories_with_hints adds _hints to stories."""
        results = [
            {
                "story_id": "US-001",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
        ]

        stories = [
            {
                "id": "US-100",
                "title": "Test Story",
                "description": "Test",
                "estimatedComplexity": "small",
                "filesTouch": ["file.py"],
            },
        ]

        enriched = enrich_stories_with_hints(stories, results)

        assert len(enriched) == 1
        assert "_hints" in enriched[0]
        assert isinstance(enriched[0]["_hints"], list)
        assert len(enriched[0]["_hints"]) > 0

        # _hints[0] should have the schema we expect
        hints = enriched[0]["_hints"][0]
        assert "decomposition_suggested" in hints
        assert "recommended_model" in hints
        assert "recommended_retries" in hints


class TestAnalizeStoryCohort:
    """Test cohort analysis by complexity band and model."""

    def test_analyze_story_cohort(self, tmp_path: Path) -> None:
        """Test that analyze_story_cohort groups by complexity and calculates pass rate."""
        results = [
            {
                "story_id": "US-001",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-002",
                "status": "reject",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-003",
                "status": "pass",
                "model": "sonnet",
                "retry_num": "0",
                "estimatedComplexity": "small",
            },
            {
                "story_id": "US-004",
                "status": "pass",
                "model": "haiku",
                "retry_num": "0",
                "estimatedComplexity": "medium",
            },
        ]

        # Analyze small complexity band
        cohort = analyze_story_cohort(results, "small")

        assert "haiku" in cohort
        assert "sonnet" in cohort
        assert cohort["haiku"]["pass_count"] == 1
        assert cohort["haiku"]["fail_count"] == 1
        assert cohort["haiku"]["pass_rate"] == 0.5

        # Medium complexity should not include small stories
        cohort_medium = analyze_story_cohort(results, "medium")
        assert "haiku" in cohort_medium
        assert cohort_medium["haiku"]["pass_count"] == 1
        assert cohort_medium["haiku"]["fail_count"] == 0


class TestDecompositionSuggestion:
    """Test decomposition suggestion logic."""

    def test_decomposition_from_many_files(self, tmp_path: Path) -> None:
        """Test that stories with >5 files suggest decomposition."""
        results: list[dict[str, str]] = []

        story = {
            "id": "US-100",
            "title": "Large story",
            "description": "Touches many files",
            "estimatedComplexity": "medium",
            "filesTouch": [f"file{i}.py" for i in range(7)],
        }

        hints = suggest_hints_from_history(story, results)

        assert hints["decomposition_suggested"] is True or isinstance(hints["decomposition_suggested"], str)

    def test_decomposition_from_previous_failures(self, tmp_path: Path) -> None:
        """Test that stories with retry_num >= 2 suggest decomposition."""
        results = [
            {
                "story_id": "US-100",
                "status": "reject",
                "model": "haiku",
                "retry_num": "2",
                "estimatedComplexity": "small",
            },
        ]

        story = {
            "id": "US-100",
            "title": "Failing story",
            "description": "Has been retried",
            "estimatedComplexity": "small",
            "filesTouch": ["file.py"],
        }

        hints = suggest_hints_from_history(story, results)

        assert hints["decomposition_suggested"] is True
        assert hints["recommended_retries"] >= 3
