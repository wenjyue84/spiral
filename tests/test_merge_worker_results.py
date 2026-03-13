"""Unit tests for merge_worker_results.py (parallel result promotion)."""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_worker_results import main


def _make_story(sid, passes=False, **extra):
    """Create a minimal valid story dict."""
    s = {
        "id": sid,
        "title": f"Story {sid}",
        "passes": passes,
        "priority": "medium",
        "description": f"Description for {sid}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    s.update(extra)
    return s


def _make_prd(stories, name="TestProduct", branch="main"):
    return {
        "productName": name,
        "branchName": branch,
        "userStories": stories,
    }


def _write_prd(path, prd):
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


def _read_prd(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestSingleWorkerPassedStory:
    """AC: single worker with one passed story promotes it to main prd."""

    def test_single_worker_promotes_passed_story(self, tmp_path, monkeypatch):
        main_prd = _make_prd([_make_story("US-001"), _make_story("US-002")])
        worker_prd = _make_prd([_make_story("US-001", passes=True), _make_story("US-002")])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", worker_prd)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 0
        result = _read_prd(main_path)
        us001 = next(s for s in result["userStories"] if s["id"] == "US-001")
        us002 = next(s for s in result["userStories"] if s["id"] == "US-002")
        assert us001["passes"] is True
        assert us002["passes"] is False


class TestWorkerSkippedStory:
    """AC: worker with _skipped story propagates skipped flag to main prd."""

    def test_skipped_flag_propagated(self, tmp_path, monkeypatch):
        main_prd = _make_prd([_make_story("US-001")])
        worker_prd = _make_prd([
            _make_story("US-001", _skipped=True, _skipReason="MAX_RETRIES exhausted after 3 attempts"),
        ])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", worker_prd)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 0
        result = _read_prd(main_path)
        us001 = result["userStories"][0]
        assert us001["_skipped"] is True
        assert "MAX_RETRIES" in us001["_skipReason"]


class TestWorkerDecomposedAndSubStories:
    """AC: worker with _decomposed parent and new sub-stories — both promoted correctly."""

    def test_decomposed_parent_and_substories_promoted(self, tmp_path, monkeypatch):
        main_prd = _make_prd([_make_story("US-001")])
        worker_prd = _make_prd([
            _make_story("US-001", _decomposed=True, _decomposedInto=["US-010", "US-011"]),
            _make_story("US-010", _decomposedFrom="US-001"),
            _make_story("US-011", _decomposedFrom="US-001"),
        ])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", worker_prd)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 0
        result = _read_prd(main_path)
        us001 = next(s for s in result["userStories"] if s["id"] == "US-001")
        assert us001["_decomposed"] is True
        assert us001["_decomposedInto"] == ["US-010", "US-011"]

        # Sub-stories appended to main
        ids = [s["id"] for s in result["userStories"]]
        assert "US-010" in ids
        assert "US-011" in ids
        us010 = next(s for s in result["userStories"] if s["id"] == "US-010")
        assert us010["_decomposedFrom"] == "US-001"


class TestTwoWorkersSameStoryNoDuplicate:
    """AC: two workers both passing the same story — no duplicate in main."""

    def test_no_duplicate_when_both_workers_pass_same(self, tmp_path, monkeypatch):
        main_prd = _make_prd([_make_story("US-001"), _make_story("US-002")])
        w1_prd = _make_prd([_make_story("US-001", passes=True), _make_story("US-002")])
        w2_prd = _make_prd([_make_story("US-001", passes=True), _make_story("US-002")])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", w1_prd)
        w2_path = _write_prd(tmp_path / "w2.json", w2_prd)

        monkeypatch.setattr(sys, "argv", [
            "merge", "--main", main_path, "--workers", w1_path, w2_path,
        ])
        rc = main()

        assert rc == 0
        result = _read_prd(main_path)
        us001_list = [s for s in result["userStories"] if s["id"] == "US-001"]
        assert len(us001_list) == 1  # no duplicate
        assert us001_list[0]["passes"] is True


class TestWorkerSchemaValidationFails:
    """AC: worker prd.json fails schema validation — warns and skips, does not abort merge."""

    def test_invalid_worker_skipped_with_warning(self, tmp_path, monkeypatch, capsys):
        main_prd = _make_prd([_make_story("US-001")])
        invalid_worker = {"bad": "data"}  # missing required fields

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", invalid_worker)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 0  # merge succeeds — invalid worker skipped, not fatal
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "skipping" in captured.out


class TestWorkerFileMissing:
    """AC: worker file missing — warning printed, other workers still processed."""

    def test_missing_worker_skipped_others_processed(self, tmp_path, monkeypatch, capsys):
        main_prd = _make_prd([_make_story("US-001"), _make_story("US-002")])
        w2_prd = _make_prd([_make_story("US-001"), _make_story("US-002", passes=True)])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        missing_path = str(tmp_path / "nonexistent.json")
        w2_path = _write_prd(tmp_path / "w2.json", w2_prd)

        monkeypatch.setattr(sys, "argv", [
            "merge", "--main", main_path, "--workers", missing_path, w2_path,
        ])
        rc = main()

        assert rc == 0
        captured = capsys.readouterr()
        assert "WARNING" in captured.out  # warning about missing file
        result = _read_prd(main_path)
        us002 = next(s for s in result["userStories"] if s["id"] == "US-002")
        assert us002["passes"] is True  # other worker still processed


class TestMainPrdNotFound:
    """Edge case: main prd.json not found → exit code 1."""

    def test_missing_main_returns_1(self, tmp_path, monkeypatch):
        w1_prd = _make_prd([_make_story("US-001")])
        w1_path = _write_prd(tmp_path / "w1.json", w1_prd)
        missing_main = str(tmp_path / "nonexistent_main.json")

        monkeypatch.setattr(sys, "argv", ["merge", "--main", missing_main, "--workers", w1_path])
        rc = main()

        assert rc == 1


class TestMainPrdSchemaValidationFails:
    """Edge case: main prd.json fails schema validation → exit code 1."""

    def test_invalid_main_returns_1(self, tmp_path, monkeypatch):
        invalid_main = {"not": "a valid prd"}
        main_path = _write_prd(tmp_path / "main.json", invalid_main)
        w1_prd = _make_prd([_make_story("US-001")])
        w1_path = _write_prd(tmp_path / "w1.json", w1_prd)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 1


class TestMultipleWorkersDifferentStories:
    """Multiple workers each pass different stories — all promoted."""

    def test_both_workers_stories_promoted(self, tmp_path, monkeypatch):
        main_prd = _make_prd([
            _make_story("US-001"),
            _make_story("US-002"),
            _make_story("US-003"),
        ])
        w1_prd = _make_prd([
            _make_story("US-001", passes=True),
            _make_story("US-002"),
            _make_story("US-003"),
        ])
        w2_prd = _make_prd([
            _make_story("US-001"),
            _make_story("US-002"),
            _make_story("US-003", passes=True),
        ])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", w1_prd)
        w2_path = _write_prd(tmp_path / "w2.json", w2_prd)

        monkeypatch.setattr(sys, "argv", [
            "merge", "--main", main_path, "--workers", w1_path, w2_path,
        ])
        rc = main()

        assert rc == 0
        result = _read_prd(main_path)
        assert next(s for s in result["userStories"] if s["id"] == "US-001")["passes"] is True
        assert next(s for s in result["userStories"] if s["id"] == "US-002")["passes"] is False
        assert next(s for s in result["userStories"] if s["id"] == "US-003")["passes"] is True


class TestAlreadyPassedNotDoubleCounted:
    """Already-passed story in main is not re-promoted (newly_passed stays 0)."""

    def test_already_passed_not_recounted(self, tmp_path, monkeypatch, capsys):
        main_prd = _make_prd([_make_story("US-001", passes=True)])
        worker_prd = _make_prd([_make_story("US-001", passes=True)])

        main_path = _write_prd(tmp_path / "main.json", main_prd)
        w1_path = _write_prd(tmp_path / "w1.json", worker_prd)

        monkeypatch.setattr(sys, "argv", ["merge", "--main", main_path, "--workers", w1_path])
        rc = main()

        assert rc == 0
        captured = capsys.readouterr()
        assert "0 newly passed" in captured.out
