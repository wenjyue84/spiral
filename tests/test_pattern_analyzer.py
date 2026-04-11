#!/usr/bin/env python3
"""
test_pattern_analyzer.py — Unit tests for retry pattern analysis.

Tests the pattern_analyzer module for clustering stories by retry count
and extracting common traits.

US-785: Phase L Retry Pattern Analysis
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lib.pattern_analyzer import (
    aggregate_traits,
    analyze_patterns,
    cluster_stories_by_retry,
    extract_file_patterns,
    extract_traits,
    load_prd,
    load_retry_counts,
    save_patterns,
)


@pytest.mark.us_785
class TestLoadPRD:
    """Test loading PRD JSON."""

    def test_load_valid_prd(self) -> None:
        """Test loading a valid prd.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "prd.json"
            prd_data = {
                "userStories": [
                    {"id": "US-1", "title": "Story 1", "passes": True},
                    {"id": "US-2", "title": "Story 2", "passes": False},
                ]
            }
            with open(fpath, "w") as f:
                json.dump(prd_data, f)

            stories = load_prd(str(fpath))
            assert len(stories) == 2
            assert stories[0]["id"] == "US-1"

    def test_load_missing_file(self) -> None:
        """Test loading non-existent file."""
        stories = load_prd("/nonexistent/prd.json")
        assert stories == []

    def test_load_invalid_json(self) -> None:
        """Test loading malformed JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "prd.json"
            with open(fpath, "w") as f:
                f.write("{ invalid json")

            stories = load_prd(str(fpath))
            assert stories == []


@pytest.mark.us_785
class TestLoadRetryCounts:
    """Test loading retry counts."""

    def test_load_retry_counts(self) -> None:
        """Test loading valid retry-counts.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "retry-counts.json"
            retry_data = {"US-1": 0, "US-2": 3, "US-3": 5}
            with open(fpath, "w") as f:
                json.dump(retry_data, f)

            counts = load_retry_counts(str(fpath))
            assert counts["US-1"] == 0
            assert counts["US-2"] == 3
            assert counts["US-3"] == 5

    def test_load_missing_retry_counts(self) -> None:
        """Test loading non-existent retry counts."""
        counts = load_retry_counts("/nonexistent/retry-counts.json")
        assert counts == {}


@pytest.mark.us_785
class TestExtractTraits:
    """Test trait extraction from stories."""

    def test_extract_basic_traits(self) -> None:
        """Test extracting traits from a story."""
        story = {
            "id": "US-1",
            "title": "Test Story",
            "description": "This is a test description with some content",
            "acceptanceCriteria": ["AC 1", "AC 2", "AC 3"],
            "tags": ["feature", "core"],
            "filesTouch": ["lib/foo.py", "tests/test_foo.py"],
        }

        traits = extract_traits(story)
        assert traits["ac_count"] == 3
        assert traits["description_length"] == len("This is a test description with some content")
        assert set(traits["tags"]) == {"feature", "core"}
        assert set(traits["file_patterns"]) == {"lib", "tests"}

    def test_extract_traits_missing_fields(self) -> None:
        """Test trait extraction with missing optional fields."""
        story = {"id": "US-1", "title": "Minimal Story"}

        traits = extract_traits(story)
        assert traits["ac_count"] == 0
        assert traits["description_length"] == 0
        assert traits["tags"] == []
        assert traits["file_patterns"] == []

    def test_extract_traits_null_fields(self) -> None:
        """Test trait extraction with null values."""
        story = {
            "id": "US-1",
            "title": "Story with nulls",
            "description": None,
            "tags": None,
            "filesTouch": None,
            "acceptanceCriteria": None,
        }

        traits = extract_traits(story)
        assert traits["ac_count"] == 0
        assert traits["description_length"] == 0
        assert traits["tags"] == []
        assert traits["file_patterns"] == []


