"""tests/test_dep_type_validator.py — Integration tests for US-729 DependencyTypeValidator.

Covers:
- feature→database  (INVALID)
- infrastructure→feature  (INVALID)
- feature→infrastructure  (VALID)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "phases"))
from validate import DependencyTypeValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stories(*defs: dict) -> list[dict]:  # type: ignore[type-arg]
    """Build a minimal story list from keyword dicts."""
    return list(defs)


# ---------------------------------------------------------------------------
# Invalid pattern 1: feature → database
# ---------------------------------------------------------------------------


class TestFeatureToDatabaseRejected:
    def test_violation_detected(self) -> None:
        stories = _make_stories(
            {"id": "US-123", "type": "feature", "dependencies": ["US-456"]},
            {"id": "US-456", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 1, f"Expected 1 violation, got: {violations}"

    def test_violation_message_contains_ids(self) -> None:
        stories = _make_stories(
            {"id": "US-123", "type": "feature", "dependencies": ["US-456"]},
            {"id": "US-456", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "US-123" in violations[0]
        assert "US-456" in violations[0]

    def test_violation_message_contains_types(self) -> None:
        stories = _make_stories(
            {"id": "US-123", "type": "feature", "dependencies": ["US-456"]},
            {"id": "US-456", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "type: feature" in violations[0]
        assert "type: database" in violations[0]

    def test_violation_message_contains_allowed_list(self) -> None:
        stories = _make_stories(
            {"id": "US-123", "type": "feature", "dependencies": ["US-456"]},
            {"id": "US-456", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "infrastructure" in violations[0]

    def test_violation_error_code(self) -> None:
        stories = _make_stories(
            {"id": "US-123", "type": "feature", "dependencies": ["US-456"]},
            {"id": "US-456", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "DEP_TYPE_FEATURE_DATABASE" in violations[0]


# ---------------------------------------------------------------------------
# Invalid pattern 2: infrastructure → feature
# ---------------------------------------------------------------------------


class TestInfrastructureToFeatureRejected:
    def test_violation_detected(self) -> None:
        stories = _make_stories(
            {"id": "US-200", "type": "infrastructure", "dependencies": ["US-201"]},
            {"id": "US-201", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 1, f"Expected 1 violation, got: {violations}"

    def test_violation_message_format(self) -> None:
        stories = _make_stories(
            {"id": "US-200", "type": "infrastructure", "dependencies": ["US-201"]},
            {"id": "US-201", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        msg = violations[0]
        assert "US-200" in msg
        assert "US-201" in msg
        assert "type: infrastructure" in msg
        assert "type: feature" in msg

    def test_violation_error_code(self) -> None:
        stories = _make_stories(
            {"id": "US-200", "type": "infrastructure", "dependencies": ["US-201"]},
            {"id": "US-201", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "DEP_TYPE_INFRASTRUCTURE_FEATURE" in violations[0]

    def test_allowed_list_is_empty(self) -> None:
        """Infrastructure may not depend on anything — allowed: []."""
        stories = _make_stories(
            {"id": "US-200", "type": "infrastructure", "dependencies": ["US-201"]},
            {"id": "US-201", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        # The allowed list for infrastructure is empty
        assert "[]" in violations[0]


# ---------------------------------------------------------------------------
# Valid pattern: feature → infrastructure
# ---------------------------------------------------------------------------


class TestFeatureToInfrastructurePasses:
    def test_no_violations(self) -> None:
        stories = _make_stories(
            {"id": "US-300", "type": "feature", "dependencies": ["US-301"]},
            {"id": "US-301", "type": "infrastructure"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == [], f"Expected no violations, got: {violations}"

    def test_multiple_valid_deps(self) -> None:
        stories = _make_stories(
            {"id": "US-300", "type": "feature", "dependencies": ["US-301", "US-302"]},
            {"id": "US-301", "type": "infrastructure"},
            {"id": "US-302", "type": "infrastructure"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_type_field_skipped(self) -> None:
        """Stories without a 'type' field are not validated."""
        stories = _make_stories(
            {"id": "US-400", "dependencies": ["US-401"]},
            {"id": "US-401"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == []

    def test_unresolved_dependency_skipped(self) -> None:
        """Unresolved dep IDs are skipped (not a type violation)."""
        stories = _make_stories(
            {"id": "US-500", "type": "feature", "dependencies": ["US-UNKNOWN"]},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == []

    def test_empty_story_list(self) -> None:
        assert DependencyTypeValidator().validate([]) == []

    def test_no_dependencies_field(self) -> None:
        stories = _make_stories({"id": "US-600", "type": "feature"})
        violations = DependencyTypeValidator().validate(stories)
        assert violations == []

    def test_database_to_infrastructure_passes(self) -> None:
        """database → infrastructure is valid per rules."""
        stories = _make_stories(
            {"id": "US-700", "type": "database", "dependencies": ["US-701"]},
            {"id": "US-701", "type": "infrastructure"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == []

    def test_two_violations_collected(self) -> None:
        """Multiple violations are all reported."""
        stories = _make_stories(
            {"id": "US-800", "type": "feature", "dependencies": ["US-801"]},
            {"id": "US-801", "type": "database"},
            {"id": "US-802", "type": "infrastructure", "dependencies": ["US-803"]},
            {"id": "US-803", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 2

    def test_remediation_in_message(self) -> None:
        """Violation message includes remediation guidance."""
        stories = _make_stories(
            {"id": "US-900", "type": "feature", "dependencies": ["US-901"]},
            {"id": "US-901", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "remediation" in violations[0].lower()
