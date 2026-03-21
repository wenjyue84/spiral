"""tests/test_validate_federated_governance.py — Tests for US-672 governance validator."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Add lib to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from validate_federated_governance import (  # noqa: E402
    GovernanceRule,
    Violation,
    format_json_report,
    format_text_report,
    load_governance_rules,
    validate_stories,
)


class TestGovernanceRuleValidation:
    """Tests for GovernanceRule dataclass initialization."""

    def test_valid_rule_creation(self) -> None:
        """Test creating a valid governance rule."""
        rule = GovernanceRule(
            project_id="web-app",
            max_stories_per_iteration=3,
            id_pattern_regex="^WEB-\\d+$",
            allowed_phases=["I", "V"],
        )
        assert rule.project_id == "web-app"
        assert rule.max_stories_per_iteration == 3
        assert rule.id_pattern_regex == "^WEB-\\d+$"
        assert rule.allowed_phases == ["I", "V"]

    def test_invalid_regex_raises_error(self) -> None:
        """Test that invalid regex in id_pattern_regex raises ValueError."""
        with pytest.raises(ValueError, match="Invalid regex"):
            GovernanceRule(
                project_id="bad-project",
                max_stories_per_iteration=5,
                id_pattern_regex="[invalid(regex",
                allowed_phases=[],
            )

    def test_rule_with_wildcard_regex(self) -> None:
        """Test rule with permissive regex pattern."""
        rule = GovernanceRule(
            project_id="any-project",
            max_stories_per_iteration=999,
            id_pattern_regex=".*",
            allowed_phases=[],
        )
        assert rule.id_pattern_regex == ".*"


class TestLoadGovernanceRules:
    """Tests for load_governance_rules function."""

    def test_load_valid_governance_json(self) -> None:
        """Test loading a valid governance.json file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "rules": [
                        {
                            "project_id": "web",
                            "max_stories_per_iteration": 5,
                            "id_pattern_regex": "^WEB-\\d+$",
                            "allowed_phases": ["I", "V"],
                        }
                    ]
                },
                f,
            )
            f.flush()
            path = Path(f.name)

        try:
            rules = load_governance_rules(path)
            assert len(rules) == 1
            assert rules[0].project_id == "web"
            assert rules[0].max_stories_per_iteration == 5
        finally:
            path.unlink()

    def test_load_nonexistent_file(self) -> None:
        """Test that loading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_governance_rules(Path("/nonexistent/governance.json"))

    def test_load_multiple_rules(self) -> None:
        """Test loading multiple governance rules."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "rules": [
                        {
                            "project_id": "web",
                            "max_stories_per_iteration": 3,
                            "id_pattern_regex": "^WEB-\\d+$",
                            "allowed_phases": [],
                        },
                        {
                            "project_id": "api",
                            "max_stories_per_iteration": 5,
                            "id_pattern_regex": "^API-\\d+$",
                            "allowed_phases": ["I"],
                        },
                    ]
                },
                f,
            )
            f.flush()
            path = Path(f.name)

        try:
            rules = load_governance_rules(path)
            assert len(rules) == 2
            assert rules[0].project_id == "web"
            assert rules[1].project_id == "api"
        finally:
            path.unlink()

    def test_load_empty_rules(self) -> None:
        """Test loading governance.json with no rules."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"rules": []}, f)
            f.flush()
            path = Path(f.name)

        try:
            rules = load_governance_rules(path)
            assert rules == []
        finally:
            path.unlink()

    def test_load_missing_rules_key(self) -> None:
        """Test loading governance.json with missing 'rules' key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            f.flush()
            path = Path(f.name)

        try:
            rules = load_governance_rules(path)
            assert rules == []
        finally:
            path.unlink()


