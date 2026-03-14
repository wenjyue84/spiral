"""Unit tests for merge_stories.py — deduplication, ID assignment, atomic write, and overflow."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_stories import overlap_ratio, is_duplicate, find_next_id, sort_key, full_sort_key, _atomic_write_json


# ── overlap_ratio ────────────────────────────────────────────────────────


class TestOverlapRatioUnit:
    """Deterministic unit tests for overlap_ratio."""

    def test_identical_strings(self):
        assert overlap_ratio("fix failing test", "fix failing test") == 1.0

    def test_partial_overlap(self):
        # "fix" and "test" overlap out of {"fix", "failing", "test"} → 2/3
        ratio = overlap_ratio("fix failing test", "fix broken test")
        assert abs(ratio - 2 / 3) < 0.01

    def test_disjoint_strings(self):
        assert overlap_ratio("alpha beta", "gamma delta") == 0.0

    def test_empty_a_returns_zero(self):
        assert overlap_ratio("", "anything") == 0.0

    def test_empty_both_returns_zero(self):
        assert overlap_ratio("", "") == 0.0

    def test_subset_overlap(self):
        # a = {"add", "unit", "tests"}, b has all three plus more
        ratio = overlap_ratio("add unit tests", "add unit tests for merge stories")
        assert ratio == 1.0

    def test_asymmetric(self):
        # a→b and b→a can differ
        ratio_ab = overlap_ratio("add unit tests", "add unit tests for merge stories")
        ratio_ba = overlap_ratio("add unit tests for merge stories", "add unit tests")
        assert ratio_ab == 1.0
        assert ratio_ba < 1.0


# ── is_duplicate threshold behaviour ─────────────────────────────────────


class TestIsDuplicateThreshold:
    """Tests for is_duplicate at boundary thresholds: 59%, 60%, 61%."""

    def test_at_59_percent_not_duplicate(self):
        """Below default 60% threshold → not duplicate."""
        # a = {"a","b","c","d","e"} (5 words), overlap 2 → 0.4
        # Need exactly 59% overlap: 3 words shared out of ~5 → 0.6 ≥ 0.6 → still dup
        # Use custom threshold of 0.6; construct titles with exactly 59% overlap
        # 10 words in candidate, 5 overlap → 50% < 59% → not dup at threshold=0.59
        candidate = "one two three four five six seven eight nine ten"
        existing = ["one two three four five alpha bravo charlie delta echo"]
        # overlap for candidate→existing: 5/10 = 0.5
        assert not is_duplicate(candidate, existing, threshold=0.59)

    def test_at_60_percent_is_duplicate(self):
        """At exactly 60% threshold → duplicate (>=)."""
        # 5 words in candidate, 3 overlap → 0.6
        candidate = "alpha beta gamma delta epsilon"
        existing = ["alpha beta gamma zeta eta"]
        # overlap: {"alpha","beta","gamma"} / {"alpha","beta","gamma","delta","epsilon"} = 3/5 = 0.6
        assert is_duplicate(candidate, existing, threshold=0.6)

    def test_at_61_percent_not_duplicate(self):
        """Below 61% threshold → not duplicate."""
        candidate = "alpha beta gamma delta epsilon"
        existing = ["alpha beta gamma zeta eta"]
        # same 3/5 = 0.6 < 0.61 → not duplicate
        assert not is_duplicate(candidate, existing, threshold=0.61)

    def test_bidirectional_check(self):
        """is_duplicate checks overlap in both directions."""
        # a→b: 2/2=1.0, b→a: 2/5=0.4 — should be dup because a→b ≥ threshold
        candidate = "alpha beta"
        existing = ["alpha beta gamma delta epsilon"]
        assert is_duplicate(candidate, existing, threshold=0.6)

    def test_empty_existing_list(self):
        assert not is_duplicate("any title", [])

    def test_duplicate_false_for_completely_different(self):
        existing = ["add dashboard widget for metrics"]
        candidate = "fix login regression test"
        assert not is_duplicate(candidate, existing, threshold=0.6)


# ── find_next_id (ID assignment) ─────────────────────────────────────────


class TestFindNextId:
    """Tests for sequential ID assignment."""

    def test_given_us001_to_us005_next_is_006(self):
        stories = [{"id": f"US-{i:03d}"} for i in range(1, 6)]
        assert find_next_id(stories) == 6

    def test_empty_stories_returns_one(self):
        assert find_next_id([]) == 1

    def test_handles_gaps(self):
        stories = [{"id": "US-001"}, {"id": "US-005"}, {"id": "US-003"}]
        assert find_next_id(stories) == 6

    def test_ignores_non_matching_ids(self):
        stories = [{"id": "US-003"}, {"id": "TASK-99"}, {"id": ""}]
        assert find_next_id(stories) == 4

    def test_single_story(self):
        assert find_next_id([{"id": "US-010"}]) == 11


# ── Atomic write (simulated os.replace failure) ─────────────────────────


class TestAtomicWrite:
    """Tests that a failed atomic write leaves original prd.json unchanged."""

    def _make_prd(self, path, stories=None):
        if stories is None:
            stories = [
                {"id": "US-001", "title": "existing story", "passes": True,
                 "priority": "medium", "description": "", "acceptanceCriteria": ["done"],
                 "dependencies": []}
            ]
        prd = {
            "productName": "TestApp",
            "branchName": "main",
            "userStories": stories,
        }
        path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

    def _make_research(self, path, titles):
        stories = [
            {"title": t, "priority": "medium", "description": t,
             "acceptanceCriteria": [f"criterion for {t}"]}
            for t in titles
        ]
        path.write_text(json.dumps({"stories": stories}, indent=2), encoding="utf-8")

    def test_successful_merge_updates_prd(self, tmp_path):
        """Normal merge: new stories appear in prd.json after merge."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        self._make_prd(prd_path)
        self._make_research(research_path, ["completely new alpha story"])
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        assert len(prd["userStories"]) == 2

    def test_original_unchanged_when_tmp_write_blocked(self, tmp_path, monkeypatch):
        """If os.replace (via shutil.move) fails, original prd.json stays intact.

        We simulate this by making the .tmp file unwritable after writing research,
        then verifying original prd.json is unchanged.
        """
        prd_path = tmp_path / "prd.json"
        self._make_prd(prd_path)

        original_content = prd_path.read_text(encoding="utf-8")

        # Simulate failure: create a read-only tmp file to block shutil.move
        tmp_file = tmp_path / "prd.json.tmp"
        # Make the destination a directory so shutil.move fails
        tmp_file.mkdir()

        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"
        self._make_research(research_path, ["new story alpha bravo"])
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
        )
        # The merge should fail (non-zero exit or exception)
        assert result.returncode != 0 or "Error" in result.stderr or "error" in result.stderr.lower()

        # Original prd.json must be unchanged
        assert prd_path.read_text(encoding="utf-8") == original_content