@pytest.mark.us_785
class TestExtractFilePatterns:
    """Test file pattern extraction."""

    def test_extract_from_filetouches(self) -> None:
        """Test extracting patterns from filesTouch."""
        story = {
            "filesTouch": [
                "lib/foo.py",
                "lib/bar.py",
                "tests/test_foo.py",
                "cli/main.py",
            ]
        }

        patterns = extract_file_patterns(story)
        assert set(patterns) == {"lib", "tests", "cli"}
        assert patterns == sorted(patterns)  # Verify sorted

    def test_extract_from_description(self) -> None:
        """Test extracting patterns from description text."""
        story = {"description": "Modify lib/foo.py and tests/bar.py to fix the issue"}

        patterns = extract_file_patterns(story)
        assert set(patterns) == {"lib", "tests"}

    def test_extract_combined(self) -> None:
        """Test extracting from both filesTouch and description."""
        story = {
            "filesTouch": ["lib/core.py"],
            "description": "Update lib/util.py and tests/integration.py",
        }

        patterns = extract_file_patterns(story)
        assert set(patterns) == {"lib", "tests"}


@pytest.mark.us_785
class TestClusterStoriesByRetry:
    """Test clustering stories by retry count."""

    def test_cluster_stories(self) -> None:
        """Test clustering stories into retry groups."""
        stories = [
            {"id": "US-1", "title": "Story 1", "passes": True},
            {"id": "US-2", "title": "Story 2", "passes": True},
            {"id": "US-3", "title": "Story 3", "passes": True},
            {"id": "US-4", "title": "Story 4", "passes": True},
            {"id": "US-5", "title": "Story 5", "passes": False},  # incomplete
        ]
        retry_counts = {
            "US-1": 0,  # 0 retries
            "US-2": 1,  # 1 retry
            "US-3": 2,  # 2 retries
            "US-4": 4,  # 3+ retries
            # US-5 not in retry_counts (incomplete)
        }

        clusters = cluster_stories_by_retry(stories, retry_counts)
        assert len(clusters["0"]) == 1
        assert clusters["0"][0]["id"] == "US-1"
        assert len(clusters["1"]) == 1
        assert clusters["1"][0]["id"] == "US-2"
        assert len(clusters["2"]) == 1
        assert clusters["2"][0]["id"] == "US-3"
        assert len(clusters["3+"]) == 1
        assert clusters["3+"][0]["id"] == "US-4"

    def test_cluster_incomplete_stories_excluded(self) -> None:
        """Test that incomplete stories are excluded."""
        stories = [
            {"id": "US-1", "title": "Complete", "passes": True},
            {"id": "US-2", "title": "Incomplete", "passes": False},
        ]
        retry_counts = {"US-1": 0, "US-2": 2}

        clusters = cluster_stories_by_retry(stories, retry_counts)
        total = sum(len(c) for c in clusters.values())
        assert total == 1


@pytest.mark.us_785
class TestAggregateTraits:
    """Test trait aggregation across story groups."""

    def test_aggregate_empty_group(self) -> None:
        """Test aggregating an empty story group."""
        result = aggregate_traits([])
        assert result["count"] == 0
        assert result["avg_ac_count"] == 0.0
        assert result["avg_description_length"] == 0.0
        assert result["common_tags"] == []
        assert result["common_file_patterns"] == []

    def test_aggregate_single_story(self) -> None:
        """Test aggregating a single story."""
        stories = [
            {
                "id": "US-1",
                "title": "Story 1",
                "description": "A test story",
                "acceptanceCriteria": ["AC1", "AC2"],
                "tags": ["feature"],
                "filesTouch": ["lib/foo.py"],
            }
        ]

        result = aggregate_traits(stories)
        assert result["count"] == 1
        assert result["avg_ac_count"] == 2.0
        assert result["avg_description_length"] == 12.0
        assert "feature" in result["common_tags"]

    def test_aggregate_common_tags(self) -> None:
        """Test that common tags (>50%) are identified."""
        stories = [
            {
                "id": "US-1",
                "description": "Story 1",
                "acceptanceCriteria": [],
                "tags": ["feature", "core"],
                "filesTouch": None,
            },
            {
                "id": "US-2",
                "description": "Story 2",
                "acceptanceCriteria": [],
                "tags": ["feature", "bug"],
                "filesTouch": None,
            },
            {
                "id": "US-3",
                "description": "Story 3",
                "acceptanceCriteria": [],
                "tags": ["feature"],
                "filesTouch": None,
            },
        ]

        result = aggregate_traits(stories)
        # "feature" appears in all 3 (100% > 50%)
        assert "feature" in result["common_tags"]
        # "core" and "bug" appear in 1/3 each (33% < 50%)
        assert "core" not in result["common_tags"]
        assert "bug" not in result["common_tags"]


