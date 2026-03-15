"""Tests for lib/conflict_preflight.py — pre-flight cross-story conflict detection."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import conflict_preflight as cp


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _story(
    sid: str,
    priority: str = "medium",
    files: list[str] | None = None,
    hints_files: list[str] | None = None,
) -> dict:
    s: dict = {"id": sid, "priority": priority, "title": f"Story {sid}"}
    if files is not None:
        s["filesTouch"] = files
    if hints_files is not None:
        s["technicalHints"] = {"filesTouch": hints_files}
    return s


def _prd(tmp_path: Path, stories: list[dict]) -> Path:
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return p


# ── get_files_to_touch ─────────────────────────────────────────────────────────


class TestGetFilesToTouch:
    def test_top_level_files(self):
        s = _story("US-1", files=["a.py", "b.py"])
        assert cp.get_files_to_touch(s) == {"a.py", "b.py"}

    def test_technical_hints_fallback(self):
        s = _story("US-1", hints_files=["c.py"])
        assert cp.get_files_to_touch(s) == {"c.py"}

    def test_top_level_takes_precedence(self):
        s = _story("US-1", files=["a.py"], hints_files=["b.py"])
        assert cp.get_files_to_touch(s) == {"a.py"}

    def test_no_files(self):
        s = _story("US-1")
        assert cp.get_files_to_touch(s) == set()

    def test_empty_technical_hints_dict(self):
        s = {"id": "US-1", "technicalHints": {}}
        assert cp.get_files_to_touch(s) == set()

    def test_technical_hints_not_dict(self):
        s = {"id": "US-1", "technicalHints": "string"}
        assert cp.get_files_to_touch(s) == set()


# ── priority_rank ──────────────────────────────────────────────────────────────


class TestPriorityRank:
    def test_critical(self):
        assert cp.priority_key(_story("US-1", priority="critical")) == 0

    def test_high(self):
        assert cp.priority_key(_story("US-1", priority="high")) == 1

    def test_medium(self):
        assert cp.priority_key(_story("US-1", priority="medium")) == 2

    def test_low(self):
        assert cp.priority_key(_story("US-1", priority="low")) == 3

    def test_unknown_defaults_medium(self):
        assert cp.priority_key({"id": "US-1"}) == 2


# ── check_pair (no git branches) ──────────────────────────────────────────────


class TestCheckPair:
    def test_no_overlap(self):
        sa = _story("US-1", files=["a.py"])
        sb = _story("US-2", files=["b.py"])
        result = cp.check_pair(sa, sb, ".", {})
        assert result == []

    def test_overlap_no_branches(self):
        sa = _story("US-1", files=["shared.py", "a.py"])
        sb = _story("US-2", files=["shared.py", "b.py"])
        result = cp.check_pair(sa, sb, ".", {})
        assert "shared.py" in result

    def test_no_files_no_conflict(self):
        sa = _story("US-1")
        sb = _story("US-2")
        result = cp.check_pair(sa, sb, ".", {})
        assert result == []

    def test_overlap_result_is_sorted(self):
        sa = _story("US-1", files=["z.py", "a.py"])
        sb = _story("US-2", files=["z.py", "a.py"])
        result = cp.check_pair(sa, sb, ".", {})
        assert result == sorted(result)

    def test_branches_exist_clean_overrides_filesTouch(self):
        """git merge-tree returning clean overrides filesTouch overlap."""
        sa = _story("US-1", files=["shared.py"])
        sb = _story("US-2", files=["shared.py"])
        branches = {"US-1": "branch-a", "US-2": "branch-b"}
        with patch.object(cp, "_branch_exists", return_value=True), \
             patch.object(cp, "_check_merge_tree", return_value=[]):
            result = cp.check_pair(sa, sb, ".", branches)
        # merge-tree says no conflict — trust it
        assert result == []

    def test_branches_exist_conflict_reported(self):
        """git merge-tree returning conflicts is forwarded."""
        sa = _story("US-1", files=["shared.py"])
        sb = _story("US-2", files=["shared.py"])
        branches = {"US-1": "branch-a", "US-2": "branch-b"}
        with patch.object(cp, "_branch_exists", return_value=True), \
             patch.object(cp, "_check_merge_tree", return_value=["shared.py"]):
            result = cp.check_pair(sa, sb, ".", branches)
        assert "shared.py" in result

    def test_only_one_branch_exists_falls_back_to_files(self):
        """If only one branch exists, skip merge-tree and fall back to filesTouch."""
        sa = _story("US-1", files=["shared.py"])
        sb = _story("US-2", files=["shared.py"])
        branches = {"US-1": "branch-a", "US-2": "branch-b"}
        # Simulate only branch-a existing
        with patch.object(cp, "_branch_exists", side_effect=lambda r, b: b == "branch-a"):
            result = cp.check_pair(sa, sb, ".", branches)
        assert "shared.py" in result


# ── run_preflight ──────────────────────────────────────────────────────────────


class TestRunPreflight:
    def test_less_than_two_stories_returns_empty(self, tmp_path: Path):
        prd_path = _prd(tmp_path, [_story("US-1", files=["a.py"])])
        result = cp.run_preflight(str(prd_path), ["US-1"], ".", "", 1)
        assert result["deferred"] == []
        assert result["conflicts"] == []

    def test_no_overlap_no_deferral(self, tmp_path: Path):
        stories = [
            _story("US-1", priority="high", files=["a.py"]),
            _story("US-2", priority="medium", files=["b.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", "", 1)
        assert result["deferred"] == []
        assert result["conflicts"] == []

    def test_lower_priority_deferred(self, tmp_path: Path):
        stories = [
            _story("US-1", priority="high", files=["shared.py"]),
            _story("US-2", priority="low", files=["shared.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", "", 1)
        assert result["deferred"] == ["US-2"]
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["deferred"] == "US-2"

    def test_equal_priority_second_deferred(self, tmp_path: Path):
        """When priorities are equal, the second story in pair order is deferred."""
        stories = [
            _story("US-1", priority="medium", files=["shared.py"]),
            _story("US-2", priority="medium", files=["shared.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", "", 1)
        # US-1 has rank 2, US-2 has rank 2 → rank_a >= rank_b → loser = sa = US-1
        assert result["deferred"] == ["US-1"]

    def test_conflict_log_written(self, tmp_path: Path):
        stories = [
            _story("US-1", priority="high", files=["shared.py"]),
            _story("US-2", priority="low", files=["shared.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        log_path = tmp_path / ".spiral" / "conflict-log.jsonl"
        cp.run_preflight(
            str(prd_path), ["US-1", "US-2"], ".", str(log_path), 3
        )
        assert log_path.exists()
        entry = json.loads(log_path.read_text())
        assert entry["event"] == "preflight_conflict"
        assert entry["batch"] == 3
        assert entry["deferred"] == "US-2"
        assert "shared.py" in entry["conflictingFiles"]

    def test_no_conflicts_no_log_file(self, tmp_path: Path):
        stories = [
            _story("US-1", files=["a.py"]),
            _story("US-2", files=["b.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        log_path = tmp_path / "conflict-log.jsonl"
        cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", str(log_path), 1)
        assert not log_path.exists()

    def test_elapsed_ms_non_negative(self, tmp_path: Path):
        stories = [_story("US-1", files=["a.py"]), _story("US-2", files=["b.py"])]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", "", 1)
        assert result["elapsed_ms"] >= 0

    def test_already_deferred_story_not_double_deferred(self, tmp_path: Path):
        """Once a story is deferred it won't also be flagged in another pair."""
        stories = [
            _story("US-1", priority="low", files=["shared.py", "other.py"]),
            _story("US-2", priority="high", files=["shared.py"]),
            _story("US-3", priority="high", files=["other.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2", "US-3"], ".", "", 1)
        # US-1 conflicts with both US-2 and US-3; it should be deferred once only
        assert result["deferred"] == ["US-1"]

    def test_batch_number_in_conflict_entry(self, tmp_path: Path):
        stories = [
            _story("US-1", priority="high", files=["f.py"]),
            _story("US-2", priority="low", files=["f.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        result = cp.run_preflight(str(prd_path), ["US-1", "US-2"], ".", "", 7)
        assert result["conflicts"][0]["batch"] == 7

    def test_completes_quickly_for_eight_stories(self, tmp_path: Path):
        """Detection must complete within 5 seconds for batches of up to 8 stories."""
        stories = [
            _story(f"US-{i}", priority="medium", files=[f"file{i}.py"])
            for i in range(1, 9)
        ]
        prd_path = _prd(tmp_path, stories)
        ids = [s["id"] for s in stories]
        import time
        start = time.monotonic()
        result = cp.run_preflight(str(prd_path), ids, ".", "", 1)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        # No overlaps — no conflicts
        assert result["deferred"] == []


# ── update_prd_defer_stories ───────────────────────────────────────────────────


class TestUpdatePrdDeferStories:
    def test_sets_passes_false(self, tmp_path: Path):
        s = _story("US-1")
        s["passes"] = True
        prd_path = _prd(tmp_path, [s])
        cp.update_prd_defer_stories(str(prd_path), ["US-1"])
        prd = json.loads(prd_path.read_text())
        assert prd["userStories"][0]["passes"] is False

    def test_sets_conflict_deferred_flag(self, tmp_path: Path):
        s = _story("US-1")
        prd_path = _prd(tmp_path, [s])
        cp.update_prd_defer_stories(str(prd_path), ["US-1"])
        prd = json.loads(prd_path.read_text())
        assert prd["userStories"][0]["_conflictDeferred"] is True

    def test_clears_failure_reason(self, tmp_path: Path):
        s = _story("US-1")
        s["_failureReason"] = "old reason"
        prd_path = _prd(tmp_path, [s])
        cp.update_prd_defer_stories(str(prd_path), ["US-1"])
        prd = json.loads(prd_path.read_text())
        assert "_failureReason" not in prd["userStories"][0]

    def test_only_targets_specified_story(self, tmp_path: Path):
        s1 = _story("US-1")
        s1["passes"] = True
        s2 = _story("US-2")
        s2["passes"] = True
        prd_path = _prd(tmp_path, [s1, s2])
        cp.update_prd_defer_stories(str(prd_path), ["US-1"])
        prd = json.loads(prd_path.read_text())
        assert prd["userStories"][0]["passes"] is False
        assert prd["userStories"][1]["passes"] is True

    def test_empty_list_is_noop(self, tmp_path: Path):
        s = _story("US-1")
        s["passes"] = True
        prd_path = _prd(tmp_path, [s])
        original = prd_path.read_text()
        cp.update_prd_defer_stories(str(prd_path), [])
        assert prd_path.read_text() == original

    def test_atomic_write(self, tmp_path: Path):
        """Verify the temp file is removed after a successful write."""
        s = _story("US-1")
        prd_path = _prd(tmp_path, [s])
        cp.update_prd_defer_stories(str(prd_path), ["US-1"])
        tmp_file = Path(str(prd_path) + ".conflict_preflight.tmp")
        assert not tmp_file.exists()


# ── CLI ────────────────────────────────────────────────────────────────────────


class TestCLI:
    def test_cli_no_conflicts(self, tmp_path: Path, capsys):
        stories = [_story("US-1", files=["a.py"]), _story("US-2", files=["b.py"])]
        prd_path = _prd(tmp_path, stories)
        import sys as _sys
        argv_backup = _sys.argv[:]
        _sys.argv = [
            "conflict_preflight.py",
            "--prd", str(prd_path),
            "--story-ids", "US-1", "US-2",
            "--repo-root", ".",
        ]
        try:
            rc = cp.main()
        finally:
            _sys.argv = argv_backup
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["deferred"] == []

    def test_cli_with_update_prd(self, tmp_path: Path, capsys):
        stories = [
            _story("US-1", priority="high", files=["f.py"]),
            _story("US-2", priority="low", files=["f.py"]),
        ]
        prd_path = _prd(tmp_path, stories)
        import sys as _sys
        argv_backup = _sys.argv[:]
        _sys.argv = [
            "conflict_preflight.py",
            "--prd", str(prd_path),
            "--story-ids", "US-1", "US-2",
            "--repo-root", ".",
            "--update-prd",
        ]
        try:
            rc = cp.main()
        finally:
            _sys.argv = argv_backup
        assert rc == 0
        # US-2 should now be marked pending with _conflictDeferred
        prd = json.loads(prd_path.read_text())
        deferred = next(s for s in prd["userStories"] if s["id"] == "US-2")
        assert deferred["_conflictDeferred"] is True
