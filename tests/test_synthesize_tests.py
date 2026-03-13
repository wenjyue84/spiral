"""Unit tests for synthesize_tests.py — report parsing and priority mapping."""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from synthesize_tests import (
    find_recent_reports,
    normalize,
    overlap_ratio,
    is_duplicate,
    PRIORITY_MAP,
    aggregate_failures,
    result_to_story,
)


# ── find_recent_reports ──────────────────────────────────────────────────


class TestFindRecentReports:
    """Tests for find_recent_reports: missing dir, empty dir, multi-report."""

    def test_missing_dir_returns_empty(self, tmp_path):
        result = find_recent_reports(str(tmp_path / "nonexistent"))
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        result = find_recent_reports(str(reports_dir))
        assert result == []

    def test_dir_with_subdirs_but_no_report_json(self, tmp_path):
        reports_dir = tmp_path / "reports"
        (reports_dir / "run-001").mkdir(parents=True)
        (reports_dir / "run-002").mkdir(parents=True)
        result = find_recent_reports(str(reports_dir))
        assert result == []

    def test_single_report(self, tmp_path):
        reports_dir = tmp_path / "reports"
        run = reports_dir / "run-001"
        run.mkdir(parents=True)
        (run / "report.json").write_text("{}", encoding="utf-8")
        result = find_recent_reports(str(reports_dir))
        assert len(result) == 1
        assert result[0].endswith("report.json")

    def test_multi_report_sorted_newest_first(self, tmp_path):
        reports_dir = tmp_path / "reports"
        for name in ["2026-01-01", "2026-03-01", "2026-02-01"]:
            run = reports_dir / name
            run.mkdir(parents=True)
            (run / "report.json").write_text("{}", encoding="utf-8")

        result = find_recent_reports(str(reports_dir), n=3)
        # Sorted reverse alphabetically: 2026-03-01, 2026-02-01, 2026-01-01
        basenames = [os.path.basename(os.path.dirname(p)) for p in result]
        assert basenames == ["2026-03-01", "2026-02-01", "2026-01-01"]

    def test_respects_n_limit(self, tmp_path):
        reports_dir = tmp_path / "reports"
        for i in range(5):
            run = reports_dir / f"run-{i:03d}"
            run.mkdir(parents=True)
            (run / "report.json").write_text("{}", encoding="utf-8")

        result = find_recent_reports(str(reports_dir), n=2)
        assert len(result) == 2


# ── normalize ────────────────────────────────────────────────────────────


class TestNormalize:
    """Tests for normalize(): punctuation, unicode, empty string."""

    def test_empty_string(self):
        assert normalize("") == set()

    def test_simple_words(self):
        assert normalize("Hello World") == {"hello", "world"}

    def test_punctuation_stripped(self):
        result = normalize("Fix: failing-test (regression)")
        assert result == {"fix", "failing", "test", "regression"}

    def test_unicode_non_alphanum_stripped(self):
        # Unicode characters like accented letters are stripped by [a-z0-9]+ pattern
        result = normalize("café résumé naïve")
        assert result == {"caf", "r", "sum", "na", "ve"}

    def test_mixed_case_lowered(self):
        assert normalize("TestClass") == {"testclass"}

    def test_numbers_preserved(self):
        result = normalize("US-050 test123")
        assert "us" in result
        assert "050" in result
        assert "test123" in result


# ── PRIORITY_MAP ─────────────────────────────────────────────────────────


class TestPriorityMap:
    """Tests for PRIORITY_MAP: all known categories and unknown fallback."""

    @pytest.mark.parametrize(
        "category,expected",
        [
            ("smoke", "critical"),
            ("security", "critical"),
            ("regression", "high"),
            ("api_contract", "high"),
            ("integration", "high"),
            ("unit", "medium"),
            ("edge_cases", "medium"),
            ("performance", "low"),
        ],
    )
    def test_known_categories(self, category, expected):
        assert PRIORITY_MAP[category] == expected

    def test_unknown_category_fallback(self):
        """Unknown categories should not be in the map; callers use .get(..., 'medium')."""
        assert "unknown_category" not in PRIORITY_MAP
        assert PRIORITY_MAP.get("unknown_category", "medium") == "medium"

    def test_all_known_categories_covered(self):
        """Ensure every key in PRIORITY_MAP is tested by the parametrized test above."""
        expected_keys = {
            "smoke", "security", "regression", "api_contract",
            "integration", "unit", "edge_cases", "performance",
        }
        assert set(PRIORITY_MAP.keys()) == expected_keys


# ── Deduplication ────────────────────────────────────────────────────────


