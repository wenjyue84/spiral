"""tests/test_rejected_pattern_cache.py — Tests for rejected pattern caching (US-771)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from lib.rejected_pattern_cache import (
    extract_story_features,
    filter_candidates_by_rejected_patterns,
    fingerprint_story,
    jaccard_similarity,
    load_rejected_patterns,
    record_rejected_story,
    save_rejected_patterns,
    should_skip_candidate,
    tokenize,
)


class TestTokenize:
    """Test text tokenization."""

    def test_tokenize_simple(self) -> None:
        """Tokenize simple text."""
        result = tokenize("hello world")
        assert result == {"hello", "world"}

    def test_tokenize_lowercase(self) -> None:
        """Tokenize is case-insensitive."""
        result = tokenize("Hello WORLD")
        assert result == {"hello", "world"}

    def test_tokenize_punctuation(self) -> None:
        """Tokenize removes punctuation."""
        result = tokenize("hello, world!")
        assert result == {"hello", "world"}

    def test_tokenize_empty(self) -> None:
        """Tokenize empty string."""
        result = tokenize("")
        assert result == set()


class TestJaccardSimilarity:
    """Test Jaccard similarity calculation."""

    def test_identical_sets(self) -> None:
        """Identical sets have 1.0 similarity."""
        set1 = {"a", "b", "c"}
        set2 = {"a", "b", "c"}
        assert jaccard_similarity(set1, set2) == 1.0

    def test_no_overlap(self) -> None:
        """Disjoint sets have 0.0 similarity."""
        set1 = {"a", "b"}
        set2 = {"c", "d"}
        assert jaccard_similarity(set1, set2) == 0.0

    def test_partial_overlap(self) -> None:
        """Partial overlap returns correct Jaccard score."""
        set1 = {"a", "b", "c"}
        set2 = {"a", "b", "d"}
        # intersection = {a, b} (2), union = {a, b, c, d} (4), similarity = 2/4 = 0.5
        assert jaccard_similarity(set1, set2) == 0.5

    def test_both_empty(self) -> None:
        """Both empty sets have 1.0 similarity."""
        assert jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self) -> None:
        """One empty set has 0.0 similarity."""
        assert jaccard_similarity({"a"}, set()) == 0.0
        assert jaccard_similarity(set(), {"a"}) == 0.0


class TestExtractStoryFeatures:
    """Test feature extraction from stories."""

    def test_extract_title_only(self) -> None:
        """Extract features from title."""
        story = {"title": "Implement foo bar"}
        features = extract_story_features(story)
        assert "implement" in features
        assert "foo" in features
        assert "bar" in features

    def test_extract_description(self) -> None:
        """Extract features from description."""
        story = {"description": "Add new feature"}
        features = extract_story_features(story)
        assert "add" in features
        assert "new" in features
        assert "feature" in features

    def test_extract_tags(self) -> None:
        """Extract tags as-is."""
        story = {"tags": ["bug-fix", "urgent"]}
        features = extract_story_features(story)
        assert "bug-fix" in features
        assert "urgent" in features

    def test_extract_all_fields(self) -> None:
        """Extract from title, description, and tags."""
        story = {
            "title": "Implement feature",
            "description": "Add support for X",
            "tags": ["core"],
        }
        features = extract_story_features(story)
        assert "implement" in features
        assert "feature" in features
        assert "support" in features
        assert "core" in features

    def test_extract_empty_story(self) -> None:
        """Extract from empty story."""
        story = {}
        features = extract_story_features(story)
        assert features == set()


class TestFingerprintStory:
    """Test story fingerprinting."""

    def test_fingerprint_basic(self) -> None:
        """Create fingerprint from story."""
        story = {
            "id": "US-100",
            "title": "Test story",
            "description": "A test",
            "tags": ["test"],
        }
        fp = fingerprint_story(story, "constitution violation", 1)
        assert fp.story_id == "US-100"
        assert fp.title == "Test story"
        assert fp.rejection_reason == "constitution violation"
        assert fp.rejection_iteration == 1

    def test_fingerprint_defaults(self) -> None:
        """Fingerprint with defaults for missing fields."""
        story = {"id": "US-100"}
        fp = fingerprint_story(story)
        assert fp.story_id == "US-100"
        assert fp.title == ""
        assert fp.rejection_reason == ""
        assert fp.rejection_iteration == 0


class TestShouldSkipCandidate:
    """Test candidate filtering by similarity."""

    def test_skip_exact_match(self) -> None:
        """Skip candidate matching rejected pattern exactly."""
        from lib.rejected_pattern_cache import StoryFingerprint

        candidate = {
            "title": "Fix bug X",
            "description": "This fixes issue X",
            "tags": ["bug"],
        }
        rejected = [
            StoryFingerprint(
                story_id="US-50",
                title="Fix bug X",
                description="This fixes issue X",
                tags=["bug"],
                rejection_reason="out of scope",
                rejection_iteration=1,
            )
        ]
        should_skip, reason = should_skip_candidate(candidate, rejected, threshold=0.8)
        assert should_skip is True
        assert "US-50" in reason

    def test_skip_near_duplicate(self) -> None:
        """Skip candidate with >80% similarity - very similar stories."""
        from lib.rejected_pattern_cache import StoryFingerprint

        candidate = {
            "title": "Implement authentication feature",
            "description": "Add authentication feature to application",
            "tags": ["auth", "feature"],
        }
        rejected = [
            StoryFingerprint(
                story_id="US-50",
                title="Implement authentication feature",
                description="Add authentication feature to application",
                tags=["auth", "feature"],
                rejection_reason="out of scope",
                rejection_iteration=1,
            )
        ]
        should_skip, reason = should_skip_candidate(candidate, rejected, threshold=0.80)
        # Should skip due to exact match (100% similarity)
        assert should_skip is True

    def test_keep_different_story(self) -> None:
        """Keep candidate with low similarity."""
        from lib.rejected_pattern_cache import StoryFingerprint

        candidate = {
            "title": "Add dashboard",
            "description": "Build a new dashboard",
            "tags": ["feature"],
        }
        rejected = [
            StoryFingerprint(
                story_id="US-50",
                title="Fix bug X",
                description="This fixes issue X",
                tags=["bug"],
                rejection_reason="out of scope",
                rejection_iteration=1,
            )
        ]
        should_skip, reason = should_skip_candidate(candidate, rejected, threshold=0.8)
        assert should_skip is False
        assert reason == ""

    def test_empty_candidate(self) -> None:
        """Empty candidate has no features."""
        from lib.rejected_pattern_cache import StoryFingerprint

        candidate = {}
        rejected = [
            StoryFingerprint(
                story_id="US-50",
                title="Fix bug",
                description="Fix",
                tags=[],
                rejection_reason="",
                rejection_iteration=1,
            )
        ]
        should_skip, reason = should_skip_candidate(candidate, rejected)
        assert should_skip is False


class TestSaveLoadPatterns:
    """Test saving and loading rejected patterns."""

    def test_save_and_load(self) -> None:
        """Save patterns and load them back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            patterns = [
                fingerprint_story(
                    {"id": "US-1", "title": "Story 1", "description": "Desc 1"},
                    "reason 1",
                    1,
                ),
                fingerprint_story(
                    {"id": "US-2", "title": "Story 2", "description": "Desc 2"},
                    "reason 2",
                    2,
                ),
            ]
            save_rejected_patterns(patterns, cache_path)
            loaded = load_rejected_patterns(cache_path)
            assert len(loaded) == 2
            assert loaded[0].story_id == "US-1"
            assert loaded[1].story_id == "US-2"

    def test_prune_to_max_entries(self) -> None:
        """Prune patterns to max_entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            patterns = [
                fingerprint_story(
                    {"id": f"US-{i}", "title": f"Story {i}"},
                    "reason",
                    i,
                )
                for i in range(10)
            ]
            save_rejected_patterns(patterns, cache_path, max_entries=5)
            loaded = load_rejected_patterns(cache_path)
            assert len(loaded) == 5
            # Should keep last 5
            assert loaded[0].story_id == "US-5"
            assert loaded[4].story_id == "US-9"

    def test_load_nonexistent_file(self) -> None:
        """Load from nonexistent file returns empty list."""
        cache_path = Path("/nonexistent/path/cache.json")
        patterns = load_rejected_patterns(cache_path)
        assert patterns == []

    def test_load_corrupt_json(self) -> None:
        """Load from corrupt JSON file returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cache.json"
            cache_path.write_text("not valid json")
            patterns = load_rejected_patterns(cache_path)
            assert patterns == []