# ── Atomic write unit — monkeypatch os.replace ───────────────────────────


class TestAtomicWriteUnit:
    """Unit tests for _atomic_write_json using monkeypatch on os.replace."""

    def test_os_replace_raises_leaves_original_unchanged(self, tmp_path, monkeypatch):
        """If os.replace raises, dest file is unchanged and .tmp is cleaned up."""
        import merge_stories as ms

        dest = tmp_path / "prd.json"
        original = {"productName": "Test", "branchName": "main", "userStories": []}
        dest.write_text(json.dumps(original, indent=2), encoding="utf-8")
        original_content = dest.read_text(encoding="utf-8")

        def _fail_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(ms.os, "replace", _fail_replace)

        with pytest.raises(OSError, match="simulated replace failure"):
            ms._atomic_write_json({"productName": "Changed", "userStories": []}, str(dest))

        # Original file must be unchanged
        assert dest.read_text(encoding="utf-8") == original_content
        # Tmp file must be cleaned up
        assert not (tmp_path / "prd.json.tmp").exists()

    def test_successful_write_creates_dest_and_removes_tmp(self, tmp_path):
        """Successful write produces correct dest file; no .tmp left behind."""
        dest = tmp_path / "out.json"
        data = {"key": "value", "items": [1, 2, 3]}
        _atomic_write_json(data, str(dest))

        assert dest.exists()
        assert not (tmp_path / "out.json.tmp").exists()
        assert json.loads(dest.read_text(encoding="utf-8")) == data


# ── Overflow behaviour ───────────────────────────────────────────────────


