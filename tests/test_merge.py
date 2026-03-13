"""Property-based tests for merge_stories.py operations."""
import json
import os
import subprocess
import sys
import re
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from conftest import valid_prd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_stories import is_duplicate, overlap_ratio, find_next_id, sort_key, story_to_prd_entry


class TestOverlapRatio:
    """Properties of the overlap ratio function."""

    @given(text=st.text(min_size=1, max_size=100))
    def test_self_overlap_is_one(self, text):
        """A string always has full overlap with itself (if it has alphanum words)."""
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        if words:  # only if there are actual words
            ratio = overlap_ratio(text, text)
            assert ratio == 1.0

    @given(a=st.text(min_size=0, max_size=50), b=st.text(min_size=0, max_size=50))
    def test_overlap_ratio_bounded(self, a, b):
        """Overlap ratio is always between 0.0 and 1.0."""
        ratio = overlap_ratio(a, b)
        assert 0.0 <= ratio <= 1.0

    def test_empty_overlap_is_zero(self):
        assert overlap_ratio("", "hello") == 0.0
        assert overlap_ratio("", "") == 0.0

    def test_no_common_words(self):
        assert overlap_ratio("alpha beta", "gamma delta") == 0.0


class TestIsDuplicate:
    """Properties of the deduplication function."""

    @given(title=st.text(alphabet="abcdefghijklmnop ", min_size=5, max_size=50))
    def test_title_is_duplicate_of_itself(self, title):
        """A title is always a duplicate of itself."""
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        if len(words) >= 2:  # need words for overlap to work
            assert is_duplicate(title, [title])

    @given(
        title=st.text(alphabet="abcdefghijklmnop ", min_size=5, max_size=50),
        existing=st.lists(st.text(alphabet="qrstuvwxyz ", min_size=5, max_size=50), max_size=5)
    )
    def test_non_overlapping_titles_not_duplicate(self, title, existing):
        """Titles with completely different alphabets are never duplicates."""
        # titles from a-p alphabet, existing from q-z alphabet: zero overlap
        assert not is_duplicate(title, existing)


class TestFindNextId:
    """Properties of ID generation."""

    @given(prd=valid_prd(min_stories=1, max_stories=10))
    def test_next_id_is_higher_than_all_existing(self, prd):
        """Next ID number is always greater than any existing ID number."""
        stories = prd["userStories"]
        next_num = find_next_id(stories)
        for s in stories:
            m = re.match(r"US-(\d+)$", s.get("id", ""))
            if m:
                assert next_num > int(m.group(1))

    def test_empty_stories_returns_one(self):
        assert find_next_id([]) == 1


class TestSortKey:
    """Properties of priority sorting."""

    def test_critical_sorts_first(self):
        critical = {"priority": "critical"}
        low = {"priority": "low"}
        assert sort_key(critical) < sort_key(low)

    @given(prd=valid_prd(min_stories=2, max_stories=10))
    def test_sort_is_stable(self, prd):
        """Sorting by priority key is deterministic."""
        stories = prd["userStories"]
        sorted1 = sorted(stories, key=sort_key)
        sorted2 = sorted(stories, key=sort_key)
        assert [s["id"] for s in sorted1] == [s["id"] for s in sorted2]


class TestStoryToPrdEntry:
    """Properties of story conversion."""

    @given(prd=valid_prd(min_stories=1, max_stories=3))
    def test_entry_always_has_required_fields(self, prd):
        """Converted entry always has all required PRD fields."""
        story = prd["userStories"][0]
        entry = story_to_prd_entry(story, "US-999")
        for field in ("id", "title", "priority", "description", "acceptanceCriteria", "dependencies", "passes"):
            assert field in entry, f"Missing field: {field}"

    @given(prd=valid_prd(min_stories=1, max_stories=3))
    def test_entry_passes_is_always_false(self, prd):
        """New entries from merge always start as passes=false."""
        story = prd["userStories"][0]
        entry = story_to_prd_entry(story, "US-999")
        assert entry["passes"] is False


class TestMaxResearchStoriesCap:
    """Integration tests for SPIRAL_MAX_RESEARCH_STORIES env var."""

    # Each title uses only its own unique words (3 words each, no overlap)
    _TITLES = [
        "alpha bravo charlie", "delta echo foxtrot", "golf hotel india",
        "juliet kilo lima", "mike november oscar", "papa quebec romeo",
        "sierra tango uniform", "victor whiskey xray", "yankee zulu amber",
        "bronze copper diamond", "emerald flint granite", "hickory ivory jade",
        "kelp lemon maple", "nutmeg olive pecan", "quartz ruby sapphire",
        "topaz umber violet", "walnut xenon yew", "zinc agate basalt",
        "cedar dusk ember", "frost glow haze",
    ]

    def _make_research_file(self, path, count):
        """Write a research output JSON with `count` non-overlapping stories."""
        stories = [
            {"title": self._TITLES[i], "priority": "medium",
             "description": self._TITLES[i], "acceptanceCriteria": [f"criterion{i}"]}
            for i in range(count)
        ]
        path.write_text(json.dumps({"stories": stories}, indent=2), encoding="utf-8")

    def _make_prd(self, path):
        """Write a minimal valid prd.json with a title that won't overlap test candidates."""
        prd = {
            "productName": "TestApp",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "xyzzy plugh plover", "passes": True,
                 "priority": "medium", "description": "", "acceptanceCriteria": ["done"],
                 "dependencies": []}
            ]
        }
        path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

    def test_max_research_stories_cap(self, tmp_path, monkeypatch):
        """When SPIRAL_MAX_RESEARCH_STORIES is set, research candidates are truncated before dedup."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        self._make_prd(prd_path)
        self._make_research_file(research_path, 20)  # 20 research candidates
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        monkeypatch.setenv("SPIRAL_MAX_RESEARCH_STORIES", "5")

        # Run merge_stories.py as subprocess to test env var integration
        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
            env={**os.environ, "SPIRAL_MAX_RESEARCH_STORIES": "5"},
        )
        assert result.returncode == 0, f"merge_stories.py failed:\n{result.stderr}"

        # Verify cap message was printed (use partial match to avoid encoding issues with arrow)
        assert "Capping research output: 20" in result.stdout
        assert "5 stories" in result.stdout

        # Verify only 5 new stories were added (+ 1 existing = 6 total)
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        new_stories = [s for s in prd["userStories"] if not s.get("passes")]
        assert len(new_stories) == 5

    def test_max_research_stories_zero_is_unlimited(self, tmp_path, monkeypatch):
        """When SPIRAL_MAX_RESEARCH_STORIES=0 (default), no truncation occurs."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        self._make_prd(prd_path)
        self._make_research_file(research_path, 8)
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
            env={**os.environ, "SPIRAL_MAX_RESEARCH_STORIES": "0"},
        )
        assert result.returncode == 0, f"merge_stories.py failed:\n{result.stderr}"

        # No cap message should appear
        assert "Capping research output" not in result.stdout

        # All 8 research stories should be added
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        new_stories = [s for s in prd["userStories"] if not s.get("passes")]
        assert len(new_stories) == 8
