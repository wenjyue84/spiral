#!/usr/bin/env python3
"""
Regression tests for US-787: Phase I Partial Victory Commit.

Tests verify that when a story fails overall but some ACs pass:
1. Parent story is marked with _partial: true
2. AC counts are recorded (_ac_total, _ac_passed, _ac_failed)
3. Sub-stories are created for each failing AC
4. Sub-stories have _decomposedFrom pointing to parent
5. No partial victory occurs when all ACs fail or all ACs pass

Run with: pytest tests/ -k us_787 -v
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.impl.partial_victory import (
    count_passing_acs,
    create_ac_sub_stories,
    find_next_id,
    get_failing_ac_indices,
    handle_partial_victory,
    has_passing_acs,
    parse_ac_report,
)


@pytest.fixture
def tmp_dir() -> Any:
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.mark.us_787
class TestParseACReport:
    """Test AC evaluation report parsing."""

    def test_parse_valid_report(self, tmp_dir: Path) -> None:
        """Parse valid AC evaluation report."""
        report_file = tmp_dir / "report.json"
        report: dict[str, Any] = {
            "story_id": "US-100",
            "ac_evaluation": [
                {"index": 0, "text": "AC 1", "passed": True},
                {"index": 1, "text": "AC 2", "passed": False},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        result = parse_ac_report(str(report_file))
        assert result["story_id"] == "US-100"
        assert len(result["ac_evaluation"]) == 2

    def test_parse_nonexistent_file(self) -> None:
        """Nonexistent report file returns empty dict."""
        result = parse_ac_report("/nonexistent/path/report.json")
        assert result == {}

    def test_parse_invalid_json(self, tmp_dir: Path) -> None:
        """Invalid JSON returns empty dict."""
        report_file = tmp_dir / "bad.json"
        report_file.write_text("{ invalid json", encoding="utf-8")

        result = parse_ac_report(str(report_file))
        assert result == {}


@pytest.mark.us_787
class TestACEvaluationHelpers:
    """Test AC evaluation helper functions."""

    def test_has_passing_acs_mixed(self) -> None:
        """Mixed ACs: at least one passes."""
        ac_eval = [
            {"index": 0, "passed": True},
            {"index": 1, "passed": False},
        ]
        assert has_passing_acs(ac_eval) is True

    def test_has_passing_acs_all_fail(self) -> None:
        """All ACs failed."""
        ac_eval = [
            {"index": 0, "passed": False},
            {"index": 1, "passed": False},
        ]
        assert has_passing_acs(ac_eval) is False

    def test_has_passing_acs_all_pass(self) -> None:
        """All ACs passed."""
        ac_eval = [
            {"index": 0, "passed": True},
            {"index": 1, "passed": True},
        ]
        assert has_passing_acs(ac_eval) is True

    def test_count_passing_acs(self) -> None:
        """Count passing ACs correctly."""
        ac_eval = [
            {"index": 0, "passed": True},
            {"index": 1, "passed": False},
            {"index": 2, "passed": True},
        ]
        assert count_passing_acs(ac_eval) == 2

    def test_get_failing_ac_indices(self) -> None:
        """Extract indices of failing ACs."""
        ac_eval = [
            {"index": 0, "passed": True},
            {"index": 1, "passed": False},
            {"index": 2, "passed": True},
            {"index": 3, "passed": False},
        ]
        failing = get_failing_ac_indices(ac_eval)
        assert failing == [1, 3]


@pytest.mark.us_787
class TestFindNextId:
    """Test story ID generation for sub-stories."""

    def test_find_next_id_empty(self) -> None:
        """Empty story list → next ID is 1."""
        next_id = find_next_id([])
        assert next_id == 1

    def test_find_next_id_existing(self) -> None:
        """Existing stories → next ID after max."""
        stories = [
            {"id": "US-1"},
            {"id": "US-2"},
            {"id": "US-5"},
        ]
        next_id = find_next_id(stories)
        assert next_id == 6

    def test_find_next_id_gaps(self) -> None:
        """Gaps in IDs are handled correctly."""
        stories = [
            {"id": "US-1"},
            {"id": "US-10"},
            {"id": "US-3"},
        ]
        next_id = find_next_id(stories)
        assert next_id == 11


@pytest.mark.us_787
class TestCreateACSubStories:
    """Test sub-story creation for failing ACs."""

    def test_create_single_sub_story(self) -> None:
        """Single failing AC creates one sub-story."""
        failing_indices = [1]
        ac_evaluation = [
            {"index": 0, "text": "AC 1", "passed": True},
            {"index": 1, "text": "AC 2", "passed": False},
        ]
        stories = [{"id": "US-1"}]

        sub_stories = create_ac_sub_stories(
            parent_id="US-1",
            parent_title="Test Story",
            parent_description="Test",
            failing_ac_indices=failing_indices,
            ac_evaluation=ac_evaluation,
            stories=stories,
        )

        assert len(sub_stories) == 1
        assert sub_stories[0]["id"] == "US-2"
        assert sub_stories[0]["_decomposedFrom"] == "US-1"
        assert "AC 2" in sub_stories[0]["acceptanceCriteria"]

    def test_create_multiple_sub_stories(self) -> None:
        """Multiple failing ACs create multiple sub-stories."""
        failing_indices = [0, 2]
        ac_evaluation = [
            {"index": 0, "text": "AC 1", "passed": False},
            {"index": 1, "text": "AC 2", "passed": True},
            {"index": 2, "text": "AC 3", "passed": False},
        ]
        stories = [{"id": "US-100"}]

        sub_stories = create_ac_sub_stories(
            parent_id="US-100",
            parent_title="Complex",
            parent_description="Complex story",
            failing_ac_indices=failing_indices,
            ac_evaluation=ac_evaluation,
            stories=stories,
        )

        assert len(sub_stories) == 2
        assert sub_stories[0]["id"] == "US-101"
        assert sub_stories[1]["id"] == "US-102"
        assert all(s["_decomposedFrom"] == "US-100" for s in sub_stories)

    def test_sub_stories_tagged_correctly(self) -> None:
        """Sub-stories have partial-victory tag."""
        failing_indices = [0]
        ac_evaluation = [{"index": 0, "text": "AC 1", "passed": False}]
        stories = [{"id": "US-1"}]

        sub_stories = create_ac_sub_stories(
            parent_id="US-1",
            parent_title="Story",
            parent_description="",
            failing_ac_indices=failing_indices,
            ac_evaluation=ac_evaluation,
            stories=stories,
        )

        assert "partial-victory" in sub_stories[0].get("tags", [])


@pytest.mark.us_787
class TestPartialVictoryCore:
    """Core regression tests for observable behavior of US-787."""

    def test_partial_victory_2_of_3_acs(self, tmp_dir: Path) -> None:
        """Core AC: 2 of 3 ACs pass → parent marked partial, 1 sub-story created."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        # Setup: Story with 3 ACs
        prd: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Implement auth",
                    "description": "Add OAuth",
                    "acceptanceCriteria": ["OAuth setup", "JWT tokens", "Token refresh"],
                }
            ]
        }
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        # AC report: AC1 pass, AC2 pass, AC3 fail
        report: dict[str, Any] = {
            "story_id": "US-100",
            "ac_evaluation": [
                {"index": 0, "text": "OAuth setup", "passed": True},
                {"index": 1, "text": "JWT tokens", "passed": True},
                {"index": 2, "text": "Token refresh", "passed": False},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        # Execute
        success = handle_partial_victory("US-100", str(report_file), str(prd_file))
        assert success is True

        # Verify: Parent marked as partial
        updated = json.loads(prd_file.read_text(encoding="utf-8"))
        parent = updated["userStories"][0]
        assert parent["_partial"] is True
        assert parent["_ac_total"] == 3
        assert parent["_ac_passed"] == 2
        assert parent["_ac_failed"] == 1

        # Verify: Exactly 1 sub-story created
        subs = [s for s in updated["userStories"] if s.get("_decomposedFrom") == "US-100"]
        assert len(subs) == 1

        # Verify: Sub-story references failing AC
        sub = subs[0]
        assert "Token refresh" in sub["description"]
        assert sub["acceptanceCriteria"] == ["Token refresh"]

        # Verify: Total story count is 2
        assert len(updated["userStories"]) == 2

    def test_partial_victory_1_of_4_acs_fails(self, tmp_dir: Path) -> None:
        """Regression: 1 of 4 ACs fail → exactly 1 sub-story created."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-500",
                    "title": "Complex Feature",
                    "description": "Complex",
                }
            ]
        }
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-500",
            "ac_evaluation": [
                {"index": 0, "text": "Setup database", "passed": True},
                {"index": 1, "text": "Create API endpoint", "passed": True},
                {"index": 2, "text": "Write documentation", "passed": False},
                {"index": 3, "text": "Add unit tests", "passed": True},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        success = handle_partial_victory("US-500", str(report_file), str(prd_file))
        assert success is True

        updated = json.loads(prd_file.read_text(encoding="utf-8"))
        subs = [s for s in updated["userStories"] if s.get("_decomposedFrom") == "US-500"]
        assert len(subs) == 1
        assert "documentation" in subs[0]["description"].lower()

        parent = updated["userStories"][0]
        assert parent["_ac_passed"] == 3
        assert parent["_ac_failed"] == 1

    def test_no_partial_victory_all_fail(self, tmp_dir: Path) -> None:
        """All ACs fail → no partial victory (returns False)."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {"userStories": [{"id": "US-1", "title": "Story"}]}
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-1",
            "ac_evaluation": [
                {"index": 0, "text": "AC 1", "passed": False},
                {"index": 1, "text": "AC 2", "passed": False},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        result = handle_partial_victory("US-1", str(report_file), str(prd_file))

        assert result is False
        updated = json.loads(prd_file.read_text(encoding="utf-8"))
        assert "_partial" not in updated["userStories"][0]

    def test_partial_victory_all_pass_zero_decompose(self, tmp_dir: Path) -> None:
        """All ACs pass → partial marked with 0 sub-stories (no ACs to decompose)."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {"userStories": [{"id": "US-1", "title": "Story"}]}
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-1",
            "ac_evaluation": [
                {"index": 0, "text": "AC 1", "passed": True},
                {"index": 1, "text": "AC 2", "passed": True},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        result = handle_partial_victory("US-1", str(report_file), str(prd_file))

        # When all ACs pass, partial victory is processed but no subs created
        assert result is True

        updated = json.loads(prd_file.read_text(encoding="utf-8"))
        parent = updated["userStories"][0]
        assert parent["_partial"] is True
        assert parent["_ac_passed"] == 2
        assert parent["_ac_failed"] == 0

        # No sub-stories created
        subs = [s for s in updated["userStories"] if s.get("_decomposedFrom") == "US-1"]
        assert len(subs) == 0

    def test_missing_ac_report_no_partial(self, tmp_dir: Path) -> None:
        """Missing AC report → no partial victory."""
        prd_file = tmp_dir / "prd.json"
        prd: dict[str, Any] = {"userStories": [{"id": "US-1"}]}
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        result = handle_partial_victory(
            "US-1",
            str(tmp_dir / "nonexistent.json"),
            str(prd_file),
        )

        assert result is False

    def test_parent_not_in_prd_error(self, tmp_dir: Path) -> None:
        """Parent story not in prd.json → error."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {"userStories": [{"id": "US-1"}]}
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-999",
            "ac_evaluation": [
                {"index": 0, "text": "AC 1", "passed": True},
                {"index": 1, "text": "AC 2", "passed": False},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        result = handle_partial_victory("US-999", str(report_file), str(prd_file))

        assert result is False

    def test_partial_victory_3_of_5_acs_fail(self, tmp_dir: Path) -> None:
        """Multiple ACs fail: 2 of 5 pass → 3 sub-stories created."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {
            "userStories": [{"id": "US-200", "title": "Complex"}]
        }
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-200",
            "ac_evaluation": [
                {"index": 0, "text": "AC 1", "passed": True},
                {"index": 1, "text": "AC 2", "passed": False},
                {"index": 2, "text": "AC 3", "passed": False},
                {"index": 3, "text": "AC 4", "passed": False},
                {"index": 4, "text": "AC 5", "passed": True},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        success = handle_partial_victory("US-200", str(report_file), str(prd_file))
        assert success is True

        updated = json.loads(prd_file.read_text(encoding="utf-8"))

        # Verify: 3 sub-stories for 3 failing ACs
        subs = [s for s in updated["userStories"] if s.get("_decomposedFrom") == "US-200"]
        assert len(subs) == 3

        # Verify: Parent has correct counts
        parent = updated["userStories"][0]
        assert parent["_ac_passed"] == 2
        assert parent["_ac_failed"] == 3

        # Verify: Total is 1 parent + 3 subs
        assert len(updated["userStories"]) == 4
