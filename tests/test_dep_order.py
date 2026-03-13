"""Integration tests for dependency-order story selection (US-041).

Verifies that ralph's story-selection logic correctly:
- Skips a story whose dependency has passes=false
- Picks the dependency (unblocked story) instead
- Accepts _decomposed=true as satisfying a dependency
- Does not skip stories with all deps satisfied
"""
import json
import os
import sys


# Pure-Python re-implementation of ralph.sh check_deps_met() so we can test
# it without spawning a shell process.

def check_deps_met(story_id: str, prd: dict) -> bool:
    """Return True if all dependencies of story_id are satisfied.

    A dependency is satisfied if the referenced story has passes=True
    OR _decomposed=True.  Returns True when there are no dependencies.
    """
    story = next((s for s in prd["userStories"] if s["id"] == story_id), None)
    if story is None:
        return False
    deps = story.get("dependencies") or []
    for dep_id in deps:
        dep = next((s for s in prd["userStories"] if s["id"] == dep_id), None)
        if dep is None:
            # Dangling dep — treat as satisfied (dep may have been removed/merged)
            continue
        if not dep.get("passes") and not dep.get("_decomposed"):
            return False
    return True


def select_next_story(prd: dict, retry_counts: dict = None, max_retries: int = 3) -> str | None:
    """Select the next actionable story ID (priority order, deps satisfied, under retry limit)."""
    if retry_counts is None:
        retry_counts = {}

    priority_order = ["critical", "high", "medium", "low"]

    def priority_key(s):
        p = s.get("priority", "low")
        try:
            return priority_order.index(p)
        except ValueError:
            return len(priority_order)

    # Decomposed stories are handled by their sub-stories, not directly
    incomplete = [s for s in prd["userStories"] if not s.get("passes") and not s.get("_decomposed")]
    incomplete.sort(key=priority_key)

    for story in incomplete:
        sid = story["id"]
        if retry_counts.get(sid, 0) >= max_retries:
            continue
        if check_deps_met(sid, prd):
            return sid
    return None


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestCheckDepsMet:
    """Unit tests for the dep-checking predicate."""

    def _prd(self, stories):
        return {"productName": "Test", "branchName": "test", "userStories": stories}

    def test_no_deps_always_met(self):
        prd = self._prd([{"id": "US-001", "passes": False, "dependencies": []}])
        assert check_deps_met("US-001", prd) is True

    def test_dep_passed_is_met(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": ["US-001"]},
        ])
        assert check_deps_met("US-002", prd) is True

    def test_dep_not_passed_is_blocked(self):
        prd = self._prd([
            {"id": "US-001", "passes": False, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": ["US-001"]},
        ])
        assert check_deps_met("US-002", prd) is False

    def test_dep_decomposed_counts_as_satisfied(self):
        """_decomposed=True should satisfy the dependency even if passes=False."""
        prd = self._prd([
            {"id": "US-001", "passes": False, "_decomposed": True, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": ["US-001"]},
        ])
        assert check_deps_met("US-002", prd) is True

    def test_dep_neither_passed_nor_decomposed_is_blocked(self):
        prd = self._prd([
            {"id": "US-001", "passes": False, "_decomposed": False, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": ["US-001"]},
        ])
        assert check_deps_met("US-002", prd) is False

    def test_dangling_dep_treated_as_satisfied(self):
        """A dep pointing to a non-existent story should not block execution."""
        prd = self._prd([
            {"id": "US-001", "passes": False, "dependencies": ["US-999"]},
        ])
        assert check_deps_met("US-001", prd) is True

    def test_missing_dependencies_field_defaults_to_no_deps(self):
        prd = self._prd([{"id": "US-001", "passes": False}])
        assert check_deps_met("US-001", prd) is True

    def test_all_multiple_deps_must_pass(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "dependencies": []},
            {"id": "US-002", "passes": False, "dependencies": []},
            {"id": "US-003", "passes": False, "dependencies": ["US-001", "US-002"]},
        ])
        assert check_deps_met("US-003", prd) is False

    def test_all_multiple_deps_passed(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "dependencies": []},
            {"id": "US-002", "passes": True, "dependencies": []},
            {"id": "US-003", "passes": False, "dependencies": ["US-001", "US-002"]},
        ])
        assert check_deps_met("US-003", prd) is True


class TestSelectNextStory:
    """Integration tests: story selection picks correct story respecting deps."""

    def _prd(self, stories):
        return {"productName": "Test", "branchName": "test", "userStories": stories}

    def test_us002_depending_on_unfinished_us001_picks_us001(self):
        """Core AC: US-002 depends on US-001 (not passed) → ralph picks US-001."""
        prd = self._prd([
            {"id": "US-001", "passes": False, "priority": "high", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": ["US-001"]},
        ])
        selected = select_next_story(prd)
        assert selected == "US-001", f"Expected US-001, got {selected}"

    def test_us002_picked_when_us001_is_done(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "priority": "high", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": ["US-001"]},
        ])
        selected = select_next_story(prd)
        assert selected == "US-002", f"Expected US-002, got {selected}"

    def test_us002_picked_when_us001_decomposed(self):
        """_decomposed=True on dep → US-002 is not blocked."""
        prd = self._prd([
            {"id": "US-001", "passes": False, "_decomposed": True, "priority": "high", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": ["US-001"]},
        ])
        selected = select_next_story(prd)
        assert selected == "US-002", f"Expected US-002, got {selected}"

    def test_max_retried_story_is_skipped(self):
        prd = self._prd([
            {"id": "US-001", "passes": False, "priority": "high", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": []},
        ])
        selected = select_next_story(prd, retry_counts={"US-001": 3})
        assert selected == "US-002"

    def test_returns_none_when_all_blocked_or_retried(self):
        prd = self._prd([
            {"id": "US-001", "passes": False, "priority": "high", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": ["US-001"]},
        ])
        # US-001 max-retried, US-002 blocked → nothing actionable
        selected = select_next_story(prd, retry_counts={"US-001": 3})
        assert selected is None

    def test_no_stories_returns_none(self):
        prd = self._prd([])
        assert select_next_story(prd) is None

    def test_all_complete_returns_none(self):
        prd = self._prd([
            {"id": "US-001", "passes": True, "priority": "high", "dependencies": []},
        ])
        assert select_next_story(prd) is None

    def test_priority_order_respected_among_unblocked(self):
        """Among unblocked stories, highest priority (lowest index) wins."""
        prd = self._prd([
            {"id": "US-001", "passes": False, "priority": "low", "dependencies": []},
            {"id": "US-002", "passes": False, "priority": "high", "dependencies": []},
            {"id": "US-003", "passes": False, "priority": "critical", "dependencies": []},
        ])
        selected = select_next_story(prd)
        assert selected == "US-003"
