"""
Unit tests for lib/similar_story_finder.py

Tests TF-IDF similarity detection for finding analogous past implementations.
"""

from typing import Any

from lib.similar_story_finder import (
    create_searchable_text,
    enrich_with_similar_solutions,
    extract_file_paths,
    find_similar_stories,
    get_passed_stories,
)


class TestCreateSearchableText:
    """Test story text extraction for TF-IDF."""

    def test_title_and_description(self) -> None:
        """Extract title and description."""
        story: dict[str, str] = {"title": "Cache Invalidation", "description": "Fix stale cache issues"}
        text = create_searchable_text(story)
        assert "Cache Invalidation" in text
        assert "Fix stale cache issues" in text

    def test_missing_fields(self) -> None:
        """Handle missing title or description gracefully."""
        story: dict[str, str] = {"title": "Cache", "description": ""}
        text = create_searchable_text(story)
        assert text == "Cache"

    def test_empty_story(self) -> None:
        """Empty story produces empty text."""
        story: dict[str, Any] = {}
        text = create_searchable_text(story)
        assert text == ""


class TestExtractFilePaths:
    """Test file path extraction from stories."""

    def test_from_files_to_touch(self) -> None:
        """Extract files from filesTouch."""
        story = {
            "filesTouch": [
                "lib/cache.py",
                "tests/test_cache.py",
            ],
            "technicalNotes": [],
        }
        files = extract_file_paths(story)
        assert "lib/cache.py" in files
        assert "tests/test_cache.py" in files

    def test_from_technical_notes(self) -> None:
        """Extract files from technicalNotes."""
        story = {
            "filesTouch": [],
            "technicalNotes": [
                "File to edit: lib/cache.py (invalidate function)",
                "File to create: tests/test_new_cache.py",
            ],
        }
        files = extract_file_paths(story)
        assert "lib/cache.py" in files
        assert "tests/test_new_cache.py" in files

    def test_deduplicated_and_sorted(self) -> None:
        """Files are deduplicated and sorted."""
        story = {
            "filesTouch": ["c.py", "a.py", "b.py", "a.py"],
            "technicalNotes": ["File to edit: b.py (func)"],
        }
        files = extract_file_paths(story)
        assert files == ["a.py", "b.py", "c.py"]


class TestFindSimilarStories:
    """Test TF-IDF similarity matching."""

    def test_caching_story_finds_similar_caching_story(self) -> None:
        """A caching story should find another caching story as similar."""
        candidate = {
            "id": "US-001",
            "title": "Implement Cache Invalidation",
            "description": "Add cache invalidation for user sessions",
        }

        passed_stories = [
            {
                "id": "US-900",
                "title": "Cache Management System",
                "description": "Build cache invalidation and eviction policies",
            },
            {
                "id": "US-901",
                "title": "Database Query Optimization",
                "description": "Speed up database queries with indexes",
            },
        ]

        similar = find_similar_stories(candidate, passed_stories, threshold=0.3, top_k=3)

        assert len(similar) > 0
        assert similar[0]["id"] == "US-900"

    def test_threshold_filtering(self) -> None:
        """Similarity threshold filters out dissimilar stories."""
        candidate = {
            "title": "Cache Invalidation",
            "description": "Fix cache issues",
        }

        passed_stories = [
            {
                "id": "US-900",
                "title": "Database optimization",
                "description": "Speed up queries with indexes",
            },
        ]

        # Very high threshold filters out
        similar = find_similar_stories(candidate, passed_stories, threshold=0.99, top_k=3)
        assert len(similar) == 0

        # Low threshold includes
        similar = find_similar_stories(candidate, passed_stories, threshold=0.0, top_k=3)
        assert len(similar) > 0

    def test_top_k_limit(self) -> None:
        """Only top K stories are returned."""
        candidate = {
            "title": "Cache",
            "description": "Cache management",
        }

        passed_stories = [{"id": f"US-{i}", "title": f"Story {i}", "description": "Cache related"} for i in range(10)]

        similar = find_similar_stories(candidate, passed_stories, threshold=0.0, top_k=3)

        assert len(similar) <= 3

    def test_empty_passed_stories(self) -> None:
        """Handles empty passed stories list."""
        candidate = {"title": "Cache", "description": ""}
        similar = find_similar_stories(candidate, [], threshold=0.5, top_k=3)
        assert similar == []

    def test_empty_candidate_text(self) -> None:
        """Handles candidate with no searchable text."""
        candidate = {"title": "", "description": ""}
        passed_stories = [{"id": "US-900", "title": "Test", "description": "Test story"}]
        similar = find_similar_stories(candidate, passed_stories, threshold=0.5, top_k=3)
        assert similar == []


