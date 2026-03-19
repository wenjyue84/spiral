"""Integration tests for Phase M (Merge) — full merge pipeline via CLI.

Covers: multi-group merging, cap enforcement, overflow persistence, focus filtering,
priority ordering, dedup across groups, ID assignment, and atomic write safety.
"""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_stories import (
    find_next_id,
    full_sort_key,
    is_duplicate,
    load_candidates,
    matches_focus,
    story_to_prd_entry,
)


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_prd(stories: list[dict] | None = None, goals: list[str] | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "productName": "TestProject",
        "branchName": "main",
        "goals": goals or ["Build a robust system"],
        "userStories": stories or [],
    }


def _make_existing_story(story_id: str, title: str, passes: bool = True, priority: str = "medium") -> dict:
    return {
        "id": story_id,
        "title": title,
        "description": f"Description for {title}",
        "priority": priority,
        "acceptanceCriteria": ["AC1"],
        "passes": passes,
        "dependencies": [],
    }


def _make_candidate(
    title: str,
    priority: str = "medium",
    source: str = "research",
    epic_id: str = "",
    description: str = "",
) -> dict:
    return {
        "title": title,
        "description": description or f"Description for {title}",
        "priority": priority,
        "_source": source,
        "epicId": epic_id,
        "acceptanceCriteria": ["AC1"],
        "technicalNotes": ["Note1"],
        "estimatedComplexity": "small",
    }


MERGE_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "lib", "prd", "merge_stories.py")
PYTHON = sys.executable


def _run_merge(
    prd_path: str,
    research_path: str = "",
    test_stories_path: str = "",
    overflow_in: str = "",
    overflow_out: str = "",
    max_pending: int = 50,
    max_new: int = 50,
    focus: str = "",
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    cmd = [PYTHON, MERGE_SCRIPT, "--prd", prd_path]
    if research_path:
        cmd += ["--research", research_path]
    if test_stories_path:
        cmd += ["--test-stories", test_stories_path]
    if overflow_in:
        cmd += ["--overflow-in", overflow_in]
    if overflow_out:
        cmd += ["--overflow-out", overflow_out]
    if max_pending > 0:
        cmd += ["--max-pending", str(max_pending)]
    if max_new < 50:
        cmd += ["--max-new", str(max_new)]
    if focus:
        cmd += ["--focus", focus]

    env = os.environ.copy()
    env["SPIRAL_SCRATCH_DIR"] = os.path.dirname(prd_path)
    if env_extra:
        env.update(env_extra)

    return subprocess.run(cmd, capture_output=True, text=True, env=env)


@pytest.fixture()
def workspace(tmp_path):
    return {
        "prd": str(tmp_path / "prd.json"),
        "research": str(tmp_path / "research.json"),
        "test_stories": str(tmp_path / "test_stories.json"),
        "overflow_in": str(tmp_path / "overflow_in.json"),
        "overflow_out": str(tmp_path / "overflow_out.json"),
        "tmp_path": tmp_path,
    }


# ── Basic merge: research candidates added to PRD ────────────────────────────


class TestBasicMerge:
    def test_research_candidates_merged_into_prd(self, workspace):
        existing = [_make_existing_story("US-001", "Existing story")]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("New research feature")]},
        )

        result = _run_merge(workspace["prd"], research_path=workspace["research"])
        assert result.returncode == 0

        prd = _read_json(workspace["prd"])
        assert len(prd["userStories"]) == 2
        new = [s for s in prd["userStories"] if s["id"] == "US-002"]
        assert len(new) == 1
        assert new[0]["title"] == "New research feature"
        assert new[0]["passes"] is False

    def test_empty_candidates_leaves_prd_unchanged(self, workspace):
        existing = [_make_existing_story("US-001", "Existing story")]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(workspace["research"], {"stories": []})

        result = _run_merge(workspace["prd"], research_path=workspace["research"])
        assert result.returncode == 0

        prd = _read_json(workspace["prd"])
        assert len(prd["userStories"]) == 1