class TestDeduplication:
    """Tests for overlap_ratio and is_duplicate."""

    def test_overlap_ratio_identical(self):
        assert overlap_ratio("fix failing test", "fix failing test") == 1.0

    def test_overlap_ratio_no_overlap(self):
        assert overlap_ratio("alpha beta", "gamma delta") == 0.0

    def test_overlap_ratio_partial(self):
        ratio = overlap_ratio("fix failing test", "fix broken test")
        # "fix" and "test" overlap out of {"fix", "failing", "test"} → 2/3
        assert abs(ratio - 2 / 3) < 0.01

    def test_overlap_ratio_empty_a(self):
        assert overlap_ratio("", "anything") == 0.0

    def test_is_duplicate_true_when_matching(self):
        existing = ["Fix failing test: regression — login"]
        candidate = "Fix failing test: regression — login flow"
        assert is_duplicate(candidate, existing, threshold=0.6)

    def test_is_duplicate_false_when_different(self):
        existing = ["Add unit tests for merge_stories.py"]
        candidate = "Fix failing test: regression — login"
        assert not is_duplicate(candidate, existing, threshold=0.6)

    def test_dedup_against_prd_story_title(self):
        """A failing test whose generated title matches an existing PRD story
        title should be detected as duplicate — preventing duplicate candidates."""
        existing_titles = [
            "Fix failing test: Login — authentication timeout",
            "Add dashboard widget for metrics",
        ]
        # Candidate closely matches the first existing title
        candidate = "Fix failing test: Login — authentication timeout error"
        assert is_duplicate(candidate, existing_titles, threshold=0.6)


# ── aggregate_failures ───────────────────────────────────────────────────


class TestAggregateFailures:
    """Tests for aggregate_failures: dedup by test ID across reports."""

    def _make_report(self, tmp_path, name, results):
        run = tmp_path / name
        run.mkdir(parents=True, exist_ok=True)
        report = {"all_results": results}
        (run / "report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return str(run / "report.json")

    def test_empty_report_list(self):
        failures, names = aggregate_failures([])
        assert failures == []
        assert names == []

    def test_single_failure(self, tmp_path):
        path = self._make_report(tmp_path, "run-001", [
            {"id": "test.foo", "status": "FAIL", "name": "test_foo"},
        ])
        failures, names = aggregate_failures([path])
        assert len(failures) == 1
        assert failures[0]["id"] == "test.foo"

    def test_dedup_across_reports(self, tmp_path):
        """Same test ID failing in two reports should only appear once."""
        p1 = self._make_report(tmp_path, "run-001", [
            {"id": "test.foo", "status": "FAIL", "name": "test_foo"},
        ])
        p2 = self._make_report(tmp_path, "run-002", [
            {"id": "test.foo", "status": "FAIL", "name": "test_foo"},
            {"id": "test.bar", "status": "ERROR", "name": "test_bar"},
        ])
        failures, names = aggregate_failures([p1, p2])
        ids = [f["id"] for f in failures]
        assert ids.count("test.foo") == 1
        assert "test.bar" in ids
        assert len(failures) == 2

    def test_passing_tests_ignored(self, tmp_path):
        path = self._make_report(tmp_path, "run-001", [
            {"id": "test.pass", "status": "PASS", "name": "test_pass"},
            {"id": "test.fail", "status": "FAIL", "name": "test_fail"},
        ])
        failures, _ = aggregate_failures([path])
        assert len(failures) == 1
        assert failures[0]["id"] == "test.fail"

    def test_invalid_json_skipped(self, tmp_path):
        run = tmp_path / "bad-run"
        run.mkdir(parents=True)
        (run / "report.json").write_text("not json", encoding="utf-8")
        failures, _ = aggregate_failures([str(run / "report.json")])
        assert failures == []


# ── result_to_story ──────────────────────────────────────────────────────


class TestResultToStory:
    """Tests for result_to_story: story generation from test failures."""

    def test_basic_story_structure(self):
        result = {
            "id": "tests.unit.module.test_file.TestFoo.test_bar",
            "name": "test_bar",
            "status": "FAIL",
            "category": "unit",
        }
        story = result_to_story(result)
        assert "title" in story
        assert "priority" in story
        assert "description" in story
        assert "acceptanceCriteria" in story
        assert story["priority"] == "medium"  # unit → medium

    def test_priority_from_category(self):
        result = {"id": "t.smoke.test_x", "name": "x", "status": "FAIL", "category": "smoke"}
        story = result_to_story(result)
        assert story["priority"] == "critical"

    def test_unknown_category_defaults_medium(self):
        result = {"id": "t.weird.test_x", "name": "x", "status": "FAIL", "category": "foobar"}
        story = result_to_story(result)
        assert story["priority"] == "medium"

    def test_error_message_in_acceptance_criteria(self):
        result = {
            "id": "t.test_x",
            "name": "test_x",
            "status": "FAIL",
            "category": "unit",
            "error": {"message": "AssertionError: expected True", "type": "AssertionError"},
        }
        story = result_to_story(result)
        ac_text = " ".join(story["acceptanceCriteria"])
        assert "AssertionError" in ac_text
