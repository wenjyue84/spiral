"""tests/test_dep_type_validator.py — Integration tests for US-729 DependencyTypeValidator.

Covers:
- feature→database  (INVALID)
- infrastructure→feature  (INVALID)
- feature→infrastructure  (VALID)
"""

import sys
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Regression tests for US-729 (DependencyTypeValidator)
# ---------------------------------------------------------------------------


class TestUS729RegressionDependencyValidation:
    """Regression tests for US-729 to guard against future breakage.

    These tests verify the core observable behavior of the dependency
    type validator and would fail if the feature were removed or broken.
    Run with: uv run pytest tests/ -k us_729 -v
    """

    def test_us_729_constraint_enforcement_feature_to_infrastructure(self) -> None:
        """US-729: feature → infrastructure is the valid constraint."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "infrastructure"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == [], "feature → infrastructure should be valid per US-729"

    def test_us_729_constraint_enforcement_feature_to_database_invalid(self) -> None:
        """US-729: feature → database constraint violation must be detected."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 1, "feature → database should produce 1 violation"
        assert "US-1" in violations[0], "Violation must identify source story"
        assert "US-2" in violations[0], "Violation must identify target story"

    def test_us_729_constraint_enforcement_database_to_infrastructure(self) -> None:
        """US-729: database → infrastructure is the valid constraint."""
        stories = _make_stories(
            {"id": "US-1", "type": "database", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "infrastructure"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert violations == [], "database → infrastructure should be valid per US-729"

    def test_us_729_constraint_enforcement_infrastructure_no_dependencies(self) -> None:
        """US-729: infrastructure stories may not depend on anything."""
        stories = _make_stories(
            {"id": "US-1", "type": "infrastructure", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 1, "infrastructure → feature should produce violation"

    def test_us_729_error_message_includes_rule_id(self) -> None:
        """US-729: Violation message must include stable rule ID for automation."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "DEP_TYPE_FEATURE_DATABASE" in violations[0], (
            "Error message must include rule ID for tooling integration"
        )

    def test_us_729_error_message_includes_remediation(self) -> None:
        """US-729: Violation message must include remediation guidance."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "remediation" in violations[0].lower(), "Error message must guide user toward fix"

    def test_us_729_error_message_includes_allowed_list(self) -> None:
        """US-729: Violation message must show allowed target types."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert "infrastructure" in violations[0], "Error message must list allowed target types"

    def test_us_729_batch_validation_collects_all_violations(self) -> None:
        """US-729: Validator must report all violations, not stop on first."""
        stories = _make_stories(
            {"id": "US-1", "type": "feature", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
            {"id": "US-3", "type": "infrastructure", "dependencies": ["US-4"]},
            {"id": "US-4", "type": "feature"},
        )
        violations = DependencyTypeValidator().validate(stories)
        assert len(violations) == 2, "Validator must report all constraint violations in one call"

    def test_us_729_custom_rules_override_defaults(self) -> None:
        """US-729: Validator must accept custom rules for extensibility."""
        custom_rules = {"feature": [], "infrastructure": ["database"]}
        stories = _make_stories(
            {"id": "US-1", "type": "infrastructure", "dependencies": ["US-2"]},
            {"id": "US-2", "type": "database"},
        )
        violations = DependencyTypeValidator(rules=custom_rules).validate(stories)
        assert violations == [], "Custom rules should override defaults for flexible validation"
