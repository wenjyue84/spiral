"""Tests for recommend_workers.py dynamic worker count recommendation."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from recommend_workers import recommend_workers


class TestAllIndependent:
    """When all pending stories are independent, recommend 3 workers."""

    def test_all_independent_no_deps(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            {"id": "US-002", "dependencies": [], "passes": False},
            {"id": "US-003", "dependencies": [], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        assert workers == 3
        assert independent == 3
        assert pending == 3

    def test_all_deps_already_passed(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": True},
            {"id": "US-002", "dependencies": ["US-001"], "passes": False},
            {"id": "US-003", "dependencies": ["US-001"], "passes": False},
            {"id": "US-004", "dependencies": [], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # All 3 pending stories have their deps satisfied → ratio 1.0 → 3
        assert workers == 3
        assert independent == 3
        assert pending == 3


class TestAllDependent:
    """When most stories have unresolved deps, recommend 1 worker."""

    def test_chain_dependency(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            {"id": "US-002", "dependencies": ["US-001"], "passes": False},
            {"id": "US-003", "dependencies": ["US-002"], "passes": False},
            {"id": "US-004", "dependencies": ["US-003"], "passes": False},
            {"id": "US-005", "dependencies": ["US-004"], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # Only US-001 is independent → ratio 0.2 → 1
        assert workers == 1
        assert independent == 1
        assert pending == 5

    def test_all_depend_on_pending(self):
        stories = [
            {"id": "US-001", "dependencies": ["US-002"], "passes": False},
            {"id": "US-002", "dependencies": ["US-001"], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        assert workers == 1
        assert independent == 0
        assert pending == 2


class TestMixed:
    """Mixed independence levels → 2 workers."""

    def test_mixed_ratio(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            {"id": "US-002", "dependencies": ["US-001"], "passes": False},
            {"id": "US-003", "dependencies": [], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # 2 of 3 independent → ratio 0.67 → 3
        assert workers == 3
        assert independent == 2
        assert pending == 3

    def test_exactly_at_30_percent(self):
        """Ratio exactly 0.3 → 2 workers."""
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            {"id": "US-002", "dependencies": ["US-001"], "passes": False},
            {"id": "US-003", "dependencies": ["US-001"], "passes": False},
            {"id": "US-004", "dependencies": ["US-001"], "passes": False},
            {"id": "US-005", "dependencies": ["US-001"], "passes": False},
            {"id": "US-006", "dependencies": ["US-001"], "passes": False},
            {"id": "US-007", "dependencies": ["US-001"], "passes": False},
            {"id": "US-008", "dependencies": ["US-001"], "passes": False},
            {"id": "US-009", "dependencies": ["US-001"], "passes": False},
            {"id": "US-010", "dependencies": ["US-001"], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # 1 of 10 → ratio 0.1 → 1
        assert workers == 1

    def test_ratio_between_30_and_60(self):
        """Independence ratio between 0.3 and 0.6 → 2 workers."""
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            {"id": "US-002", "dependencies": [], "passes": False},
            {"id": "US-003", "dependencies": ["US-001"], "passes": False},
            {"id": "US-004", "dependencies": ["US-002"], "passes": False},
            {"id": "US-005", "dependencies": ["US-003"], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # US-001, US-002 independent → 2/5 = 0.4 → 2 workers
        assert workers == 2
        assert independent == 2
        assert pending == 5


class TestEdgeCases:
    """Edge cases for worker recommendation."""

    def test_empty_stories(self):
        workers, independent, pending = recommend_workers([])
        assert workers == 1
        assert independent == 0
        assert pending == 0

    def test_all_passed(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": True},
            {"id": "US-002", "dependencies": [], "passes": True},
        ]
        workers, independent, pending = recommend_workers(stories)
        assert workers == 1
        assert pending == 0

    def test_single_pending_story(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        # 1/1 = 1.0 → 3 workers
        assert workers == 3
        assert independent == 1

    def test_missing_dependency_fields(self):
        """Stories without dependencies key treated as independent."""
        stories = [
            {"id": "US-001", "passes": False},
            {"id": "US-002", "passes": False},
        ]
        workers, independent, pending = recommend_workers(stories)
        assert workers == 3
        assert independent == 2

    def test_non_dict_stories_ignored(self):
        stories = [
            {"id": "US-001", "dependencies": [], "passes": False},
            "not a dict",
            None,
        ]
        workers, independent, pending = recommend_workers(stories)
        assert workers == 3
        assert independent == 1
        assert pending == 1