class TestRecordRejectedStory:
    """Test recording rejected stories."""

    def test_record_and_retrieve(self) -> None:
        """Record a rejected story and retrieve it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".spiral" / "rejected_patterns.json"
            story = {
                "id": "US-100",
                "title": "Test story",
                "description": "A test",
                "tags": ["test"],
            }
            record_rejected_story(story, "constitution violation", cache_path, iteration=1)
            patterns = load_rejected_patterns(cache_path)
            assert len(patterns) == 1
            assert patterns[0].story_id == "US-100"
            assert patterns[0].rejection_reason == "constitution violation"

    def test_multiple_records(self) -> None:
        """Record multiple rejected stories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".spiral" / "rejected_patterns.json"
            for i in range(3):
                story = {"id": f"US-{i}", "title": f"Story {i}"}
                record_rejected_story(story, f"reason {i}", cache_path, iteration=i)
            patterns = load_rejected_patterns(cache_path)
            assert len(patterns) == 3


class TestFilterCandidates:
    """Test filtering candidates by rejected patterns."""

    def test_filter_removes_matches(self) -> None:
        """Filter removes candidates matching rejected patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".spiral" / "rejected_patterns.json"
            # Record a rejected story
            rejected_story = {
                "id": "US-OLD",
                "title": "Old story",
                "description": "Old description",
            }
            record_rejected_story(rejected_story, "out of scope", cache_path)

            # Try to filter candidates
            candidates = [
                {
                    "id": "US-NEW-1",
                    "title": "New story",
                    "description": "Different",
                },
                {
                    "id": "US-NEW-2",
                    "title": "Old story",  # Matches rejected
                    "description": "Old description",
                },
            ]
            kept, skipped = filter_candidates_by_rejected_patterns(candidates, cache_path, similarity_threshold=0.8)
            assert len(kept) == 1
            assert kept[0]["id"] == "US-NEW-1"
            assert "US-NEW-2" in skipped

    def test_filter_empty_cache(self) -> None:
        """Filter with empty cache returns all candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".spiral" / "rejected_patterns.json"
            candidates = [
                {"id": "US-1", "title": "Story 1"},
                {"id": "US-2", "title": "Story 2"},
            ]
            kept, skipped = filter_candidates_by_rejected_patterns(candidates, cache_path)
            assert len(kept) == 2
            assert len(skipped) == 0

    def test_filter_all_match(self) -> None:
        """Filter removes all candidates if all match rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / ".spiral" / "rejected_patterns.json"
            rejected_story = {
                "id": "US-OLD",
                "title": "Auth feature",
                "description": "Implement auth",
            }
            record_rejected_story(rejected_story, "out of scope", cache_path)

            candidates = [
                {
                    "id": "US-NEW-1",
                    "title": "Authentication feature",
                    "description": "Add auth support",
                },
            ]
            kept, skipped = filter_candidates_by_rejected_patterns(
                candidates,
                cache_path,
                similarity_threshold=0.7,  # Lower threshold
            )
            # Should remove due to high similarity
            assert len(kept) <= 1
