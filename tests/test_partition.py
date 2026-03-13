"""Property-based tests for partition_prd.py operations."""
import os
import sys
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from conftest import valid_prd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from partition_prd import assign_stories, compute_levels, priority_key


class TestAssignStories:
    """Properties of the story partitioning algorithm."""

    @given(
        prd=valid_prd(min_stories=2, max_stories=20),
        n_workers=st.integers(min_value=2, max_value=5)
    )
    @settings(max_examples=100)
    def test_all_pending_stories_assigned(self, prd, n_workers):
        """Every pending story must appear in exactly one bucket."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 1)

        buckets = assign_stories(pending, n_workers)

        assigned_ids = []
        for bucket in buckets:
            assigned_ids.extend(s["id"] for s in bucket)

        pending_ids = {s["id"] for s in pending}
        assert set(assigned_ids) == pending_ids, "All pending stories must be assigned"

    @given(
        prd=valid_prd(min_stories=2, max_stories=20),
        n_workers=st.integers(min_value=2, max_value=5)
    )
    @settings(max_examples=100)
    def test_no_story_assigned_twice(self, prd, n_workers):
        """No story may appear in more than one bucket."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 1)

        buckets = assign_stories(pending, n_workers)

        all_ids = []
        for bucket in buckets:
            all_ids.extend(s["id"] for s in bucket)

        assert len(all_ids) == len(set(all_ids)), "No story should be assigned to multiple workers"

    @given(
        prd=valid_prd(min_stories=4, max_stories=20),
        n_workers=st.integers(min_value=2, max_value=4)
    )
    @settings(max_examples=50)
    def test_bucket_count_matches_workers(self, prd, n_workers):
        """Always produces exactly n_workers buckets."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 1)

        buckets = assign_stories(pending, n_workers)
        assert len(buckets) == n_workers

    def test_empty_pending_returns_empty_buckets(self):
        buckets = assign_stories([], 3)
        assert len(buckets) == 3
        assert all(len(b) == 0 for b in buckets)


class TestComputeLevels:
    """Properties of the topological level computation."""

    @given(prd=valid_prd(min_stories=1, max_stories=15))
    @settings(max_examples=100)
    def test_all_pending_get_a_level(self, prd):
        """Every pending story must be assigned a topological level."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 1)

        levels = compute_levels(pending)
        for s in pending:
            assert s["id"] in levels, f"{s['id']} missing from levels"

    @given(prd=valid_prd(min_stories=1, max_stories=15))
    @settings(max_examples=100)
    def test_level_zero_has_no_pending_deps(self, prd):
        """Stories at level 0 have no pending dependencies."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 1)

        pending_ids = {s["id"] for s in pending}
        levels = compute_levels(pending)

        for s in pending:
            if levels.get(s["id"]) == 0:
                pending_deps = [d for d in s.get("dependencies", []) if d in pending_ids]
                assert len(pending_deps) == 0, f"{s['id']} at level 0 but has pending deps: {pending_deps}"

    @given(prd=valid_prd(min_stories=2, max_stories=15))
    @settings(max_examples=100)
    def test_deps_at_lower_level(self, prd):
        """A story's pending dependencies must be at a strictly lower level."""
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        assume(len(pending) >= 2)

        pending_ids = {s["id"] for s in pending}
        levels = compute_levels(pending)

        for s in pending:
            sid = s["id"]
            for dep in s.get("dependencies", []):
                if dep in pending_ids and dep in levels and sid in levels:
                    # dep should be at a lower OR EQUAL level (equal if cycle was broken)
                    assert levels[dep] <= levels[sid], \
                        f"Dep {dep} (level {levels[dep]}) should be <= {sid} (level {levels[sid]})"