# ── ID assignment ─────────────────────────────────────────────────────────────


class TestIdAssignment:
    def test_ids_sequential_from_max_existing(self, workspace):
        existing = [
            _make_existing_story("US-001", "Story 1"),
            _make_existing_story("US-005", "Story 5"),  # gap
        ]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [
            _make_candidate("New A"),
            _make_candidate("New B"),
        ]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(workspace["prd"], research_path=workspace["research"])
        prd = _read_json(workspace["prd"])
        new_ids = sorted(s["id"] for s in prd["userStories"] if s["id"] not in ("US-001", "US-005"))
        assert new_ids == ["US-006", "US-007"]

    def test_ids_unique_after_merge(self, workspace):
        existing = [_make_existing_story("US-001", "Story 1")]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [_make_candidate(f"Feature {i}") for i in range(5)]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(workspace["prd"], research_path=workspace["research"])
        prd = _read_json(workspace["prd"])
        ids = [s["id"] for s in prd["userStories"]]
        assert len(ids) == len(set(ids))


# ── Cap enforcement (max_pending, max_new) ────────────────────────────────────


class TestCapEnforcement:
    def test_max_pending_blocks_new_stories(self, workspace):
        # 3 pending stories, max_pending=3 → room=0 → no new stories
        existing = [
            _make_existing_story("US-001", "Done", passes=True),
            _make_existing_story("US-002", "Pending 1", passes=False),
            _make_existing_story("US-003", "Pending 2", passes=False),
            _make_existing_story("US-004", "Pending 3", passes=False),
        ]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Should not be added")]},
        )

        result = _run_merge(workspace["prd"], research_path=workspace["research"], max_pending=3)
        assert result.returncode == 0
        assert "no new stories will be added" in result.stdout.lower() or "room: 0" in result.stdout.lower()

        prd = _read_json(workspace["prd"])
        assert len(prd["userStories"]) == 4  # unchanged

    def test_max_new_limits_additions(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [_make_candidate(f"Feature {i}") for i in range(10)]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(workspace["prd"], research_path=workspace["research"], max_new=3)
        prd = _read_json(workspace["prd"])
        new_stories = [s for s in prd["userStories"] if s["id"] != "US-001"]
        assert len(new_stories) == 3

    def test_max_pending_with_room_adds_partial(self, workspace):
        existing = [
            _make_existing_story("US-001", "Done", passes=True),
            _make_existing_story("US-002", "Pending", passes=False),
        ]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [_make_candidate(f"Feature {i}") for i in range(10)]
        _write_json(workspace["research"], {"stories": candidates})

        # max_pending=4, current_pending=1 → room=3
        _run_merge(workspace["prd"], research_path=workspace["research"], max_pending=4)
        prd = _read_json(workspace["prd"])
        new_stories = [s for s in prd["userStories"] if s["id"] not in ("US-001", "US-002")]
        assert len(new_stories) == 3


# ── Dedup across groups ──────────────────────────────────────────────────────


class TestDedup:
    def test_duplicate_research_skipped(self, workspace):
        existing = [_make_existing_story("US-001", "Add caching layer")]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Add caching layer")]},  # exact dup
        )

        _run_merge(workspace["prd"], research_path=workspace["research"])
        prd = _read_json(workspace["prd"])
        assert len(prd["userStories"]) == 1  # no addition

    def test_duplicate_test_candidate_skipped(self, workspace):
        existing = [_make_existing_story("US-001", "Fix login timeout")]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Fix login timeout", source="test-fix")]},
        )

        _run_merge(workspace["prd"], test_stories_path=workspace["test_stories"])
        prd = _read_json(workspace["prd"])
        assert len(prd["userStories"]) == 1


# ── Overflow persistence ─────────────────────────────────────────────────────