class TestOverflow:
    """Tests that excess stories go to overflow file when cap is hit."""

    # Each title uses unique words to avoid dedup
    _TITLES = [
        "alpha bravo charlie", "delta echo foxtrot", "golf hotel india",
        "juliet kilo lima", "mike november oscar", "papa quebec romeo",
        "sierra tango uniform", "victor whiskey xray",
    ]

    def _make_prd(self, path):
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

    def _make_research(self, path, count):
        stories = [
            {"title": self._TITLES[i], "priority": "medium",
             "description": self._TITLES[i], "acceptanceCriteria": [f"criterion{i}"]}
            for i in range(count)
        ]
        path.write_text(json.dumps({"stories": stories}, indent=2), encoding="utf-8")

    def test_overflow_written_when_cap_hit(self, tmp_path):
        """When --max-new is 3 and 5 candidates exist, 2 go to overflow."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"
        overflow_path = tmp_path / "overflow.json"

        self._make_prd(prd_path)
        self._make_research(research_path, 5)
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path),
             "--max-new", "3",
             "--overflow-out", str(overflow_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        # 3 stories added to prd (+ 1 existing = 4)
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        new_stories = [s for s in prd["userStories"] if not s.get("passes")]
        assert len(new_stories) == 3

        # 2 stories in overflow
        with open(overflow_path, encoding="utf-8") as f:
            overflow = json.load(f)
        assert len(overflow["stories"]) == 2

    def test_no_overflow_when_under_cap(self, tmp_path):
        """When candidates < cap, overflow file is empty."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"
        overflow_path = tmp_path / "overflow.json"

        self._make_prd(prd_path)
        self._make_research(research_path, 2)
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path),
             "--max-new", "10",
             "--overflow-out", str(overflow_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(overflow_path, encoding="utf-8") as f:
            overflow = json.load(f)
        assert len(overflow["stories"]) == 0

    def test_max_new_zero_adds_nothing(self, tmp_path):
        """--max-new 0 means nothing gets added, all go to overflow."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"
        overflow_path = tmp_path / "overflow.json"

        self._make_prd(prd_path)
        self._make_research(research_path, 3)
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path),
             "--max-new", "0",
             "--overflow-out", str(overflow_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        new_stories = [s for s in prd["userStories"] if not s.get("passes")]
        assert len(new_stories) == 0

        with open(overflow_path, encoding="utf-8") as f:
            overflow = json.load(f)
        assert len(overflow["stories"]) == 3

    def test_max_new_one_boundary(self, tmp_path):
        """--max-new 1 adds exactly one story."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        self._make_prd(prd_path)
        self._make_research(research_path, 5)
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path),
             "--max-new", "1"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        new_stories = [s for s in prd["userStories"] if not s.get("passes")]
        assert len(new_stories) == 1


# ── Priority ordering ────────────────────────────────────────────────────


