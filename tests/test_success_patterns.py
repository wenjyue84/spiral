"""
Regression tests for US-1225: Success-Pattern Library with Phase L to Phase A Feedback Loop.

Tests verify that:
1. After a story completes with 0 retries, its characteristics are appended to _success_patterns.jsonl
2. The appended JSON line contains the correct keys: file_count, ac_count, keywords
3. Phase A candidate scoring reads this file and returns higher scores for matching patterns
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.meta_harness import (
    append_success_pattern,
    extract_success_pattern,
    load_success_patterns,
    score_candidate_from_patterns,
)


class TestSuccessPatternExtraction:
    """Test extraction of success patterns from passed stories."""

    def test_extract_success_pattern_has_required_keys(self) -> None:
        """AC2: Extraction function returns dict with keys: file_count, ac_count, keywords."""
        story = {
            "id": "US-1",
            "title": "Test Feature",
            "description": "Implement test feature for testing",
            "acceptanceCriteria": ["Criterion 1", "Criterion 2"],
            "filesTouch": ["lib/module.py", "tests/test_module.py"],
        }

        pattern = extract_success_pattern(story)

        assert "file_count" in pattern
        assert "ac_count" in pattern
        assert "keywords" in pattern
        assert "story_id" in pattern

    def test_extract_success_pattern_correct_counts(self) -> None:
        """Extraction correctly counts files and acceptance criteria."""
        story = {
            "id": "US-2",
            "title": "Test",
            "description": "Description",
            "acceptanceCriteria": ["AC1", "AC2", "AC3"],
            "filesTouch": ["file1.py", "file2.py"],
        }

        pattern = extract_success_pattern(story)

        assert pattern["ac_count"] == 3
        assert pattern["file_count"] == 2
        assert pattern["story_id"] == "US-2"

    def test_extract_success_pattern_handles_missing_fields(self) -> None:
        """Extraction handles missing filesTouch or acceptanceCriteria."""
        story = {"id": "US-3", "title": "Minimal", "description": "Minimal story"}

        pattern = extract_success_pattern(story)

        assert pattern["file_count"] == 0
        assert pattern["ac_count"] == 0
        assert isinstance(pattern["keywords"], list)

    def test_extract_success_pattern_extracts_keywords(self) -> None:
        """Extraction extracts keywords from title and description."""
        story = {
            "id": "US-4",
            "title": "Implement Authentication System",
            "description": "Add authentication and authorization for users",
            "acceptanceCriteria": [],
            "filesTouch": [],
        }

        pattern = extract_success_pattern(story)

        # Should extract words like "implement", "authentication", "authorization"
        keywords = pattern["keywords"]
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        # Check that meaningful words are extracted (not stopwords)
        assert "authentication" in keywords or "auth" in keywords


class TestSuccessPatternAppend:
    """Test appending success patterns to _success_patterns.jsonl."""

    def test_append_success_pattern_creates_file(self, tmp_path: Path) -> None:
        """AC1: Appending a pattern creates _success_patterns.jsonl if it doesn't exist."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        pattern = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["test", "feature"],
            "story_id": "US-100",
        }

        append_success_pattern(pattern, patterns_file)

        assert patterns_file.exists()

    def test_append_success_pattern_writes_json_line(self, tmp_path: Path) -> None:
        """AC1: Pattern is appended as a JSON line to the file."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        pattern = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["test", "feature"],
            "story_id": "US-101",
        }

        append_success_pattern(pattern, patterns_file)

        # Read the file and verify JSON line
        content = patterns_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert len(lines) >= 1

        loaded = json.loads(lines[0])
        assert loaded["file_count"] == 2
        assert loaded["ac_count"] == 3
        assert loaded["keywords"] == ["test", "feature"]
        assert loaded["story_id"] == "US-101"

    def test_append_success_pattern_deduplicates(self, tmp_path: Path) -> None:
        """Appending the same story_id twice doesn't create duplicate entries."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        pattern1 = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["test"],
            "story_id": "US-102",
        }
        pattern2 = {
            "file_count": 3,
            "ac_count": 4,
            "keywords": ["test", "other"],
            "story_id": "US-102",  # Same story_id
        }

        append_success_pattern(pattern1, patterns_file)
        result = append_success_pattern(pattern2, patterns_file)

        # Second append should return the existing pattern, not add a new line
        content = patterns_file.read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 1  # Only one line, not two

        # Result should be the first pattern (existing)
        assert result["story_id"] == "US-102"

    def test_append_multiple_patterns(self, tmp_path: Path) -> None:
        """Multiple different patterns are all appended to the file."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        for i in range(3):
            pattern = {
                "file_count": i,
                "ac_count": i + 1,
                "keywords": [f"keyword{i}"],
                "story_id": f"US-{200 + i}",
            }
            append_success_pattern(pattern, patterns_file)

        content = patterns_file.read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 3


class TestSuccessPatternLoading:
    """Test loading success patterns from disk."""

    def test_load_success_patterns_empty_file(self, tmp_path: Path) -> None:
        """Loading from nonexistent file returns empty list."""
        patterns_file = tmp_path / "nonexistent.jsonl"
        result = load_success_patterns(patterns_file)
        assert result == []

    def test_load_success_patterns_from_file(self, tmp_path: Path) -> None:
        """Loading reads all JSON lines from the file."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Write patterns directly
        patterns_file.write_text(
            '{"file_count": 1, "ac_count": 2, "keywords": ["a"], "story_id": "US-1"}\n'
            '{"file_count": 2, "ac_count": 3, "keywords": ["b"], "story_id": "US-2"}\n',
            encoding="utf-8",
        )

        result = load_success_patterns(patterns_file)

        assert len(result) == 2
        assert result[0]["story_id"] == "US-1"
        assert result[1]["story_id"] == "US-2"

    def test_load_success_patterns_skips_blank_lines(self, tmp_path: Path) -> None:
        """Loading handles blank lines gracefully."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        patterns_file.write_text(
            '{"file_count": 1, "ac_count": 2, "keywords": ["a"], "story_id": "US-1"}\n'
            "\n"
            '{"file_count": 2, "ac_count": 3, "keywords": ["b"], "story_id": "US-2"}\n',
            encoding="utf-8",
        )

        result = load_success_patterns(patterns_file)

        assert len(result) == 2  # Blank line is skipped


class TestPhaseAScoringWithPatterns:
    """AC3: Phase A candidate scoring reads success patterns and returns higher scores for matches."""

    def test_score_candidate_no_patterns_returns_zero(self, tmp_path: Path) -> None:
        """Scoring with no patterns returns 0.0."""
        patterns_file = tmp_path / "_success_patterns.jsonl"
        candidate = {"id": "US-999", "title": "Test", "acceptanceCriteria": [], "filesTouch": []}

        score = score_candidate_from_patterns(candidate, patterns_file)

        assert score == 0.0

    def test_score_candidate_matching_pattern_returns_positive_score(self, tmp_path: Path) -> None:
        """Scoring a candidate matching a stored pattern returns score > 0.0."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Store a pattern
        pattern = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["authentication", "user"],
            "story_id": "US-100",
        }
        append_success_pattern(pattern, patterns_file)

        # Create a candidate matching the pattern
        candidate = {
            "id": "US-999",
            "title": "Implement user authentication system",
            "description": "Add authentication and user management",
            "acceptanceCriteria": ["AC1", "AC2", "AC3"],
            "filesTouch": ["lib/auth.py", "tests/test_auth.py"],
        }

        score = score_candidate_from_patterns(candidate, patterns_file)

        assert score > 0.0

    def test_score_candidate_non_matching_pattern_returns_zero(self, tmp_path: Path) -> None:
        """Scoring a candidate NOT matching stored patterns returns 0.0."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Store a pattern with specific characteristics
        pattern = {
            "file_count": 5,  # Requires 5 files
            "ac_count": 10,  # Requires 10 ACs
            "keywords": ["kubernetes", "orchestration"],
            "story_id": "US-100",
        }
        append_success_pattern(pattern, patterns_file)

        # Create a candidate with completely different characteristics
        candidate = {
            "id": "US-999",
            "title": "Simple documentation update",
            "description": "Fix a typo in README",
            "acceptanceCriteria": [],
            "filesTouch": [],
        }

        score = score_candidate_from_patterns(candidate, patterns_file)

        # No match: different file count, AC count, and keywords
        assert score == 0.0

    def test_score_candidate_higher_for_better_match(self, tmp_path: Path) -> None:
        """Candidates with more keyword overlap get higher scores."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Store a pattern
        pattern = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["authentication", "login", "password"],
            "story_id": "US-100",
        }
        append_success_pattern(pattern, patterns_file)

        # Candidate 1: matches all keywords
        candidate1 = {
            "id": "US-1",
            "title": "Add authentication and login with password support",
            "description": "Implement authentication, login, password management",
            "acceptanceCriteria": ["AC1", "AC2", "AC3"],
            "filesTouch": ["lib/auth.py", "tests/test_auth.py"],
        }

        # Candidate 2: matches fewer keywords
        candidate2 = {
            "id": "US-2",
            "title": "Add login button UI",
            "description": "Add a login button to the homepage",
            "acceptanceCriteria": ["AC1", "AC2", "AC3"],
            "filesTouch": ["lib/ui.py", "tests/test_ui.py"],
        }

        score1 = score_candidate_from_patterns(candidate1, patterns_file)
        score2 = score_candidate_from_patterns(candidate2, patterns_file)

        # Candidate 1 (more keyword overlap) should score higher
        assert score1 > score2

    def test_score_candidate_respects_file_and_ac_ranges(self, tmp_path: Path) -> None:
        """Scoring only matches if file count and AC count are within ±1 range."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Store a pattern: 2 files, 3 ACs
        pattern = {
            "file_count": 2,
            "ac_count": 3,
            "keywords": ["test"],
            "story_id": "US-100",
        }
        append_success_pattern(pattern, patterns_file)

        # Candidate with 2 files, 3 ACs: should match
        candidate_match = {
            "id": "US-1",
            "title": "Test feature",
            "acceptanceCriteria": ["AC1", "AC2", "AC3"],
            "filesTouch": ["lib/x.py", "tests/test_x.py"],
        }

        # Candidate with 0 files, 1 AC: should NOT match (too different)
        candidate_no_match = {
            "id": "US-2",
            "title": "Test feature",
            "acceptanceCriteria": ["AC1"],
            "filesTouch": [],
        }

        score_match = score_candidate_from_patterns(candidate_match, patterns_file)
        score_no_match = score_candidate_from_patterns(candidate_no_match, patterns_file)

        assert score_match > 0.0
        assert score_no_match == 0.0


class TestEndToEndSuccessPatternWorkflow:
    """End-to-end test: extract pattern from passed story, then use it to score candidates."""

    def test_e2e_extract_and_score(self, tmp_path: Path) -> None:
        """E2E: Extract pattern from a passed story and use it to score similar candidates."""
        patterns_file = tmp_path / "_success_patterns.jsonl"

        # Simulate a story that passed with 0 retries
        passed_story = {
            "id": "US-100",
            "title": "Implement REST API endpoint",
            "description": "Create a REST API endpoint for user management",
            "acceptanceCriteria": ["GET endpoint works", "POST endpoint works", "DELETE endpoint works"],
            "filesTouch": ["lib/api.py", "tests/test_api.py"],
            "passes": True,
        }

        # Phase L: Extract pattern from the passed story
        pattern = extract_success_pattern(passed_story)
        append_success_pattern(pattern, patterns_file)

        # Verify pattern was stored
        patterns = load_success_patterns(patterns_file)
        assert len(patterns) == 1

        # Phase A: Score a similar candidate
        similar_candidate = {
            "id": "US-999",
            "title": "Implement GraphQL API endpoint",
            "description": "Create a GraphQL API endpoint for product management",
            "acceptanceCriteria": ["Query works", "Mutation works"],
            "filesTouch": ["lib/graphql.py", "tests/test_graphql.py"],
        }

        score = score_candidate_from_patterns(similar_candidate, patterns_file)

        # Score should be > 0 because the candidate is similar to the passed story
        assert score > 0.0

        # Phase A: Score a very different candidate
        different_candidate = {
            "id": "US-1000",
            "title": "Fix typo in README",
            "description": "Fix a typo",
            "acceptanceCriteria": [],
            "filesTouch": ["README.md"],
        }

        score_different = score_candidate_from_patterns(different_candidate, patterns_file)

        # Score should be much lower (likely 0) because it's very different
        assert score_different < score
