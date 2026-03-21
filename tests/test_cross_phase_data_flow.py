"""tests/test_cross_phase_data_flow.py — US-644: Cross-Phase Data Flow Validation.

Integration tests that validate the SPIRAL R→T→S→M data pipeline by:
1. Asserting each phase's output JSON contains required fields.
2. Detecting schema violations (missing required fields, type mismatches) and
   reporting them with file:function():line context.
3. Creating intentionally malformed phase outputs and asserting they are
   rejected with actionable error messages before the next phase consumes them.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from phase_schemas import (
    PHASE_R_STORY_REQUIRED,
    PHASE_S_STORY_REQUIRED,
    PHASE_T_STORY_REQUIRED,
    SchemaError,
    load_and_validate,
    validate_phase_m_output,
    validate_phase_output,
    validate_phase_r_output,
    validate_phase_s_output,
    validate_phase_t_output,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _research_story(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Research Story Title",
        "description": "Discovered via Phase R web research",
        "_source": "research",
        "acceptanceCriteria": ["AC 1"],
        "estimatedComplexity": "small",
    }
    base.update(overrides)
    return base


def _test_story(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Fix failing test in module X",
        "_source": "test-fix",
        "description": "Regression detected by Phase T",
        "acceptanceCriteria": ["Test passes green"],
        "estimatedComplexity": "small",
    }
    base.update(overrides)
    return base


def _validated_story(**overrides: Any) -> dict[str, Any]:
    """Phase S accepted story — has _source preserved from input."""
    base: dict[str, Any] = {
        "title": "Validated Story",
        "_source": "research",
        "description": "Passed Phase S validation",
        "acceptanceCriteria": ["AC 1"],
        "estimatedComplexity": "small",
    }
    base.update(overrides)
    return base


def _prd_story(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "US-001",
        "title": "Story added by Phase M",
        "passes": False,
        "priority": "high",
        "description": "Merged from research output",
        "acceptanceCriteria": ["AC 1"],
        "dependencies": [],
        "estimatedComplexity": "small",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# AC1 — Required fields: Phase R, T, S outputs
# ---------------------------------------------------------------------------


class TestPhaseROutputSchema:
    """Phase R: _research_output.json must have {stories: [{title, description, ...}]}."""

    def test_valid_research_output_passes(self) -> None:
        """Valid Phase R output with required fields is accepted."""
        data = {"stories": [_research_story()]}
        validate_phase_r_output(data)  # must not raise

    def test_multiple_stories_all_valid(self) -> None:
        data = {"stories": [_research_story(title=f"Story {i}") for i in range(5)]}
        validate_phase_r_output(data)

    def test_empty_stories_list_passes(self) -> None:
        """Empty stories list is valid — Phase R may find nothing."""
        validate_phase_r_output({"stories": []})

    def test_missing_title_raises_schema_error(self) -> None:
        story = _research_story()
        del story["title"]
        with pytest.raises(SchemaError, match="title"):
            validate_phase_r_output({"stories": [story]})

    def test_missing_description_raises_schema_error(self) -> None:
        story = _research_story()
        del story["description"]
        with pytest.raises(SchemaError, match="description"):
            validate_phase_r_output({"stories": [story]})

    def test_missing_stories_key_raises_schema_error(self) -> None:
        with pytest.raises(SchemaError, match="stories"):
            validate_phase_r_output({"candidates": []})

    def test_stories_not_list_raises_schema_error(self) -> None:
        with pytest.raises(SchemaError, match="list"):
            validate_phase_r_output({"stories": "not a list"})

    def test_required_fields_constant_correct(self) -> None:
        assert "title" in PHASE_R_STORY_REQUIRED
        assert "description" in PHASE_R_STORY_REQUIRED


class TestPhaseTOutputSchema:
    """Phase T: _test_stories_output.json must have {stories: [{title, _source, ...}]}."""

    def test_valid_test_stories_output_passes(self) -> None:
        data = {"stories": [_test_story()]}
        validate_phase_t_output(data)

    def test_missing_title_raises(self) -> None:
        story = _test_story()
        del story["title"]
        with pytest.raises(SchemaError, match="title"):
            validate_phase_t_output({"stories": [story]})

    def test_missing_source_raises(self) -> None:
        story = _test_story()
        del story["_source"]
        with pytest.raises(SchemaError, match="_source"):
            validate_phase_t_output({"stories": [story]})

    def test_empty_stories_passes(self) -> None:
        validate_phase_t_output({"stories": []})

    def test_required_fields_constant_correct(self) -> None:
        assert "_source" in PHASE_T_STORY_REQUIRED
        assert "title" in PHASE_T_STORY_REQUIRED


class TestPhaseSOutputSchema:
    """Phase S: _validated_stories.json must have {stories: [{title, _source, ...}]}."""

    def test_valid_validated_output_passes(self) -> None:
        data = {"stories": [_validated_story()]}
        validate_phase_s_output(data)

    def test_missing_title_raises(self) -> None:
        story = _validated_story()
        del story["title"]
        with pytest.raises(SchemaError, match="title"):
            validate_phase_s_output({"stories": [story]})

    def test_missing_source_raises(self) -> None:
        story = _validated_story()
        del story["_source"]
        with pytest.raises(SchemaError, match="_source"):
            validate_phase_s_output({"stories": [story]})

    def test_empty_stories_passes(self) -> None:
        validate_phase_s_output({"stories": []})

    def test_required_fields_constant_correct(self) -> None:
        assert "_source" in PHASE_S_STORY_REQUIRED
        assert "title" in PHASE_S_STORY_REQUIRED


# ---------------------------------------------------------------------------
# AC2 — Schema violations report file:function():line context
# ---------------------------------------------------------------------------


class TestSchemaViolationContext:
    """Schema errors include file:function():line in their message."""

    def test_phase_r_violation_includes_context(self) -> None:
        """Error for Phase R violation includes location context."""
        story = _research_story()
        del story["title"]
        with pytest.raises(SchemaError) as exc_info:
            validate_phase_r_output({"stories": [story]})
        msg = str(exc_info.value)
        # Must contain a colon-separated location string (file:func():line)
        assert ":" in msg, f"Error message has no location context: {msg!r}"
        assert "title" in msg, f"Error message does not name the missing field: {msg!r}"

    def test_phase_s_violation_includes_context(self) -> None:
        story = _validated_story()
        del story["_source"]
        with pytest.raises(SchemaError) as exc_info:
            validate_phase_s_output({"stories": [story]})
        msg = str(exc_info.value)
        assert ":" in msg
        assert "_source" in msg

    def test_phase_m_violation_includes_context(self) -> None:
        prd = {"userStories": [{"title": "Missing id and passes"}]}
        with pytest.raises(SchemaError) as exc_info:
            validate_phase_m_output(prd)
        msg = str(exc_info.value)
        assert ":" in msg
        assert "id" in msg or "passes" in msg

    def test_error_message_names_missing_field(self) -> None:
        """Error message must name the specific missing field."""
        for field in PHASE_R_STORY_REQUIRED:
            story = _research_story()
            del story[field]
            with pytest.raises(SchemaError) as exc_info:
                validate_phase_r_output({"stories": [story]})
            assert field in str(exc_info.value), f"Error message should name field '{field}': {exc_info.value!r}"

    def test_error_message_names_story_index(self) -> None:
        """Error message includes story index to locate the bad story."""
        stories = [_research_story(), _research_story()]
        del stories[1]["description"]  # second story is bad
        with pytest.raises(SchemaError) as exc_info:
            validate_phase_r_output({"stories": stories})
        assert "[1]" in str(exc_info.value), f"Error message should reference story index 1: {exc_info.value!r}"

    def test_wrong_type_for_stories_key_reports_context(self) -> None:
        with pytest.raises(SchemaError) as exc_info:
            validate_phase_r_output({"stories": 42})
        msg = str(exc_info.value)
        assert ":" in msg
        assert "list" in msg.lower()


# ---------------------------------------------------------------------------
# AC3 — Intentionally malformed outputs are rejected with actionable message
# ---------------------------------------------------------------------------


class TestMalformedOutputRejection:
    """Malformed phase outputs are detected before consumption by the next phase."""

    def test_malformed_phase_r_missing_description_rejected(self, tmp_path: Path) -> None:
        """Phase R output missing 'description' is rejected before Phase S consumes it."""
        # Intentionally produce a bad Phase R output
        bad_r_output = {
            "stories": [
                {
                    "title": "Story without description",
                    "_source": "research",
                    # 'description' intentionally omitted
                }
            ]
        }
        out_file = tmp_path / "_research_output.json"
        _write_json(out_file, bad_r_output)

        # Phase S would read this file — validator must reject it before handoff
        with pytest.raises(SchemaError) as exc_info:
            load_and_validate(out_file, "R")

        err = str(exc_info.value)
        assert "description" in err, f"Error should name missing field: {err!r}"

    def test_malformed_phase_t_missing_source_rejected(self, tmp_path: Path) -> None:
        """Phase T output missing '_source' is rejected before Phase S consumes it."""
        bad_t_output = {
            "stories": [
                {
                    "title": "Test story without _source",
                    # '_source' intentionally omitted
                }
            ]
        }
        out_file = tmp_path / "_test_stories_output.json"
        _write_json(out_file, bad_t_output)

        with pytest.raises(SchemaError) as exc_info:
            load_and_validate(out_file, "T")

        assert "_source" in str(exc_info.value)

    def test_malformed_phase_s_missing_source_rejected(self, tmp_path: Path) -> None:
        """Phase S output missing '_source' is caught before Phase M consumes it."""
        bad_s_output = {
            "stories": [
                {
                    "title": "Validated story without _source",
                    # '_source' intentionally omitted
                }
            ]
        }
        out_file = tmp_path / "_validated_stories.json"
        _write_json(out_file, bad_s_output)

        with pytest.raises(SchemaError) as exc_info:
            load_and_validate(out_file, "S")

        assert "_source" in str(exc_info.value)

    def test_malformed_prd_missing_passes_rejected(self, tmp_path: Path) -> None:
        """prd.json story missing 'passes' is caught by Phase M schema check."""
        bad_prd = {
            "userStories": [
                {
                    "id": "US-999",
                    "title": "Story without passes",
                    # 'passes' intentionally omitted
                }
            ]
        }
        out_file = tmp_path / "prd.json"
        _write_json(out_file, bad_prd)

        with pytest.raises(SchemaError) as exc_info:
            load_and_validate(out_file, "M")

        assert "passes" in str(exc_info.value)

    def test_invalid_json_file_raises_schema_error(self, tmp_path: Path) -> None:
        """A non-JSON file raises SchemaError (not raw json.JSONDecodeError)."""
        bad_file = tmp_path / "_research_output.json"
        bad_file.write_text("this is not json", encoding="utf-8")

        with pytest.raises(SchemaError, match="cannot load"):
            load_and_validate(bad_file, "R")

    def test_missing_file_raises_schema_error(self, tmp_path: Path) -> None:
        """A missing file raises SchemaError with informative message."""
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(SchemaError, match="cannot load"):
            load_and_validate(missing, "R")


# ---------------------------------------------------------------------------
# Cross-phase pipeline simulation: R → T → S
# ---------------------------------------------------------------------------


class TestCrossPhaseDataFlow:
    """Simulate the R→T→S pipeline and assert schemas are consistent."""

    def test_r_output_feeds_s_without_error(self, tmp_path: Path) -> None:
        """Phase R stories can flow directly into Phase S schema validation."""
        r_output = {"stories": [_research_story(), _research_story(title="Story 2")]}
        r_file = tmp_path / "_research_output.json"
        _write_json(r_file, r_output)

        # Validate Phase R
        r_data = load_and_validate(r_file, "R")
        assert len(r_data["stories"]) == 2

        # Simulate Phase S output (stories that passed validation)
        s_output = {"stories": [{**s, "_source": s.get("_source", "research")} for s in r_data["stories"]]}
        s_file = tmp_path / "_validated_stories.json"
        _write_json(s_file, s_output)

        # Validate Phase S
        s_data = load_and_validate(s_file, "S")
        assert len(s_data["stories"]) == 2
        assert all("_source" in st for st in s_data["stories"])

    def test_t_output_feeds_s_without_error(self, tmp_path: Path) -> None:
        """Phase T stories can flow into Phase S schema validation."""
        t_output = {"stories": [_test_story(), _test_story(title="Fix test 2")]}
        t_file = tmp_path / "_test_stories_output.json"
        _write_json(t_file, t_output)

        t_data = load_and_validate(t_file, "T")
        assert len(t_data["stories"]) == 2

        # Simulate Phase S accepting test stories
        s_output = {"stories": list(t_data["stories"])}
        s_file = tmp_path / "_validated_stories.json"
        _write_json(s_file, s_output)

        s_data = load_and_validate(s_file, "S")
        assert all(st["_source"] == "test-fix" for st in s_data["stories"])

    def test_s_output_feeds_m_prd_without_error(self, tmp_path: Path) -> None:
        """Phase S validated stories flow into prd.json (Phase M) schema validation."""
        # Phase M merges validated stories into prd.json
        prd = {
            "userStories": [
                _prd_story(id="US-001", title="Story from Phase S"),
                _prd_story(id="US-002", title="Story 2 from Phase S"),
            ]
        }
        prd_file = tmp_path / "prd.json"
        _write_json(prd_file, prd)

        prd_data = load_and_validate(prd_file, "M")
        assert len(prd_data["userStories"]) == 2
        assert all("passes" in st for st in prd_data["userStories"])

    def test_bad_r_output_blocked_before_s(self, tmp_path: Path) -> None:
        """Malformed Phase R output is blocked before it can corrupt Phase S input."""
        # Intentionally missing 'description'
        bad_r = {"stories": [{"title": "No description", "_source": "research"}]}
        r_file = tmp_path / "_research_output.json"
        _write_json(r_file, bad_r)

        with pytest.raises(SchemaError) as exc_info:
            load_and_validate(r_file, "R")

        # Error must be actionable: name the field and location
        err = str(exc_info.value)
        assert "description" in err
        assert ":" in err  # contains file:func():line

    def test_full_pipeline_r_t_s_m_valid(self, tmp_path: Path) -> None:
        """Full R→T→S→M pipeline with valid data passes all schema checks."""
        # Phase R output
        r_file = tmp_path / "_research_output.json"
        _write_json(r_file, {"stories": [_research_story(title=f"R Story {i}") for i in range(3)]})
        r_data = load_and_validate(r_file, "R")

        # Phase T output
        t_file = tmp_path / "_test_stories_output.json"
        _write_json(t_file, {"stories": [_test_story(title=f"T Story {i}") for i in range(2)]})
        t_data = load_and_validate(t_file, "T")

        # Phase S output (merge of R + T validated candidates)
        s_stories = list(r_data["stories"]) + list(t_data["stories"])
        s_file = tmp_path / "_validated_stories.json"
        _write_json(s_file, {"stories": s_stories})
        s_data = load_and_validate(s_file, "S")

        # Phase M output (prd.json patch)
        prd_stories = [_prd_story(id=f"US-{100 + i}", title=st["title"]) for i, st in enumerate(s_data["stories"])]
        prd_file = tmp_path / "prd.json"
        _write_json(prd_file, {"userStories": prd_stories})
        prd_data = load_and_validate(prd_file, "M")

        assert len(prd_data["userStories"]) == 5  # 3 from R + 2 from T


# ---------------------------------------------------------------------------
# validate_phase_output dispatch
# ---------------------------------------------------------------------------


class TestValidatePhaseOutputDispatch:
    """validate_phase_output() dispatches correctly to per-phase validators."""

    def test_dispatch_r(self) -> None:
        validate_phase_output("R", {"stories": [_research_story()]})

    def test_dispatch_t(self) -> None:
        validate_phase_output("T", {"stories": [_test_story()]})

    def test_dispatch_s(self) -> None:
        validate_phase_output("S", {"stories": [_validated_story()]})

    def test_dispatch_m(self) -> None:
        validate_phase_output("M", {"userStories": [_prd_story()]})

    def test_dispatch_case_insensitive(self) -> None:
        validate_phase_output("r", {"stories": [_research_story()]})
        validate_phase_output("s", {"stories": [_validated_story()]})

    def test_unknown_phase_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown phase"):
            validate_phase_output("X", {})

    def test_dispatch_r_missing_field_raises_schema_error(self) -> None:
        bad = {"stories": [{"_source": "research"}]}  # missing title, description
        with pytest.raises(SchemaError):
            validate_phase_output("R", bad)