class TestEnrichWithSimilarSolutions:
    """Test enrichment of stories with similar solution references."""

    def test_enrichment_adds_similar_solutions(self) -> None:
        """Enrichment adds _enrichment.similar_solutions field."""
        validated = [
            {
                "id": "US-001",
                "title": "Cache System Cache Implementation",
                "description": "Implement caching with cache invalidation",
                "filesTouch": ["lib/cache.py"],
            }
        ]

        passed = [
            {
                "id": "US-900",
                "title": "Cache Invalidation Cache System",
                "description": "Fix cache invalidation and cache management",
                "filesTouch": ["lib/cache_invalidate.py"],
                "passes": True,
            }
        ]

        enriched = enrich_with_similar_solutions(validated, passed, similarity_threshold=0.1, top_k=3)

        assert len(enriched) == 1
        assert "_enrichment" in enriched[0]
        assert "similar_solutions" in enriched[0]["_enrichment"]
        assert len(enriched[0]["_enrichment"]["similar_solutions"]) > 0

    def test_enrichment_includes_file_paths(self) -> None:
        """Similar solutions include file paths from passed stories."""
        validated = [
            {
                "id": "US-001",
                "title": "Caching",
                "description": "Cache management",
            }
        ]

        passed = [
            {
                "id": "US-900",
                "title": "Cache System",
                "description": "Cache implementation",
                "filesTouch": ["lib/cache.py", "tests/test_cache.py"],
                "passes": True,
            }
        ]

        enriched = enrich_with_similar_solutions(validated, passed, similarity_threshold=0.2, top_k=1)

        similar = enriched[0]["_enrichment"]["similar_solutions"][0]
        assert "lib/cache.py" in similar["files"]

    def test_no_enrichment_when_no_similar_stories(self) -> None:
        """No enrichment field added if no similar stories found."""
        validated = [
            {
                "id": "US-001",
                "title": "Unrelated Feature",
                "description": "Something completely different",
            }
        ]

        passed = [
            {
                "id": "US-900",
                "title": "Database optimization",
                "description": "Query speed improvements",
                "passes": True,
            }
        ]

        enriched = enrich_with_similar_solutions(validated, passed, similarity_threshold=0.99, top_k=3)

        assert "_enrichment" in enriched[0]
        assert "similar_solutions" not in enriched[0]["_enrichment"]

    def test_preserves_original_story_fields(self) -> None:
        """Enrichment preserves all original story fields."""
        original: dict[str, Any] = {
            "id": "US-001",
            "title": "Test",
            "description": "Test story",
            "priority": "high",
            "acceptanceCriteria": ["Test 1"],
            "technicalNotes": ["Note 1"],
        }

        validated: list[dict[str, Any]] = [original]
        passed: list[dict[str, Any]] = []

        enriched = enrich_with_similar_solutions(validated, passed)

        assert enriched[0]["id"] == original["id"]
        assert enriched[0]["priority"] == original["priority"]
        assert enriched[0]["acceptanceCriteria"] == original["acceptanceCriteria"]


class TestGetPassedStories:
    """Test extraction of passed stories from PRD."""

    def test_extracts_passed_stories(self) -> None:
        """Extract only stories with passes=true."""
        prd: dict[str, list[dict[str, Any]]] = {
            "userStories": [
                {"id": "US-001", "passes": True, "title": "Story 1"},
                {"id": "US-002", "passes": False, "title": "Story 2"},
                {"id": "US-003", "passes": True, "title": "Story 3"},
            ]
        }

        passed = get_passed_stories(prd)

        assert len(passed) == 2
        assert passed[0]["id"] == "US-001"
        assert passed[1]["id"] == "US-003"

    def test_empty_prd(self) -> None:
        """Handle empty PRD."""
        prd: dict[str, list[Any]] = {"userStories": []}
        passed = get_passed_stories(prd)
        assert passed == []

    def test_missing_userStories(self) -> None:
        """Handle PRD missing userStories key."""
        prd: dict[str, Any] = {}
        passed = get_passed_stories(prd)
        assert passed == []
