"""Unit tests for check_done.py (PRD gate + report logic)."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from check_done import main, find_latest_report


def _write_prd(tmp_path, stories):
    """Write a minimal valid prd.json and return its path."""
    prd = {
        "productName": "TestApp",
        "branchName": "main",
        "userStories": stories,
    }
    path = tmp_path / "prd.json"
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


def _write_report(tmp_path, summary, subdir="20260313-120000"):
    """Write a report.json inside reports_dir/<subdir>/ and return reports_dir path."""
    reports_dir = tmp_path / "test-reports"
    report_dir = reports_dir / subdir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"summary": summary}
    (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return str(reports_dir)


def _all_passed_story(sid="US-001"):
    return {
        "id": sid,
        "title": "Test story",
        "passes": True,
        "priority": "high",
        "description": "A test",
        "acceptanceCriteria": ["Works"],
        "dependencies": [],
    }


def _pending_story(sid="US-002"):
    return {
        "id": sid,
        "title": "Pending story",
        "passes": False,
        "priority": "medium",
        "description": "Not done",
        "acceptanceCriteria": ["Needs work"],
        "dependencies": [],
    }


class TestAllStoriesPassedCleanReport:
    """Exit 0 when all stories pass and test report is clean."""

    def test_exits_0(self, tmp_path, monkeypatch):
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        reports_dir = _write_report(tmp_path, {
            "passed": 10, "failed": 0, "errored": 0, "total": 10, "pass_rate": "100%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 0


class TestPendingStoriesPresent:
    """Exit 1 when there are pending (incomplete) stories."""

    def test_exits_1(self, tmp_path, monkeypatch):
        prd_path = _write_prd(tmp_path, [_all_passed_story(), _pending_story()])
        reports_dir = _write_report(tmp_path, {
            "passed": 10, "failed": 0, "errored": 0, "total": 10, "pass_rate": "100%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 1

    def test_decomposed_stories_not_counted_as_pending(self, tmp_path, monkeypatch):
        """Stories marked _decomposed should not count as pending."""
        decomposed = _pending_story("US-002")
        decomposed["_decomposed"] = True
        prd_path = _write_prd(tmp_path, [_all_passed_story(), decomposed])
        reports_dir = _write_report(tmp_path, {
            "passed": 5, "failed": 0, "errored": 0, "total": 5, "pass_rate": "100%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 0

    def test_skipped_stories_not_counted_as_pending(self, tmp_path, monkeypatch):
        """Stories marked _skipped should not count as pending."""
        skipped = _pending_story("US-002")
        skipped["_skipped"] = True
        prd_path = _write_prd(tmp_path, [_all_passed_story(), skipped])
        reports_dir = _write_report(tmp_path, {
            "passed": 5, "failed": 0, "errored": 0, "total": 5, "pass_rate": "100%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 0


class TestNoReportFile:
    """Exit 1 with warning when no test report directory exists."""

    def test_exits_1(self, tmp_path, monkeypatch, capsys):
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        nonexistent_dir = str(tmp_path / "no-reports")
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", nonexistent_dir])
        assert main() == 1
        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "no test report" in captured.err.lower()

    def test_exits_1_empty_reports_dir(self, tmp_path, monkeypatch):
        """Reports dir exists but has no subdirs with report.json."""
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        reports_dir = tmp_path / "test-reports"
        reports_dir.mkdir()
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", str(reports_dir)])
        assert main() == 1


class TestStaleReportPrintsWarning:
    """Stale report prints warning but does NOT change exit code."""

    def test_stale_report_still_exits_0_when_all_pass(self, tmp_path, monkeypatch, capsys):
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        reports_dir = _write_report(tmp_path, {
            "passed": 10, "failed": 0, "errored": 0, "total": 10, "pass_rate": "100%"
        })
        # Make report appear 3 hours old by mocking time.time()
        report_file = os.path.join(reports_dir, "20260313-120000", "report.json")
        real_mtime = os.path.getmtime(report_file)
        # time.time returns 3 hours (180 min) after the file mtime
        monkeypatch.setattr("check_done.time", type(sys)("fake_time"))
        import types
        fake_time = types.ModuleType("fake_time")
        fake_time.time = lambda: real_mtime + (180 * 60)
        monkeypatch.setattr("check_done.time", fake_time)

        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        result = main()
        captured = capsys.readouterr()
        # Warning should be printed
        assert "stale" in captured.err.lower() or "old" in captured.err.lower()
        # But exit code should still be 0 (all pass + clean report)
        assert result == 0


class TestFailedTestsExits1:
    """Exit 1 when report has failed tests, even if all PRD stories pass."""

    def test_exits_1(self, tmp_path, monkeypatch):
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        reports_dir = _write_report(tmp_path, {
            "passed": 8, "failed": 2, "errored": 0, "total": 10, "pass_rate": "80%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 1


class TestErroredTestsExits1:
    """Exit 1 when report has errored tests, even if all PRD stories pass."""

    def test_exits_1(self, tmp_path, monkeypatch):
        prd_path = _write_prd(tmp_path, [_all_passed_story()])
        reports_dir = _write_report(tmp_path, {
            "passed": 9, "failed": 0, "errored": 1, "total": 10, "pass_rate": "90%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", prd_path, "--reports-dir", reports_dir])
        assert main() == 1


class TestPrdFileNotFound:
    """Exit 1 when prd.json file does not exist."""

    def test_exits_1(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", str(tmp_path / "missing.json")])
        assert main() == 1


class TestInvalidPrdSchema:
    """Exit 1 when prd.json fails schema validation."""

    def test_exits_1(self, tmp_path, monkeypatch):
        bad_prd = {"not_a_valid": "prd"}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad_prd), encoding="utf-8")
        reports_dir = _write_report(tmp_path, {
            "passed": 10, "failed": 0, "errored": 0, "total": 10, "pass_rate": "100%"
        })
        monkeypatch.setattr("sys.argv", ["check_done", "--prd", str(path), "--reports-dir", reports_dir])
        assert main() == 1


class TestFindLatestReport:
    """Unit tests for the find_latest_report helper."""

    def test_returns_none_for_nonexistent_dir(self):
        assert find_latest_report("/nonexistent/path") is None

    def test_picks_latest_subdir(self, tmp_path):
        """Should pick the lexicographically last (most recent) subdirectory."""
        reports_dir = tmp_path / "reports"
        for name in ["20260310-100000", "20260313-120000", "20260311-080000"]:
            d = reports_dir / name
            d.mkdir(parents=True)
            (d / "report.json").write_text("{}", encoding="utf-8")
        result = find_latest_report(str(reports_dir))
        assert result is not None
        assert "20260313-120000" in result