@pytest.mark.us_785
class TestAnalyzePatterns:
    """Test full pattern analysis workflow."""

    def test_analyze_patterns_happy_path(self) -> None:
        """Test analyzing patterns from mixed retry stories."""
        # Create temp prd.json
        prd_data = {
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Easy Story",
                    "description": "Quick fix in lib/",
                    "acceptanceCriteria": ["AC1"],
                    "tags": ["easy"],
                    "filesTouch": ["lib/core.py"],
                    "passes": True,
                },
                {
                    "id": "US-2",
                    "title": "Hard Story",
                    "description": "Complex refactor touching lib/ and tests/",
                    "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
                    "tags": ["hard", "refactor"],
                    "filesTouch": ["lib/foo.py", "tests/test_foo.py"],
                    "passes": True,
                },
            ]
        }

        retry_data = {"US-1": 0, "US-2": 3}

        with tempfile.TemporaryDirectory() as tmpdir:
            prd_file = Path(tmpdir) / "prd.json"
            retry_file = Path(tmpdir) / "retry-counts.json"

            with open(prd_file, "w") as f:
                json.dump(prd_data, f)
            with open(retry_file, "w") as f:
                json.dump(retry_data, f)

            patterns = analyze_patterns(str(prd_file), str(retry_file), iteration=1)

            assert patterns["iteration"] == 1
            assert "timestamp" in patterns
            assert "summary" in patterns
            assert "insights" in patterns

            # Check summary clusters
            summary = patterns["summary"]
            assert summary["0_retries"]["count"] == 1
            assert summary["3plus_retries"]["count"] == 1

    def test_analyze_no_stories(self) -> None:
        """Test analyzing when no stories exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prd_file = Path(tmpdir) / "prd.json"
            retry_file = Path(tmpdir) / "retry-counts.json"

            prd_data: dict[str, list[dict[str, Any]]] = {"userStories": []}
            retry_data: dict[str, int] = {}

            with open(prd_file, "w") as f:
                json.dump(prd_data, f)
            with open(retry_file, "w") as f:
                json.dump(retry_data, f)

            patterns = analyze_patterns(str(prd_file), str(retry_file))
            summary = patterns["summary"]
            assert all(summary[k]["count"] == 0 for k in summary.keys())


class TestSavePatterns:
    """Test saving patterns to file."""

    def test_save_patterns_creates_dir(self) -> None:
        """Test that save_patterns creates parent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "subdir" / "patterns.json"
            patterns = {"iteration": 1, "summary": {}}

            save_patterns(patterns, str(output_path))

            assert output_path.exists()
            with open(output_path, "r") as f:
                loaded = json.load(f)
                assert loaded["iteration"] == 1

    def test_save_patterns_overwrites(self) -> None:
        """Test that save_patterns overwrites existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "patterns.json"

            patterns1 = {"iteration": 1, "data": "first"}
            save_patterns(patterns1, str(output_path))

            patterns2 = {"iteration": 2, "data": "second"}
            save_patterns(patterns2, str(output_path))

            with open(output_path, "r") as f:
                loaded = json.load(f)
                assert loaded["iteration"] == 2
                assert loaded["data"] == "second"


@pytest.mark.us_785
class TestPatternMemoryIntegration:
    """Test integration: pattern analysis with episodic memory storage."""

    def test_patterns_match_episodic_memory_structure(self) -> None:
        """Verify analyzed patterns can be stored in episodic memory format."""
        from lib.episodic_memory import EpisodicMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup: Create PRD with stories of varying retry counts
            prd_data: dict[str, list[dict[str, Any]]] = {
                "userStories": [
                    {
                        "id": "US-easy-1",
                        "title": "Easy: Single AC",
                        "description": "Simple UI text update in lib/",
                        "acceptanceCriteria": ["Change text"],
                        "tags": ["ui"],
                        "filesTouch": ["lib/ui.py"],
                        "passes": True,
                    },
                    {
                        "id": "US-easy-2",
                        "title": "Easy: Two ACs",
                        "description": "Quick feature flag update",
                        "acceptanceCriteria": ["Add flag", "Use flag"],
                        "tags": ["feature"],
                        "filesTouch": ["lib/flags.py"],
                        "passes": True,
                    },
                    {
                        "id": "US-hard-1",
                        "title": "Hard: Complex Refactor",
                        "description": "Database migration with multiple tests and lib updates",
                        "acceptanceCriteria": ["Create migration", "Run tests", "Verify data", "Update lib"],
                        "tags": ["database", "migration"],
                        "filesTouch": ["lib/db.py", "tests/test_db.py", "lib/models.py"],
                        "passes": True,
                    },
                ]
            }

            retry_data: dict[str, int] = {
                "US-easy-1": 0,
                "US-easy-2": 1,
                "US-hard-1": 5,
            }

            prd_path = Path(tmpdir) / "prd.json"
            retry_path = Path(tmpdir) / "retry-counts.json"
            mem_path = Path(tmpdir) / "episodic_memory.jsonl"

            with open(prd_path, "w") as f:
                json.dump(prd_data, f)
            with open(retry_path, "w") as f:
                json.dump(retry_data, f)

            # Execute: Analyze patterns
            patterns = analyze_patterns(str(prd_path), str(retry_path), iteration=1)

            # Verify pattern structure can be stored in episodic memory
            memory = EpisodicMemory(str(mem_path))

            # Store the pattern analysis result as an episodic memory record
            pattern_record = {
                "title": "Retry Pattern Analysis",
                "approach": "Clustered stories by retry count and extracted common traits",
                "outcome": "patterns_extracted",
                "insight": patterns.get("insights", {}),
                "summary": patterns.get("summary", {}),
            }
            memory.write("US-785-pattern-analysis", pattern_record)

            # Verify the record was stored and can be retrieved
            assert mem_path.exists(), "Episodic memory file was not created"

            # Read back and verify structure
            stored_records = memory._load_all_records()
            assert len(stored_records) == 1
            stored = stored_records[0]

            assert stored["story_id"] == "US-785-pattern-analysis"
            assert "timestamp" in stored
            assert stored["outcome"] == "patterns_extracted"
            assert "insight" in stored
            assert "summary" in stored

            # Verify pattern insights distinguish easy from hard stories
            insights = patterns["insights"]
            assert insights.get("easy_count", 0) >= 2
            assert insights.get("hard_count", 0) >= 1
            assert insights.get("easy_avg_ac_count", 0) < insights.get("hard_avg_ac_count", 0)

    def test_retry_patterns_detectdifference_between_easy_and_hard(self) -> None:
        """Regression test: ensure pattern analysis reliably detects easy vs hard stories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test data where easy stories have fewer ACs and hard stories have more
            prd_data: dict[str, list[dict[str, Any]]] = {
                "userStories": [
                    {
                        "id": f"US-easy-{i}",
                        "title": f"Easy Story {i}",
                        "description": "Simple fix",
                        "acceptanceCriteria": ["AC1"],
                        "tags": [],
                        "filesTouch": ["lib/x.py"],
                        "passes": True,
                    }
                    for i in range(3)
                ]
                + [
                    {
                        "id": f"US-hard-{i}",
                        "title": f"Hard Story {i}",
                        "description": "Complex refactor with many changes",
                        "acceptanceCriteria": [f"AC{j}" for j in range(1, 6)],
                        "tags": [],
                        "filesTouch": ["lib/a.py", "lib/b.py", "tests/test_a.py", "tests/test_b.py"],
                        "passes": True,
                    }
                    for i in range(3)
                ]
            }

            retry_data: dict[str, int] = {f"US-easy-{i}": i for i in range(3)} | {
                f"US-hard-{i}": 3 + i for i in range(3)
            }

            prd_path = Path(tmpdir) / "prd.json"
            retry_path = Path(tmpdir) / "retry-counts.json"

            with open(prd_path, "w") as f:
                json.dump(prd_data, f)
            with open(retry_path, "w") as f:
                json.dump(retry_data, f)

            patterns = analyze_patterns(str(prd_path), str(retry_path))

            # AC: Pattern analysis must distinguish easy (0-1 retries) from hard (3+ retries)
            easy_0 = patterns["summary"]["0_retries"]
            easy_1 = patterns["summary"]["1_retry"]
            hard_3plus = patterns["summary"]["3plus_retries"]

            assert easy_0["count"] == 1, "Should have exactly 1 story with 0 retries"
            assert easy_1["count"] == 1, "Should have exactly 1 story with 1 retry"
            assert hard_3plus["count"] == 3, "Should have exactly 3 stories with 3+ retries"

            # Key insight: average AC count should show hard stories are more complex
            insights = patterns["insights"]
            assert insights["easy_avg_ac_count"] < insights["hard_avg_ac_count"], (
                "Hard stories must have higher avg AC count than easy stories"
            )
