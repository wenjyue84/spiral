"""Unit tests for lib/infer_dependencies.py — story dependency auto-inference."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from infer_dependencies import (
    apply_strong_deps,
    get_files_to_touch,
    infer_dependencies,
    jaccard,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _story(sid, files=None, passes=False, deps=None, **kwargs):
    """Build a minimal story dict."""
    s = {
        "id": sid,
        "title": f"Story {sid}",
        "priority": "medium",
        "passes": passes,
        "dependencies": deps or [],
        "acceptanceCriteria": [],
    }
    if files is not None:
        s["filesTouch"] = list(files)
    return s


def _prd(stories):
    return {
        "productName": "TestApp",
        "branchName": "main",
        "userStories": stories,
    }


def _write_prd(tmp_path, stories):
    path = tmp_path / "prd.json"
    path.write_text(json.dumps(_prd(stories), indent=2), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# jaccard()
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical_sets(self):
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_empty_sets(self):
        assert jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard({"a"}, set()) == 0.0

    def test_partial_overlap(self):
        # |{a,b} ∩ {b,c}| / |{a,b,c}| = 1/3
        assert abs(jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_full_containment(self):
        # |{a} ∩ {a,b}| / |{a,b}| = 1/2 = 0.5
        assert jaccard({"a"}, {"a", "b"}) == 0.5


# ---------------------------------------------------------------------------
# get_files_to_touch()
# ---------------------------------------------------------------------------


class TestGetFilesTouch:
    def test_top_level_files(self):
        story = {"filesTouch": ["lib/foo.py", "lib/bar.py"]}
        assert get_files_to_touch(story) == {"lib/foo.py", "lib/bar.py"}

    def test_technical_hints_fallback(self):
        story = {"technicalHints": {"filesTouch": ["src/main.ts"]}}
        assert get_files_to_touch(story) == {"src/main.ts"}

    def test_top_level_takes_priority(self):
        story = {
            "filesTouch": ["lib/a.py"],
            "technicalHints": {"filesTouch": ["lib/b.py"]},
        }
        assert get_files_to_touch(story) == {"lib/a.py"}

    def test_no_files_returns_empty(self):
        assert get_files_to_touch({}) == set()

    def test_technical_hints_not_dict(self):
        story = {"technicalHints": "not a dict"}
        assert get_files_to_touch(story) == set()


# ---------------------------------------------------------------------------
# infer_dependencies()
# ---------------------------------------------------------------------------


class TestInferDependencies:
    def test_empty_filesTouch_skipped(self):
        """Stories with no filesTouch are skipped — cannot infer."""
        stories = [_story("US-001"), _story("US-002")]
        strong, weak = infer_dependencies(stories)
        assert strong == []
        assert weak == []

    def test_full_overlap_is_strong(self):
        """Identical filesTouch → Jaccard 1.0 → strong."""
        files = ["lib/foo.py", "lib/bar.py"]
        stories = [_story("US-001", files=files), _story("US-002", files=files)]
        strong, weak = infer_dependencies(stories)
        assert ("US-001", "US-002") in strong
        assert len(weak) == 0

    def test_disjoint_no_overlap(self):
        """Non-overlapping files → no inferred deps."""
        stories = [
            _story("US-001", files=["lib/a.py"]),
            _story("US-002", files=["lib/b.py"]),
        ]
        strong, weak = infer_dependencies(stories)
        assert strong == []
        assert weak == []

    def test_partial_overlap_is_weak(self):
        """1/3 Jaccard → weak overlap."""
        stories = [
            _story("US-001", files=["a.py", "b.py"]),
            _story("US-002", files=["b.py", "c.py"]),
        ]
        strong, weak = infer_dependencies(stories)
        assert len(strong) == 0
        assert len(weak) == 1
        a, b, score = weak[0]
        assert {a, b} == {"US-001", "US-002"}
        assert abs(score - 1 / 3) < 1e-9

    def test_jaccard_threshold_at_exactly_half(self):
        """Jaccard = 0.5 → classified as strong."""
        stories = [
            _story("US-001", files=["a.py"]),
            _story("US-002", files=["a.py", "b.py"]),
        ]
        strong, weak = infer_dependencies(stories)
        assert len(strong) == 1
        assert len(weak) == 0

    def test_completed_stories_excluded(self):
        """Completed stories (passes=True) are not candidates."""
        stories = [
            _story("US-001", files=["lib/a.py"], passes=True),
            _story("US-002", files=["lib/a.py"]),
            _story("US-003", files=["lib/a.py"]),
        ]
        strong, weak = infer_dependencies(stories)
        # Only US-002 / US-003 pair
        assert ("US-001", "US-002") not in strong
        assert ("US-001", "US-003") not in strong
        assert ("US-002", "US-003") in strong

    def test_skipped_stories_excluded(self):
        stories = [
            _story("US-001", files=["lib/a.py"], **{"_skipped": True}),
            _story("US-002", files=["lib/a.py"]),
        ]
        # _skipped must be in the dict directly
        stories[0]["_skipped"] = True
        strong, weak = infer_dependencies(stories)
        assert len(strong) == 0


# ---------------------------------------------------------------------------
# apply_strong_deps()
# ---------------------------------------------------------------------------


class TestApplyStrongDeps:
    def test_applies_dependency_edge(self):
        stories = [_story("US-001", files=["a.py"]), _story("US-002", files=["a.py"])]
        prd = _prd(stories)
        applied, skipped = apply_strong_deps(prd, [("US-001", "US-002")])
        assert applied == 1
        assert skipped == 0
        # One of the two should have a dep on the other
        sm = {s["id"]: s for s in prd["userStories"]}
        has_edge = "US-002" in sm["US-001"].get(
            "dependencies", []
        ) or "US-001" in sm["US-002"].get("dependencies", [])
        assert has_edge

    def test_skips_existing_dep(self):
        """If b already depends on a, do not add a duplicate."""
        s1 = _story("US-001", files=["a.py"])
        s2 = _story("US-002", files=["a.py"], deps=["US-001"])
        prd = _prd([s1, s2])
        applied, skipped = apply_strong_deps(prd, [("US-001", "US-002")])
        assert applied == 0
        assert skipped == 0

    def test_would_create_cycle_is_skipped(self):
        """When the base graph already has a cycle, no new edge can be applied.
        US-001→US-003→US-002→US-001 forms a cycle; adding either direction
        between US-004 and US-005 still triggers cycle detection → skipped."""
        # Pre-existing 3-story cycle
        s1 = _story("US-001", files=["z.py"], deps=["US-003"])
        s2 = _story("US-002", files=["z.py"], deps=["US-001"])
        s3 = _story("US-003", files=["z.py"], deps=["US-002"])
        # Two fresh stories with strong overlap (not yet connected to anyone)
        s4 = _story("US-004", files=["a.py"])
        s5 = _story("US-005", files=["a.py"])
        prd = _prd([s1, s2, s3, s4, s5])
        # Both directions fail because find_cycles sees the pre-existing cycle
        applied, skipped = apply_strong_deps(prd, [("US-004", "US-005")])
        assert applied == 0
        assert skipped == 1


# ---------------------------------------------------------------------------
# main() CLI integration
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_prd_returns_1(self, tmp_path):
        sys.argv = ["infer_dependencies.py", "--prd", str(tmp_path / "missing.json")]
        assert main() == 1

    def test_no_overlap_exits_0(self, tmp_path):
        prd_path = _write_prd(
            tmp_path,
            [_story("US-001", files=["a.py"]), _story("US-002", files=["b.py"])],
        )
        sys.argv = ["infer_dependencies.py", "--prd", prd_path]
        assert main() == 0

    def test_weak_hints_written(self, tmp_path):
        prd_path = _write_prd(
            tmp_path,
            [
                _story("US-001", files=["a.py", "b.py"]),
                _story("US-002", files=["b.py", "c.py"]),
            ],
        )
        hints_path = str(tmp_path / "hints.json")
        sys.argv = [
            "infer_dependencies.py",
            "--prd",
            prd_path,
            "--out-hints",
            hints_path,
        ]
        assert main() == 0
        assert os.path.isfile(hints_path)
        data = json.loads(open(hints_path).read())
        assert "weak_overlaps" in data
        assert len(data["weak_overlaps"]) == 1
        entry = data["weak_overlaps"][0]
        assert set([entry["story_a"], entry["story_b"]]) == {"US-001", "US-002"}
        assert 0 < entry["jaccard_score"] < 0.5

    def test_auto_infer_applies_strong_deps(self, tmp_path, monkeypatch):
        """When SPIRAL_AUTO_INFER_DEPS=true, strong deps are written to prd.json."""
        monkeypatch.setenv("SPIRAL_AUTO_INFER_DEPS", "true")
        files = ["lib/foo.py", "lib/bar.py"]
        prd_path = _write_prd(
            tmp_path,
            [_story("US-001", files=files), _story("US-002", files=files)],
        )
        sys.argv = ["infer_dependencies.py", "--prd", prd_path]
        assert main() == 0
        prd = json.loads(open(prd_path).read())
        sm = {s["id"]: s for s in prd["userStories"]}
        has_edge = "US-002" in sm["US-001"].get(
            "dependencies", []
        ) or "US-001" in sm["US-002"].get("dependencies", [])
        assert has_edge

    def test_auto_infer_false_does_not_write(self, tmp_path, monkeypatch):
        """Without SPIRAL_AUTO_INFER_DEPS=true, prd.json is not modified."""
        monkeypatch.setenv("SPIRAL_AUTO_INFER_DEPS", "false")
        files = ["lib/foo.py", "lib/bar.py"]
        prd_path = _write_prd(
            tmp_path,
            [_story("US-001", files=files), _story("US-002", files=files)],
        )
        original = open(prd_path).read()
        sys.argv = ["infer_dependencies.py", "--prd", prd_path]
        assert main() == 0
        assert open(prd_path).read() == original
