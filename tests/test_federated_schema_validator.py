"""tests/test_federated_schema_validator.py — Tests for US-1057.

Covers:
- AC1: Duplicate story ID detection across subprojects with locations
- AC2: Namespace prefix validation with suggested fix
- AC3: JSON report format (pass, error_count, errors, suggestions)
"""

from __future__ import annotations

from lib.federated_schema_validator import (
    detect_duplicates,
    validate,
    validate_namespace_prefixes,
)


def test_clean_prd_passes() -> None:
    """AC1+AC2: Clean PRD with unique IDs and correct prefixes passes."""
    prd: dict = {
        "subProjects": [{"name": "makan", "namespace_prefix": "MAKAN-"}],
        "userStories": [
            {"id": "MAKAN-US-001", "title": "Menu Display", "sub_project": "makan"},
            {"id": "US-100", "title": "Root story"},
        ],
    }
    result = validate(prd)
    assert result["pass"] is True
    assert result["error_count"] == 0
    assert result["errors"] == []


def test_duplicate_ids_detected() -> None:
    """AC1: Duplicate story ID across subprojects is detected."""
    stories: list[dict] = [
        {"id": "US-1", "sub_project": "alpha"},
        {"id": "US-1", "sub_project": "beta"},
    ]
    dups = detect_duplicates(stories)
    assert len(dups) == 1
    assert dups[0]["story_id"] == "US-1"


def test_duplicate_ids_report_locations() -> None:
    """AC1: Error report includes subproject locations for each duplicate."""
    stories: list[dict] = [
        {"id": "US-42", "sub_project": "makan"},
        {"id": "US-42", "sub_project": "pelangi"},
    ]
    dups = detect_duplicates(stories)
    assert dups[0]["locations"] == ["makan", "pelangi"]


def test_duplicate_ids_in_validate_output() -> None:
    """AC1: validate() includes duplicate error with locations in result."""
    prd: dict = {
        "userStories": [
            {"id": "US-5", "sub_project": "makan"},
            {"id": "US-5", "sub_project": "cafe"},
        ]
    }
    result = validate(prd)
    assert result["pass"] is False
    assert result["error_count"] >= 1
    dup_errors = [e for e in result["errors"] if e["type"] == "duplicate_story_id"]
    assert len(dup_errors) == 1
    assert "makan" in dup_errors[0]["locations"]
    assert "cafe" in dup_errors[0]["locations"]


def test_namespace_prefix_violation_detected() -> None:
    """AC2: Story in 'makan' subproject without MAKAN- prefix is a violation."""
    stories: list[dict] = [{"id": "US-999", "sub_project": "makan"}]
    rules = {"makan": "MAKAN-"}
    violations = validate_namespace_prefixes(stories, rules)
    assert len(violations) == 1
    assert violations[0]["story_id"] == "US-999"
    assert violations[0]["required_prefix"] == "MAKAN-"


def test_namespace_prefix_valid_passes() -> None:
    """AC2: Story with correct MAKAN- prefix has no violation."""
    stories: list[dict] = [{"id": "MAKAN-US-001", "sub_project": "makan"}]
    rules = {"makan": "MAKAN-"}
    violations = validate_namespace_prefixes(stories, rules)
    assert violations == []


def test_namespace_suggestion_provided() -> None:
    """AC2: Validation result includes suggested fix for namespace violation."""
    prd: dict = {
        "subProjects": [{"name": "makan", "namespace_prefix": "MAKAN-"}],
        "userStories": [{"id": "US-100", "sub_project": "makan"}],
    }
    result = validate(prd)
    assert result["pass"] is False
    assert len(result["suggestions"]) >= 1
    assert "MAKAN-" in result["suggestions"][0]


def test_json_report_format() -> None:
    """AC3: Result has pass, error_count, errors, suggestions keys."""
    prd: dict = {"userStories": [{"id": "US-1"}, {"id": "US-2"}]}
    result = validate(prd)
    assert "pass" in result
    assert "error_count" in result
    assert "errors" in result
    assert "suggestions" in result


def test_error_count_matches_errors_length() -> None:
    """AC3: error_count equals len(errors)."""
    prd: dict = {
        "userStories": [
            {"id": "US-1", "sub_project": "makan"},
            {"id": "US-1", "sub_project": "cafe"},
        ]
    }
    result = validate(prd)
    assert result["error_count"] == len(result["errors"])


def test_multiple_duplicates_all_reported() -> None:
    """AC1: Multiple different duplicate IDs are all detected."""
    stories: list[dict] = [
        {"id": "US-1", "sub_project": "alpha"},
        {"id": "US-1", "sub_project": "beta"},
        {"id": "US-2", "sub_project": "alpha"},
        {"id": "US-2", "sub_project": "gamma"},
    ]
    dups = detect_duplicates(stories)
    assert len(dups) == 2
    ids = {d["story_id"] for d in dups}
    assert ids == {"US-1", "US-2"}


def test_namespace_rules_inferred_from_subprojects() -> None:
    """AC2: Namespace rules are inferred from prd_dict subProjects field."""
    prd: dict = {
        "subProjects": [{"name": "pelangi", "namespace_prefix": "PEL-"}],
        "userStories": [
            {"id": "WRONG-001", "sub_project": "pelangi"},
        ],
    }
    result = validate(prd)
    assert result["pass"] is False
    prefix_errors = [
        e for e in result["errors"] if e["type"] == "namespace_prefix_violation"
    ]
    assert len(prefix_errors) == 1
    assert prefix_errors[0]["required_prefix"] == "PEL-"
