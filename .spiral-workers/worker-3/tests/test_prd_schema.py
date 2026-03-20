"""Property-based tests for prd_schema.py validation."""

import json
import os
import time

import pytest
from conftest import invalid_prd_missing_field, prd_with_dangling_dep, prd_with_duplicate_ids, valid_prd
from hypothesis import HealthCheck, assume, given, settings
from prd_schema import validate_jsonschema, validate_prd


class TestValidPrd:
    """Property: valid PRDs always pass validation."""

    @given(prd=valid_prd())
    @settings(suppress_health_check=[HealthCheck.too_slow])
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
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_missing_required_field_detected(self, data):
        prd, field = data
        errors = validate_prd(prd)
        assert len(errors) > 0, f"Missing '{field}' should be detected"
        assert any(field in e for e in errors)

    @given(prd=prd_with_duplicate_ids())
    @settings(suppress_health_check=[HealthCheck.too_slow])
    def test_duplicate_ids_detected(self, prd):
        errors = validate_prd(prd)
        assert any("duplicate" in e.lower() for e in errors)

    @given(prd=prd_with_dangling_dep())
    @settings(suppress_health_check=[HealthCheck.too_slow])
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


class TestSchemaVersion:
    """Tests for schemaVersion validation."""

    def test_valid_schema_version(self):
        prd = {"productName": "X", "branchName": "main", "schemaVersion": 1, "userStories": []}
        errors = validate_prd(prd)
        assert errors == []

    def test_non_integer_schema_version(self):
        prd = {"productName": "X", "branchName": "main", "schemaVersion": "1", "userStories": []}
        errors = validate_prd(prd)
        assert any("schemaVersion" in e and "integer" in e for e in errors)

    def test_negative_schema_version(self):
        prd = {"productName": "X", "branchName": "main", "schemaVersion": 0, "userStories": []}
        errors = validate_prd(prd)
        assert any("schemaVersion" in e for e in errors)

    def test_missing_schema_version_warns_but_no_error(self, capsys):
        prd = {"productName": "X", "branchName": "main", "userStories": []}
        errors = validate_prd(prd)
        assert errors == []
        captured = capsys.readouterr()
        assert "schemaVersion" in captured.err


class TestSchemaIdempotency:
    """Property: validation is pure — same input always gives same output."""

    @given(prd=valid_prd())
    def test_validation_is_deterministic(self, prd):
        errors1 = validate_prd(prd)
        errors2 = validate_prd(prd)
        assert errors1 == errors2


class TestJsonSchemaRsBenchmark:
    """Benchmark jsonschema-rs validation on prd.json."""

    @pytest.fixture()
    def prd_and_schema(self):
        """Load the real prd.json and schema for benchmarking."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prd_path = os.path.join(repo_root, "prd.json")
        schema_path = os.path.join(repo_root, "prd.schema.json")
        if not os.path.isfile(prd_path) or not os.path.isfile(schema_path):
            pytest.skip("prd.json or prd.schema.json not found")
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        return prd, schema, schema_path

    def test_jsonschema_rs_validates_prd(self, prd_and_schema):
        """jsonschema-rs validates the real prd.json without crashing."""
        prd, _schema, schema_path = prd_and_schema
        errors = validate_jsonschema(prd, schema_path)
        # We just check it runs and returns a list (may have known schema errors)
        assert isinstance(errors, list)

    def test_jsonschema_rs_benchmark(self, prd_and_schema):
        """Benchmark: time 100 validation runs on the real prd.json."""
        import jsonschema_rs

        prd, schema, _schema_path = prd_and_schema
        validator = jsonschema_rs.validator_for(schema)
        n_runs = 100

        start = time.perf_counter()
        for _ in range(n_runs):
            list(validator.iter_errors(prd))
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / n_runs) * 1000
        print(f"\njsonschema-rs: {n_runs} runs in {elapsed:.3f}s (avg {avg_ms:.2f}ms per validation)")
        # Rust-backed validator should complete each run in under 100ms
        assert avg_ms < 100, f"Validation too slow: {avg_ms:.2f}ms per run"
