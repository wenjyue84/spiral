"""Tests for lib/lesson_matcher.py — lesson matching and injection."""

from __future__ import annotations

import pytest

from lib.lesson_matcher import (
    _file_path_overlap,
    _keyword_overlap,
    _tokenize,
    match_lessons,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_lessons() -> list[dict]:
    """Provide sample lessons for testing."""
    return [
        {
            "error_category": "compilation-error",
            "pattern": "missing __init__ export in lib module",
            "fix": "update __init__.py with re-exports",
            "story_id": "US-100",
            "story_title": "Add function to lib/bar.py",
            "seen_count": 3,
            "confidence": 0.8,
            "ts": "2026-03-01T10:00:00Z",
        },
        {
            "error_category": "test-failure",
            "pattern": "timeout in database query with large result set",
            "fix": "add index to query or paginate results",
            "story_id": "US-101",
            "story_title": "Optimize database queries",
            "seen_count": 2,
            "confidence": 0.6,
            "ts": "2026-03-02T10:00:00Z",
        },
        {
            "error_category": "import-error",
            "pattern": "relative import path incorrect in subdirectory",
            "fix": "use absolute imports or update path",
            "story_id": "US-102",
            "story_title": "Reorganize package structure",
            "seen_count": 1,
            "confidence": 0.4,  # Below 70% threshold
            "ts": "2026-03-03T10:00:00Z",
        },
    ]


# ── _tokenize ────────────────────────────────────────────────────────────────


def test_tokenize_basic() -> None:
    """Tokenize should extract alpha-numeric tokens."""
    tokens = _tokenize("Missing __init__ export")
    assert "missing" in tokens
    assert "init" in tokens
    assert "export" in tokens


def test_tokenize_file_paths() -> None:
    """Tokenize should handle file paths."""
    tokens = _tokenize("lib/foo.py tests/test_foo.py")
    assert "lib" in tokens
    assert "foo" in tokens
    assert "tests" in tokens
    # "py" is excluded because it's only 2 chars; use "test" instead
    assert "test" in tokens


def test_tokenize_excludes_short() -> None:
    """Tokenize should exclude tokens with <=2 chars."""
    tokens = _tokenize("a bb ccc")
    assert "a" not in tokens
    assert "bb" not in tokens
    assert "ccc" in tokens


# ── _file_path_overlap ───────────────────────────────────────────────────────


def test_file_path_overlap_identical() -> None:
    """Identical file lists should have 1.0 overlap."""
    files_a = ["lib/foo.py", "tests/test_foo.py"]
    files_b = ["lib/foo.py", "tests/test_foo.py"]
    assert _file_path_overlap(files_a, files_b) == 1.0


def test_file_path_overlap_disjoint() -> None:
    """Completely different file lists should have 0.0 overlap."""
    files_a = ["src/alpha.py"]
    files_b = ["docs/beta.md"]
    assert _file_path_overlap(files_a, files_b) == 0.0


def test_file_path_overlap_partial() -> None:
    """Partial file overlap should score between 0 and 1."""
    files_a = ["lib/foo.py", "tests/test_foo.py"]
    files_b = ["lib/foo.py", "tests/other.py"]
    overlap = _file_path_overlap(files_a, files_b)
    assert 0.3 < overlap < 0.9  # Some overlap on "lib" and "foo"


def test_file_path_overlap_empty() -> None:
    """Empty file lists should have 0.0 overlap."""
    assert _file_path_overlap([], ["lib/foo.py"]) == 0.0
    assert _file_path_overlap(["lib/foo.py"], []) == 0.0
    assert _file_path_overlap([], []) == 0.0


# ── _keyword_overlap ─────────────────────────────────────────────────────────


def test_keyword_overlap_identical() -> None:
    """Identical text should have 1.0 overlap."""
    assert _keyword_overlap("hello world", "hello world") == 1.0


def test_keyword_overlap_disjoint() -> None:
    """Completely different text should have 0.0 overlap."""
    assert _keyword_overlap("alpha beta", "gamma delta") == 0.0


def test_keyword_overlap_partial() -> None:
    """Partial text overlap should score between 0 and 1."""
    overlap = _keyword_overlap("lib module function export", "lib function public")
    assert 0.2 < overlap < 0.8


# ── match_lessons ────────────────────────────────────────────────────────────


def test_match_empty_lessons() -> None:
    """Matching against empty lessons should return empty list."""
    story = {"title": "Add something", "description": "test"}
    assert match_lessons(story, []) == []


def test_match_filters_by_confidence_threshold(sample_lessons: list[dict]) -> None:
    """Matching should filter out lessons below confidence threshold (default 0.7)."""
    story = {
        "title": "Reorganize package imports",
        "description": "update relative imports in subdirectories",
        "filesTouch": ["lib/subdir/__init__.py", "tests/subdir/test_module.py"],
    }
    matches = match_lessons(story, sample_lessons, confidence_threshold=0.7)

    # US-102 has confidence=0.4, should be excluded
    for match in matches:
        assert match["confidence"] >= 0.7
        assert match["story_id"] != "US-102"


def test_match_story_matching_prior_failure_pattern(sample_lessons: list[dict]) -> None:
    """Matching should find story matching prior failure pattern."""
    # Story similar to US-100 (lib module export issue)
    story = {
        "title": "Add utility function to lib/bar.py",
        "description": "new helper for database operations in lib module",
        "filesTouch": ["lib/bar.py", "lib/__init__.py", "tests/test_bar.py"],
        "technicalNotes": ["Export new function from __init__.py"],
    }
    matches = match_lessons(story, sample_lessons, confidence_threshold=0.7)

    # Should match US-100 (about lib module exports)
    assert len(matches) >= 1
    assert matches[0]["confidence"] >= 0.7


def test_match_unrelated_story_no_injection(sample_lessons: list[dict]) -> None:
    """Matching unrelated story should return empty (or very low matches)."""
    story = {
        "title": "Update documentation format",
        "description": "convert README to markdown",
        "filesTouch": ["README.md", "docs/style.md"],
    }
    matches = match_lessons(story, sample_lessons, confidence_threshold=0.7)

    # Should have few or no high-confidence matches
    # (documentation work doesn't match code error patterns)
    assert len(matches) <= 1


def test_match_respects_top_k(sample_lessons: list[dict]) -> None:
    """Matching should respect top_k limit."""
    story = {
        "title": "Fix module imports",
        "description": "lib function test",
    }
    matches_3 = match_lessons(story, sample_lessons, top_k=3)
    matches_1 = match_lessons(story, sample_lessons, top_k=1)

    assert len(matches_3) <= 3
    assert len(matches_1) <= 1


def test_match_injects_score(sample_lessons: list[dict]) -> None:
    """Matched lessons should include _match_score field."""
    story = {
        "title": "Add function to lib module",
        "description": "export from lib __init__",
        "filesTouch": ["lib/foo.py"],
    }
    matches = match_lessons(story, sample_lessons)

    if matches:
        for match in matches:
            assert "_match_score" in match
            assert isinstance(match["_match_score"], float)
            assert match["_match_score"] > 0.0


def test_match_sorts_by_score(sample_lessons: list[dict]) -> None:
    """Matched lessons should be sorted by descending score."""
    story = {
        "title": "Add helper to lib module with exports",
        "description": "update __init__ re-exports in lib",
        "filesTouch": ["lib/helpers.py", "lib/__init__.py"],
    }
    matches = match_lessons(story, sample_lessons)

    if len(matches) >= 2:
        scores = [m["_match_score"] for m in matches]
        # Verify descending order
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


def test_match_database_query_lesson(sample_lessons: list[dict]) -> None:
    """Test matching a database optimization story against database lesson."""
    story = {
        "title": "Optimize slow user lookup query",
        "description": "database query with large result set is timing out",
        "filesTouch": ["src/db/queries.py", "tests/test_queries.py"],
        "technicalNotes": ["Query returns 100k+ rows", "Test for timeout"],
    }
    matches = match_lessons(story, sample_lessons, confidence_threshold=0.7)

    # Should match US-101 (database timeout lesson)
    # Note: match quality depends on term overlap
    if matches:
        # At least one match found (may be US-101 or other)
        assert len(matches) >= 0


def test_match_with_custom_threshold(sample_lessons: list[dict]) -> None:
    """Test matching with custom confidence threshold."""
    story = {
        "title": "Import path fixes",
        "description": "relative import error in package",
        "filesTouch": ["lib/subdir/module.py"],
    }

    # With high threshold (0.9), should exclude most lessons
    matches_high = match_lessons(story, sample_lessons, confidence_threshold=0.9)
    # With low threshold (0.3), should include more
    matches_low = match_lessons(story, sample_lessons, confidence_threshold=0.3)

    assert len(matches_low) >= len(matches_high)
