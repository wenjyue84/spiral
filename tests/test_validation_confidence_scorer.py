"""tests/test_validation_confidence_scorer.py — Integration tests for US-1062.

Tests:
  1. score_story() produces 0-100 values.
  2. 10 curated stories: simple stories score >80, complex score <50.
  3. score_all_stories() writes _validation_confidence to prd.json in-place.
  4. Low-confidence stories get prioritized enrichment (score < 50 → in low_confidence list).
  5. 95%+ accuracy against manual labels on 10 curated stories.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Ensure lib/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from validation_confidence_scorer import score_all_stories, score_story  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Curated test stories (10 stories with manual labels)
# label: "simple" → expect score > 80; "complex" → expect score < 50
# ---------------------------------------------------------------------------

_CURATED_STORIES: list[tuple[dict[str, Any], str]] = [
    # 1. Simple UI tweak
    (
        {
            "id": "US-C01",
            "title": "Add button to form",
            "description": "Add a submit button to the contact form.",
            "acceptanceCriteria": ["Button appears on form", "Clicking button submits form"],
            "dependencies": [],
            "filesTouch": ["src/components/ContactForm.tsx"],
        },
        "simple",
    ),
    # 2. Simple label change
    (
        {
            "id": "US-C02",
            "title": "Update page title",
            "description": "Change the landing page heading from 'Welcome' to 'Hello'.",
            "acceptanceCriteria": ["Heading reads Hello"],
            "dependencies": [],
            "filesTouch": [],
        },
        "simple",
    ),
    # 3. Simple config value
    (
        {
            "id": "US-C03",
            "title": "Increase timeout to 30s",
            "description": "Set the HTTP request timeout to 30 seconds.",
            "acceptanceCriteria": ["Timeout is 30 seconds"],
            "dependencies": [],
            "filesTouch": ["config/settings.py"],
        },
        "simple",
    ),
    # 4. Moderately simple — one dep, short description
    (
        {
            "id": "US-C04",
            "title": "Add CSV export button",
            "description": "Export the results table to a CSV file.",
            "acceptanceCriteria": ["CSV file downloads on click"],
            "dependencies": ["US-C01"],
            "filesTouch": [],
        },
        "simple",
    ),
    # 5. Complex: distributed cache with monitoring
    (
        {
            "id": "US-C05",
            "title": "Implement distributed cache with monitoring",
            "description": (
                "Implement a distributed cache layer using Redis with cache invalidation, "
                "monitoring dashboards, and async cache warming on startup."
            ),
            "acceptanceCriteria": [
                "Cache entries expire after TTL",
                "Monitor cache hit rates",
                "Async warm-up on startup",
            ],
            "dependencies": ["US-C01", "US-C02", "US-C03"],
            "filesTouch": ["src/cache/**", "config/redis.config.json"],
        },
        "complex",
    ),
    # 6. Complex: database migration with rollback
    (
        {
            "id": "US-C06",
            "title": "Run database migration with rollback support",
            "description": (
                "Migrate user_accounts table to new schema with transaction support and "
                "rollback on failure. Update all authentication paths."
            ),
            "acceptanceCriteria": [
                "Migration runs inside a transaction",
                "Rollback triggered on error",
                "Authentication still works post-migration",
            ],
            "dependencies": ["US-C01", "US-C02"],
            "filesTouch": ["db/migrations/schema.sql", "src/auth/middleware.ts"],
        },
        "complex",
    ),
    # 7. Complex: concurrent pipeline
    (
        {
            "id": "US-C07",
            "title": "Build concurrent data pipeline",
            "description": (
                "Build a parallel processing pipeline with mutex-based coordination "
                "across worker threads and streaming output to S3."
            ),
            "acceptanceCriteria": [
                "Workers process tasks concurrently",
                "No race conditions under load",
                "Results stream to S3",
            ],
            "dependencies": ["US-C03", "US-C04", "US-C05"],
            "filesTouch": ["src/pipeline/**", "src/workers/**"],
        },
        "complex",
    ),
    # 8. Complex: transaction-based distributed auth with cache + db migration
    (
        {
            "id": "US-C08",
            "title": "Build transaction-based authentication with distributed session cache",
            "description": (
                "Build authentication with distributed session cache using rollback-safe "
                "transactions and database migrations with encryption at rest."
            ),
            "acceptanceCriteria": [
                "Transactions are atomic across cache and database",
                "Cache invalidated on rollback",
                "Authentication passes all tests after migration",
            ],
            "dependencies": ["US-C04", "US-C05", "US-C06"],
            "filesTouch": [
                "src/auth/session/**",
                "config/auth.config.json",
                "db/migrations/auth_schema.sql",
            ],
        },
        "complex",
    ),
    # 9. Simple: doc update
    (
        {
            "id": "US-C09",
            "title": "Update README with quickstart guide",
            "description": "Add a quickstart section to README.md.",
            "acceptanceCriteria": ["README has Quickstart heading"],
            "dependencies": [],
            "filesTouch": ["README.md"],
        },
        "simple",
    ),
    # 10. Complex: federated orchestration
    (
        {
            "id": "US-C10",
            "title": "Implement federated story orchestration with lock coordination",
            "description": (
                "Orchestrate story execution across federated sub-projects using a "
                "distributed lock and async pipeline with transaction-safe merge."
            ),
            "acceptanceCriteria": [
                "Stories execute without deadlock",
                "Federation lock prevents conflicts",
                "Merge is transaction-safe",
            ],
            "dependencies": ["US-C07", "US-C08"],
            "filesTouch": ["lib/federation/**", "lib/impl/lock.py"],
        },
        "complex",
    ),
]


class TestScoreStory:
    def test_returns_int_in_range(self) -> None:
        for story, _ in _CURATED_STORIES:
            score = score_story(story)
            assert isinstance(score, int), f"Expected int, got {type(score)}"
            assert 0 <= score <= 100, f"Score {score} out of range for {story['id']}"

    def test_simple_stories_score_above_80(self) -> None:
        simple_stories = [s for s, label in _CURATED_STORIES if label == "simple"]
        for story in simple_stories:
            score = score_story(story)
            assert score > 80, f"Simple story {story['id']!r} scored {score} (expected >80): {story['description']!r}"

    def test_complex_stories_score_below_50(self) -> None:
        complex_stories = [s for s, label in _CURATED_STORIES if label == "complex"]
        for story in complex_stories:
            score = score_story(story)
            assert score < 50, f"Complex story {story['id']!r} scored {score} (expected <50): {story['description']!r}"

    def test_accuracy_95_percent_on_curated_set(self) -> None:
        """95%+ of stories correctly classified as simple (>80) or complex (<50)."""
        correct = 0
        total = len(_CURATED_STORIES)
        misses: list[str] = []
        for story, label in _CURATED_STORIES:
            score = score_story(story)
            if label == "simple" and score > 80:
                correct += 1
            elif label == "complex" and score < 50:
                correct += 1
            else:
                misses.append(f"{story['id']} label={label} score={score}")
        accuracy = correct / total
        assert accuracy >= 0.95, f"Accuracy {accuracy:.0%} < 95%. Misclassified: {misses}"

    def test_empty_story_scores_100(self) -> None:
        score = score_story({})
        assert score == 100

    def test_many_deps_reduces_score(self) -> None:
        story: dict[str, Any] = {
            "id": "US-TEST",
            "description": "Simple task",
            "dependencies": ["US-1", "US-2", "US-3", "US-4", "US-5", "US-6", "US-7"],
        }
        score = score_story(story)
        assert score < 75, f"Expected score reduced by many deps, got {score}"


class TestScoreAllStories:
    def test_writes_validation_confidence_field(self) -> None:
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-T01", "title": "Add button", "description": "Add a submit button.", "dependencies": []},
                {
                    "id": "US-T02",
                    "title": "Distributed cache",
                    "description": "Implement distributed cache with monitoring and async pipeline.",
                    "dependencies": ["US-T01", "US-X1", "US-X2"],
                },
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(prd, f)
            tmp_path = Path(f.name)

        try:
            summary = score_all_stories(tmp_path)

            # Check summary fields
            assert summary["scored"] == 2
            assert "avg_score" in summary
            assert "low_confidence" in summary

            # Check prd.json was updated in-place
            updated = json.loads(tmp_path.read_text(encoding="utf-8"))
            for story in updated["userStories"]:
                assert "_validation_confidence" in story, f"Missing field on {story['id']}"
                score = story["_validation_confidence"]
                assert 0 <= score <= 100

            scores = {s["id"]: s["_validation_confidence"] for s in updated["userStories"]}
            assert scores["US-T01"] > scores["US-T02"], f"Simple story should score higher than complex: {scores}"
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_low_confidence_stories_in_summary(self) -> None:
        prd: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-COMPLEX",
                    "title": "Distributed cache with monitoring",
                    "description": (
                        "Implement distributed cache with concurrency, monitoring, "
                        "database migration, authentication, and encryption."
                    ),
                    "dependencies": ["US-A", "US-B", "US-C", "US-D", "US-E", "US-F"],
                }
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(prd, f)
            tmp_path = Path(f.name)

        try:
            summary = score_all_stories(tmp_path)
            assert "US-COMPLEX" in summary["low_confidence"], (
                f"Expected US-COMPLEX in low_confidence, got {summary['low_confidence']}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_missing_prd_raises(self) -> None:
        with pytest.raises((FileNotFoundError, OSError)):
            score_all_stories(Path("/nonexistent/path/prd.json"))
