"""Property-based tests for prd_schema.py validation."""
import pytest
from hypothesis import given, settings, assume
from conftest import valid_prd, invalid_prd_missing_field, prd_with_duplicate_ids, prd_with_dangling_dep
from prd_schema import validate_prd


class TestValidPrd:
    """Property: valid PRDs always pass validation."""

    @given(prd=valid_prd())
    @settings(max_examples=200)
    def test_valid_prd_has_no_errors(self, prd):
        errors = validate_prd(prd)
        assert errors == [], f"Valid PRD should have no errors: {errors}"

    @given(prd=valid_prd(min_stories=0, max_stories=0))
    def test_empty_stories_is_valid(self, prd):
        errors = validate_prd(prd)
        assert errors == []


class TestInvalidPrd:
    """Property: known-invalid PRDs always fail validation."""

    @given(data=invalid_prd_missing_field())
    @settings(max_examples=100)
    def test_missing_required_field_detected(self, data):
        prd, field = data
        errors = validate_prd(prd)
        assert len(errors) > 0, f"Missing '{field}' should be detected"
        assert any(field in e for e in errors)

    @given(prd=prd_with_duplicate_ids())
    @settings(max_examples=100)
    def test_duplicate_ids_detected(self, prd):
        errors = validate_prd(prd)
        assert any("duplicate" in e.lower() for e in errors)

    @given(prd=prd_with_dangling_dep())
    @settings(max_examples=100)
    def test_dangling_dependency_detected(self, prd):
        errors = validate_prd(prd)
        assert any("not found" in e for e in errors)


class TestSchemaTypes:
    """Property: type violations are always caught."""

    @given(prd=valid_prd())
    def test_passes_not_bool_detected(self, prd):
        assume(len(prd["userStories"]) > 0)
        prd["userStories"][0]["passes"] = "yes"
        errors = validate_prd(prd)
        assert any("boolean" in e.lower() for e in errors)

    @given(prd=valid_prd())
    def test_invalid_priority_detected(self, prd):
        assume(len(prd["userStories"]) > 0)
        prd["userStories"][0]["priority"] = "urgent"
        errors = validate_prd(prd)
        assert any("urgent" in e for e in errors)

    @given(prd=valid_prd())
    def test_invalid_complexity_detected(self, prd):
        assume(len(prd["userStories"]) > 0)
        prd["userStories"][0]["estimatedComplexity"] = "huge"
        errors = validate_prd(prd)
        assert any("huge" in e for e in errors)

    def test_root_not_dict(self):
        errors = validate_prd([])
        assert any("object" in e.lower() for e in errors)

    def test_stories_not_list(self):
        errors = validate_prd({"productName": "X", "branchName": "main", "userStories": "nope"})
        assert any("list" in e.lower() for e in errors)


class TestSchemaIdempotency:
    """Property: validation is pure — same input always gives same output."""

    @given(prd=valid_prd())
    def test_validation_is_deterministic(self, prd):
        errors1 = validate_prd(prd)
        errors2 = validate_prd(prd)
        assert errors1 == errors2
