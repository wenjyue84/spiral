"""tests/test_lint_prd.py — Tests for lib/prd/lint_prd.py (US-639).

5 fixtures:
  1. valid                — clean PRD, no errors
  2. duplicate_ids        — two stories share an ID
  3. circular_deps        — US-001 → US-002 → US-001
  4. missing_fields       — stories missing required fields
  5. naming_violations    — IDs that don't match (US|UT)-NNN
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from prd.lint_prd import lint_prd

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_PRD: dict = {
    "productName": "Test Product",
    "branchName": "main",
    "userStories": [
        {
            "id": "US-001",
            "title": "Story one",
            "passes": False,
            "priority": "high",
            "description": "desc",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "US-002",
            "title": "Story two",
            "passes": False,
            "priority": "medium",
            "description": "desc",
            "acceptanceCriteria": ["AC1"],
            "dependencies": ["US-001"],
        },
    ],
}

DUPLICATE_IDS_PRD: dict = {
    "productName": "Test Product",
    "branchName": "main",
    "userStories": [
        {
            "id": "US-001",
            "title": "First story",
            "passes": False,
            "priority": "high",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "US-001",  # duplicate
            "title": "Duplicate story",
            "passes": False,
            "priority": "low",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "US-002",
            "title": "Unique story",
            "passes": False,
            "priority": "medium",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
    ],
}

CIRCULAR_DEPS_PRD: dict = {
    "productName": "Test Product",
    "branchName": "main",
    "userStories": [
        {
            "id": "US-001",
            "title": "Story A",
            "passes": False,
            "priority": "high",
            "acceptanceCriteria": ["AC1"],
            "dependencies": ["US-002"],
        },
        {
            "id": "US-002",
            "title": "Story B",
            "passes": False,
            "priority": "high",
            "acceptanceCriteria": ["AC1"],
            "dependencies": ["US-001"],
        },
    ],
}

MISSING_FIELDS_PRD: dict = {
    "productName": "Test Product",
    "branchName": "main",
    "userStories": [
        {
            "id": "US-010",
            # missing: title, passes, acceptanceCriteria, dependencies
            "priority": "high",
        },
        {
            "id": "US-011",
            "title": "Story with missing AC",
            "passes": False,
            "priority": "low",
            # missing: acceptanceCriteria, dependencies
        },
    ],
}

NAMING_VIOLATIONS_PRD: dict = {
    "productName": "Test Product",
    "branchName": "main",
    "userStories": [
        {
            "id": "US001",  # missing hyphen
            "title": "Bad naming one",
            "passes": False,
            "priority": "high",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "STORY-42",  # wrong prefix
            "title": "Bad naming two",
            "passes": False,
            "priority": "medium",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "US-1",  # too few digits
            "title": "Bad naming three",
            "passes": False,
            "priority": "low",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
        {
            "id": "US-999",  # valid — should NOT appear in errors
            "title": "Good naming",
            "passes": False,
            "priority": "low",
            "acceptanceCriteria": ["AC1"],
            "dependencies": [],
        },
    ],
}


# ── Test: fixture 1 — valid PRD ───────────────────────────────────────────────


def test_valid_prd_returns_no_errors() -> None:
    report = lint_prd(VALID_PRD)
    assert report["valid"] is True
    assert report["errors"] == []


# ── Test: fixture 2 — duplicate IDs ──────────────────────────────────────────


def test_duplicate_ids_detected() -> None:
    report = lint_prd(DUPLICATE_IDS_PRD)
    assert report["valid"] is False
    dup_errors = [e for e in report["errors"] if e["type"] == "duplicate_id"]
    assert len(dup_errors) == 1
    assert dup_errors[0]["story_id"] == "US-001"


# ── Test: fixture 3 — circular dependencies ───────────────────────────────────


def test_circular_deps_detected() -> None:
    report = lint_prd(CIRCULAR_DEPS_PRD)
    assert report["valid"] is False
    circ_errors = [e for e in report["errors"] if e["type"] == "circular_dep"]
    assert len(circ_errors) == 1
    cycle = circ_errors[0]["cycle"]
    assert isinstance(cycle, list)
    # cycle must be non-empty and loop back (first == last)
    assert len(cycle) >= 2
    assert cycle[0] == cycle[-1]
    # cycle members must include US-001 and US-002
    cycle_members = set(cycle)
    assert "US-001" in cycle_members
    assert "US-002" in cycle_members


# ── Test: fixture 4 — missing required fields ─────────────────────────────────


def test_missing_fields_detected() -> None:
    report = lint_prd(MISSING_FIELDS_PRD)
    assert report["valid"] is False
    schema_errors = [e for e in report["errors"] if e["type"] == "schema"]
    assert len(schema_errors) > 0
    messages = [e["message"] for e in schema_errors]
    # US-010 is missing title, passes, acceptanceCriteria, dependencies
    assert any("US-010" in m and "title" in m for m in messages)
    assert any("US-010" in m and "acceptanceCriteria" in m for m in messages)
    # US-011 is missing acceptanceCriteria, dependencies
    assert any("US-011" in m and "acceptanceCriteria" in m for m in messages)
    assert any("US-011" in m and "dependencies" in m for m in messages)


# ── Test: fixture 5 — naming violations ──────────────────────────────────────


def test_naming_violations_detected() -> None:
    report = lint_prd(NAMING_VIOLATIONS_PRD)
    assert report["valid"] is False
    naming_errors = [e for e in report["errors"] if e["type"] == "naming"]
    violating_ids = {e["story_id"] for e in naming_errors}
    assert "US001" in violating_ids
    assert "STORY-42" in violating_ids
    assert "US-1" in violating_ids
    # US-999 is valid and must NOT appear
    assert "US-999" not in violating_ids


# ── Test: output structure matches AC spec ────────────────────────────────────


def test_output_structure() -> None:
    """Report dict always has 'valid' (bool) and 'errors' (list) keys."""
    report = lint_prd(VALID_PRD)
    assert "valid" in report
    assert "errors" in report
    assert isinstance(report["valid"], bool)
    assert isinstance(report["errors"], list)


def test_error_objects_have_type_field() -> None:
    """Every error object must have a 'type' field."""
    report = lint_prd(DUPLICATE_IDS_PRD)
    for err in report["errors"]:
        assert "type" in err


def test_duplicate_id_error_has_story_id_field() -> None:
    report = lint_prd(DUPLICATE_IDS_PRD)
    dup_errors = [e for e in report["errors"] if e["type"] == "duplicate_id"]
    assert all("story_id" in e for e in dup_errors)


def test_circular_dep_error_has_cycle_field() -> None:
    report = lint_prd(CIRCULAR_DEPS_PRD)
    circ_errors = [e for e in report["errors"] if e["type"] == "circular_dep"]
    assert all("cycle" in e for e in circ_errors)


def test_schema_error_has_message_field() -> None:
    report = lint_prd(MISSING_FIELDS_PRD)
    schema_errors = [e for e in report["errors"] if e["type"] == "schema"]
    assert all("message" in e for e in schema_errors)