class TestOverflow:
    def test_overflow_written_when_cap_reached(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [_make_candidate(f"Feature {i}") for i in range(5)]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            overflow_out=workspace["overflow_out"],
            max_new=2,
        )
        overflow = _read_json(workspace["overflow_out"])
        assert len(overflow["stories"]) == 3  # 5 - 2 = 3 overflow

    def test_overflow_consumed_in_next_iteration(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        overflow = [_make_candidate("Overflow feature from last iter")]
        _write_json(workspace["overflow_in"], {"stories": overflow})
        _write_json(workspace["research"], {"stories": []})

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            overflow_in=workspace["overflow_in"],
        )
        prd = _read_json(workspace["prd"])
        new = [s for s in prd["userStories"] if s["id"] != "US-001"]
        assert len(new) == 1
        assert new[0]["title"] == "Overflow feature from last iter"

    def test_overflow_strips_private_fields(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [
            {**_make_candidate("Feature A"), "_internal_score": 99, "_batch_id": "b123"},
            {**_make_candidate("Feature B")},
            {**_make_candidate("Feature C")},
        ]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            overflow_out=workspace["overflow_out"],
            max_new=1,
        )
        overflow = _read_json(workspace["overflow_out"])
        for story in overflow["stories"]:
            private_keys = [k for k in story if k.startswith("_")]
            assert private_keys == [], f"Overflow story has private fields: {private_keys}"


# ── Focus filtering ───────────────────────────────────────────────────────────


class TestFocusFiltering:
    def test_focus_filters_research_hard(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [
            _make_candidate("Improve authentication security"),
            _make_candidate("Add marketing analytics"),
        ]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            focus="authentication",
        )
        prd = _read_json(workspace["prd"])
        new = [s for s in prd["userStories"] if s["id"] != "US-001"]
        assert len(new) == 1
        assert "authentication" in new[0]["title"].lower()


# ── Multi-group merge order ───────────────────────────────────────────────────


class TestMultiGroupMerge:
    def test_test_candidates_before_research(self, workspace):
        """Test candidates (group 1) are added before research (group 2)."""
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Test fix for auth", source="test-fix", priority="high")]},
        )
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Research feature for perf", priority="low")]},
        )

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
            max_new=1,
        )
        prd = _read_json(workspace["prd"])
        new = [s for s in prd["userStories"] if s["id"] != "US-001"]
        assert len(new) == 1
        assert "test fix" in new[0]["title"].lower()  # test candidate won


# ── Priority ordering ─────────────────────────────────────────────────────────


class TestPriorityOrdering:
    def test_stories_sorted_by_priority_after_merge(self, workspace):
        existing = [
            _make_existing_story("US-001", "Low prio done", passes=True, priority="low"),
        ]
        _write_json(workspace["prd"], _make_prd(existing))
        candidates = [
            _make_candidate("Low prio feature", priority="low"),
            _make_candidate("High prio feature", priority="high"),
            _make_candidate("Critical feature", priority="critical"),
        ]
        _write_json(workspace["research"], {"stories": candidates})

        _run_merge(workspace["prd"], research_path=workspace["research"])
        prd = _read_json(workspace["prd"])
        pending = [s for s in prd["userStories"] if not s.get("passes")]
        priorities = [s["priority"] for s in pending]
        # Critical should come before high, high before low
        assert priorities.index("critical") < priorities.index("high")
        assert priorities.index("high") < priorities.index("low")


# ── Source preserved in PRD entry ─────────────────────────────────────────────


class TestSourcePreservation:
    def test_source_field_preserved_in_merged_story(self, workspace):
        existing = [_make_existing_story("US-001", "Done", passes=True)]
        _write_json(workspace["prd"], _make_prd(existing))
        _write_json(
            workspace["research"],
            {"stories": [_make_candidate("Research story", source="research")]},
        )
        _write_json(
            workspace["test_stories"],
            {"stories": [_make_candidate("Test fix story", source="test-fix")]},
        )

        _run_merge(
            workspace["prd"],
            research_path=workspace["research"],
            test_stories_path=workspace["test_stories"],
        )
        prd = _read_json(workspace["prd"])
        new = [s for s in prd["userStories"] if s["id"] != "US-001"]
        sources = {s.get("_source") for s in new}
        assert "research" in sources
        assert "test-fix" in sources