class TestValidateStoriesQuota:
    """Tests for story quota violations."""

    def test_no_violations_under_quota(self) -> None:
        """Test that stories under quota pass validation."""
        rule = GovernanceRule(
            project_id="default",
            max_stories_per_iteration=5,
            id_pattern_regex=".*",
            allowed_phases=[],
        )
        stories = [
            {"id": "US-001", "title": "Story 1", "sub_project": "default"},
            {"id": "US-002", "title": "Story 2", "sub_project": "default"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0

    def test_quota_exceeded_violation(self) -> None:
        """Test that exceeding quota generates a violation."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=2,
            id_pattern_regex=".*",
            allowed_phases=[],
        )
        stories = [
            {"id": "US-001", "title": "Story 1", "sub_project": "web"},
            {"id": "US-002", "title": "Story 2", "sub_project": "web"},
            {"id": "US-003", "title": "Story 3", "sub_project": "web"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 1
        assert violations[0].violation_type == "quota"
        assert violations[0].project_id == "web"
        assert "exceeds quota" in violations[0].message
        assert "3 active, max=2" in violations[0].message

    def test_quota_at_limit(self) -> None:
        """Test that stories exactly at quota pass validation."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=3,
            id_pattern_regex=".*",
            allowed_phases=[],
        )
        stories = [
            {"id": "US-001", "title": "Story 1", "sub_project": "web"},
            {"id": "US-002", "title": "Story 2", "sub_project": "web"},
            {"id": "US-003", "title": "Story 3", "sub_project": "web"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0


class TestValidateStoriesIdPattern:
    """Tests for ID pattern violations."""

    def test_id_pattern_match(self) -> None:
        """Test that IDs matching pattern pass validation."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex="^WEB-\\d+$",
            allowed_phases=[],
        )
        stories = [
            {"id": "WEB-001", "title": "Story 1", "sub_project": "web"},
            {"id": "WEB-100", "title": "Story 2", "sub_project": "web"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0

    def test_id_pattern_mismatch(self) -> None:
        """Test that IDs not matching pattern generate violations."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex="^WEB-\\d+$",
            allowed_phases=[],
        )
        stories = [
            {"id": "WEB-001", "title": "Story 1", "sub_project": "web"},
            {"id": "US-002", "title": "Story 2", "sub_project": "web"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 1
        assert violations[0].violation_type == "id_pattern"
        assert violations[0].story_id == "US-002"
        assert "does not match pattern" in violations[0].message

    def test_missing_id_field_skipped(self) -> None:
        """Test that stories without ID are skipped."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex="^WEB-\\d+$",
            allowed_phases=[],
        )
        stories = [
            {"title": "Story without ID", "sub_project": "web"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0


class TestValidateStoriesPhases:
    """Tests for allowed phases violations."""

    def test_phase_in_allowed_list(self) -> None:
        """Test that phases in allowed_phases pass validation."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex=".*",
            allowed_phases=["I", "V"],
        )
        stories = [
            {
                "id": "WEB-001",
                "title": "Story 1",
                "sub_project": "web",
                "phases": ["I"],
            },
            {
                "id": "WEB-002",
                "title": "Story 2",
                "sub_project": "web",
                "phases": ["V"],
            },
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0

    def test_phase_not_in_allowed_list(self) -> None:
        """Test that phases not in allowed_phases generate violations."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex=".*",
            allowed_phases=["I", "V"],
        )
        stories = [
            {
                "id": "WEB-001",
                "title": "Story 1",
                "sub_project": "web",
                "phases": ["R"],
            },
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 1
        assert violations[0].violation_type == "phase"
        assert violations[0].story_id == "WEB-001"
        assert "not in allowed_phases" in violations[0].message

    def test_multiple_phases_all_allowed(self) -> None:
        """Test that all phases in a list must be allowed."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex=".*",
            allowed_phases=["I", "V"],
        )
        stories = [
            {
                "id": "WEB-001",
                "title": "Story 1",
                "sub_project": "web",
                "phases": ["I", "V"],
            },
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0

    def test_story_without_phases_field_skipped(self) -> None:
        """Test that stories without phases field are skipped."""
        rule = GovernanceRule(
            project_id="web",
            max_stories_per_iteration=999,
            id_pattern_regex=".*",
            allowed_phases=["I", "V"],
        )
        stories = [
            {
                "id": "WEB-001",
                "title": "Story 1",
                "sub_project": "web",
            },
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 0


class TestMultipleProjects:
    """Tests for validation with multiple projects."""

    def test_separate_quotas_per_project(self) -> None:
        """Test that quota violations are per-project."""
        rules = [
            GovernanceRule(
                project_id="web",
                max_stories_per_iteration=2,
                id_pattern_regex=".*",
                allowed_phases=[],
            ),
            GovernanceRule(
                project_id="api",
                max_stories_per_iteration=3,
                id_pattern_regex=".*",
                allowed_phases=[],
            ),
        ]
        stories = [
            {"id": "US-001", "sub_project": "web"},
            {"id": "US-002", "sub_project": "web"},
            {"id": "US-003", "sub_project": "web"},  # Exceeds web quota
            {"id": "US-004", "sub_project": "api"},
            {"id": "US-005", "sub_project": "api"},
        ]
        violations = validate_stories(stories, rules)
        assert len(violations) == 1
        assert violations[0].project_id == "web"
        assert "3 active, max=2" in violations[0].message

    def test_default_project_mapping(self) -> None:
        """Test that empty/None sub_project maps to 'default'."""
        rule = GovernanceRule(
            project_id="default",
            max_stories_per_iteration=2,
            id_pattern_regex=".*",
            allowed_phases=[],
        )
        stories = [
            {"id": "US-001"},  # No sub_project field
            {"id": "US-002", "sub_project": None},
            {"id": "US-003", "sub_project": ""},
            {"id": "US-004", "sub_project": "default"},
        ]
        violations = validate_stories(stories, [rule])
        assert len(violations) == 1
        assert violations[0].project_id == "default"
        assert "4 active, max=2" in violations[0].message


class TestFormatTextReport:
    """Tests for text output formatting."""

    def test_empty_violations(self) -> None:
        """Test formatting with no violations."""
        violations: list[Violation] = []
        report = format_text_report(violations)
        assert "[ok] No governance violations found" in report

    def test_single_violation(self) -> None:
        """Test formatting a single violation."""
        violations = [
            Violation(
                violation_type="quota",
                project_id="web",
                story_id="",
                message="exceeds quota (3 active, max=2)",
            )
        ]
        report = format_text_report(violations)
        assert "Project: web" in report
        assert "exceeds quota" in report

    def test_multiple_violations_grouped_by_project(self) -> None:
        """Test that violations are grouped by project."""
        violations = [
            Violation(
                violation_type="quota",
                project_id="web",
                story_id="",
                message="exceeds quota (3 active, max=2)",
            ),
            Violation(
                violation_type="id_pattern",
                project_id="web",
                story_id="US-001",
                message="ID does not match pattern",
            ),
            Violation(
                violation_type="quota",
                project_id="api",
                story_id="",
                message="exceeds quota (5 active, max=4)",
            ),
        ]
        report = format_text_report(violations)
        assert "Project: api" in report
        assert "Project: web" in report
        # Check that api violations appear before web (alphabetical order)
        assert report.index("Project: api") < report.index("Project: web")


class TestFormatJsonReport:
    """Tests for JSON output formatting."""

    def test_empty_violations_json(self) -> None:
        """Test JSON formatting with no violations."""
        violations: list[Violation] = []
        json_str = format_json_report(violations)
        data = json.loads(json_str)
        assert data == {"violations": {}}

    def test_single_violation_json(self) -> None:
        """Test JSON formatting a single violation."""
        violations = [
            Violation(
                violation_type="quota",
                project_id="web",
                story_id="",
                message="exceeds quota (3 active, max=2)",
            )
        ]
        json_str = format_json_report(violations)
        data = json.loads(json_str)
        assert "web" in data["violations"]
        assert len(data["violations"]["web"]) == 1
        assert data["violations"]["web"][0]["type"] == "quota"
        assert data["violations"]["web"][0]["message"] == "exceeds quota (3 active, max=2)"

    def test_multiple_violations_json(self) -> None:
        """Test JSON formatting with multiple violations per project."""
        violations = [
            Violation(
                violation_type="quota",
                project_id="web",
                story_id="",
                message="exceeds quota",
            ),
            Violation(
                violation_type="id_pattern",
                project_id="web",
                story_id="US-001",
                message="ID mismatch",
            ),
        ]
        json_str = format_json_report(violations)
        data = json.loads(json_str)
        assert len(data["violations"]["web"]) == 2


class TestIntegration:
    """Integration tests for complete governance validation workflow."""

    def test_full_validation_workflow(self) -> None:
        """Test loading rules, validating stories, and formatting output."""
        # Create governance.json
        governance_dict = {
            "rules": [
                {
                    "project_id": "web",
                    "max_stories_per_iteration": 3,
                    "id_pattern_regex": "^WEB-\\d+$",
                    "allowed_phases": ["I", "V"],
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(governance_dict, f)
            gov_path = Path(f.name)

        try:
            rules = load_governance_rules(gov_path)

            stories = [
                {"id": "WEB-001", "title": "S1", "sub_project": "web", "phases": ["I"]},
                {"id": "WEB-002", "title": "S2", "sub_project": "web", "phases": ["I"]},
                {"id": "INVALID-001", "title": "S3", "sub_project": "web"},
            ]

            violations = validate_stories(stories, rules)
            # Should have 1 violation: ID pattern mismatch
            assert len(violations) == 1
            assert violations[0].violation_type == "id_pattern"

            report = format_text_report(violations)
            assert "INVALID-001" in report
        finally:
            gov_path.unlink()

    def test_no_violations_all_rules_pass(self) -> None:
        """Test full workflow with no violations."""
        governance_dict = {
            "rules": [
                {
                    "project_id": "web",
                    "max_stories_per_iteration": 5,
                    "id_pattern_regex": "^WEB-\\d+$",
                    "allowed_phases": ["I", "V"],
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(governance_dict, f)
            gov_path = Path(f.name)

        try:
            rules = load_governance_rules(gov_path)
            stories = [
                {"id": "WEB-001", "title": "S1", "sub_project": "web", "phases": ["I"]},
                {"id": "WEB-002", "title": "S2", "sub_project": "web", "phases": ["V"]},
            ]
            violations = validate_stories(stories, rules)
            assert len(violations) == 0

            report = format_text_report(violations)
            assert "[ok]" in report
        finally:
            gov_path.unlink()
