#!/usr/bin/env python3
"""Unit tests for US-787 Partial Victory Commit."""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.impl.partial_victory import (
    add_sub_stories,
    count_passing_acs,
    create_ac_sub_stories,
    find_next_id,
    get_failing_ac_indices,
    handle_partial_victory,
    has_passing_acs,
    mark_story_as_partial,
    parse_ac_report,
)


@pytest.fixture
def tmp_dir() -> Any:
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


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


class TestHasPassingACs:
    """Test AC eligibility checking."""

    def test_all_passed(self) -> None:
        """All ACs passed."""
        ac_eval = [
            {"index": 0, "text": "AC 1", "passed": True},
            {"index": 1, "text": "AC 2", "passed": True},
        ]
        assert has_passing_acs(ac_eval) is True

    def test_none_passed(self) -> None:
        """No ACs passed."""
        ac_eval = [
            {"index": 0, "text": "AC 1", "passed": False},
        ]
        assert has_passing_acs(ac_eval) is False


class TestIntegration:
    """Integration tests for partial victory."""

    def test_partial_victory_2_of_3_acs(self, tmp_dir: Path) -> None:
        """3 ACs, 2 passing, 1 failing → partial + 1 sub."""
        prd_file = tmp_dir / "prd.json"
        report_file = tmp_dir / "ac_report.json"

        prd: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-100",
                    "title": "Implement auth",
                    "description": "Add OAuth",
                    "passes": False,
                }
            ]
        }
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        report: dict[str, Any] = {
            "story_id": "US-100",
            "ac_evaluation": [
                {"index": 0, "text": "OAuth setup", "passed": True},
                {"index": 1, "text": "JWT tokens", "passed": True},
                {"index": 2, "text": "Token refresh", "passed": False},
            ],
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")

        success = handle_partial_victory(
            "US-100", str(report_file), str(prd_file)
        )
        assert success is True

        updated = json.loads(prd_file.read_text(encoding="utf-8"))
        parent = updated["userStories"][0]
        assert parent["_partial"] is True
        assert parent["_ac_passed"] == 2
        assert parent["_ac_failed"] == 1
        assert len(updated["userStories"]) == 2