class TestPriorityOrdering:
    """Tests that critical stories sort before medium in merged output."""

    def test_critical_before_medium(self):
        assert sort_key({"priority": "critical"}) < sort_key({"priority": "medium"})

    def test_high_before_low(self):
        assert sort_key({"priority": "high"}) < sort_key({"priority": "low"})

    def test_missing_priority_defaults_medium(self):
        assert sort_key({}) == sort_key({"priority": "medium"})

    def test_priority_ordering_in_merge(self, tmp_path):
        """Merged stories within a group appear sorted by priority."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        prd = {
            "productName": "TestApp",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "xyzzy plugh plover", "passes": True,
                 "priority": "medium", "description": "", "acceptanceCriteria": ["done"],
                 "dependencies": []}
            ]
        }
        prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        # Research candidates with mixed priorities
        stories = [
            {"title": "low priority zephyr quasar nebula", "priority": "low",
             "description": "low", "acceptanceCriteria": ["c1"]},
            {"title": "critical priority zenith apex summit", "priority": "critical",
             "description": "critical", "acceptanceCriteria": ["c2"]},
            {"title": "medium priority aurora borealis cosmic", "priority": "medium",
             "description": "medium", "acceptanceCriteria": ["c3"]},
        ]
        research_path.write_text(json.dumps({"stories": stories}, indent=2), encoding="utf-8")
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(prd_path, encoding="utf-8") as f:
            merged = json.load(f)

        # New stories (indices 1, 2, 3) should be sorted: critical, medium, low
        new_stories = [s for s in merged["userStories"] if not s.get("passes")]
        priorities = [s["priority"] for s in new_stories]
        assert priorities == ["critical", "medium", "low"]


# ── Post-merge sort order (US-065) ─────────────────────────────────────


class TestPostMergeSortOrder:
    """Tests that all userStories are sorted after merge: active before done,
    priority order within active, fewer deps first within same priority."""

    def test_full_sort_key_active_before_done(self):
        active = {"passes": False, "priority": "low", "dependencies": []}
        done = {"passes": True, "priority": "critical", "dependencies": []}
        assert full_sort_key(active) < full_sort_key(done)

    def test_full_sort_key_decomposed_is_done(self):
        active = {"passes": False, "priority": "medium", "dependencies": []}
        decomposed = {"_decomposed": True, "priority": "critical", "dependencies": []}
        assert full_sort_key(active) < full_sort_key(decomposed)

    def test_full_sort_key_skipped_is_done(self):
        active = {"passes": False, "priority": "medium", "dependencies": []}
        skipped = {"_skipped": True, "priority": "critical", "dependencies": []}
        assert full_sort_key(active) < full_sort_key(skipped)

    def test_full_sort_key_priority_tiebreak(self):
        high = {"passes": False, "priority": "high", "dependencies": []}
        low = {"passes": False, "priority": "low", "dependencies": []}
        assert full_sort_key(high) < full_sort_key(low)

    def test_full_sort_key_dep_count_tiebreak(self):
        fewer = {"passes": False, "priority": "medium", "dependencies": []}
        more = {"passes": False, "priority": "medium", "dependencies": ["US-001", "US-002"]}
        assert full_sort_key(fewer) < full_sort_key(more)

    def test_end_to_end_sort_after_merge(self, tmp_path):
        """After merge, prd.json stories are sorted: active by priority/deps, done at end."""
        prd_path = tmp_path / "prd.json"
        research_path = tmp_path / "research.json"
        test_stories_path = tmp_path / "test_stories.json"

        # Existing stories: one done (high), two active (low, medium)
        prd = {
            "productName": "TestApp",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "done story omega phi psi", "passes": True,
                 "priority": "high", "description": "", "acceptanceCriteria": ["done"],
                 "dependencies": []},
                {"id": "US-002", "title": "active low zephyr quasar nebula", "passes": False,
                 "priority": "low", "description": "", "acceptanceCriteria": ["c"],
                 "dependencies": []},
                {"id": "US-003", "title": "active medium aurora borealis cosmic", "passes": False,
                 "priority": "medium", "description": "", "acceptanceCriteria": ["c"],
                 "dependencies": ["US-001", "US-002"]},
            ],
        }
        prd_path.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        # Add one critical research story with no deps
        stories = [
            {"title": "critical story zenith apex summit pinnacle",
             "priority": "critical", "description": "critical",
             "acceptanceCriteria": ["c1"]},
            {"title": "medium story gamma delta epsilon zeta",
             "priority": "medium", "description": "medium",
             "acceptanceCriteria": ["c2"], "dependencies": []},
        ]
        research_path.write_text(json.dumps({"stories": stories}, indent=2), encoding="utf-8")
        test_stories_path.write_text('{"stories": []}', encoding="utf-8")

        merge_script = os.path.join(os.path.dirname(__file__), "..", "lib", "merge_stories.py")
        result = subprocess.run(
            [sys.executable, merge_script,
             "--prd", str(prd_path),
             "--research", str(research_path),
             "--test-stories", str(test_stories_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"merge failed:\n{result.stderr}"

        with open(prd_path, encoding="utf-8") as f:
            merged = json.load(f)

        all_stories = merged["userStories"]
        # Active stories should come first, sorted by priority then dep count
        # Expected order:
        #   1. critical (active, 0 deps) — US-004
        #   2. medium (active, 0 deps)  — US-005
        #   3. medium (active, 2 deps)  — US-003
        #   4. low (active, 0 deps)     — US-002
        #   5. high (done)              — US-001
        active = [s for s in all_stories if not s.get("passes")]
        done = [s for s in all_stories if s.get("passes")]

        # All active come before all done
        active_indices = [i for i, s in enumerate(all_stories) if not s.get("passes")]
        done_indices = [i for i, s in enumerate(all_stories) if s.get("passes")]
        assert max(active_indices) < min(done_indices), "Active stories must come before done"

        # Active priority order: critical, medium, medium, low
        active_priorities = [s["priority"] for s in active]
        assert active_priorities == ["critical", "medium", "medium", "low"]

        # The two medium stories: fewer deps (0) before more deps (2)
        medium_stories = [s for s in active if s["priority"] == "medium"]
        medium_dep_counts = [len(s.get("dependencies", [])) for s in medium_stories]
        assert medium_dep_counts == [0, 2]
