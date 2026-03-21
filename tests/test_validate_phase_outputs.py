"""Tests for lib/spiral/validate_phase_outputs.py — US-661.

Acceptance criteria:
1. lib/spiral/validate_phase_outputs.py with schema matchers for each phase.
2. CLI validates .spiral/ output files against lib/schemas/phase_*.schema.json.
3. JSON format {valid, phase, errors: [{file, line, expected, got}]} and --format text.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "spiral"))

from validate_phase_outputs import (
    VALID_PHASES,
    format_text_report,
    validate_phase,
    validate_phases,
)

# Real schema directory (already committed)
SCHEMA_DIR = Path(__file__).parent.parent / "lib" / "schemas"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class TestValidatePhaseR:
    """Phase R (_research_output.json) validation."""

    def test_valid_research_output(self, tmp_path: Path) -> None:
        """Valid _research_output.json passes."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            spiral_dir / "_research_output.json",
            {
                "stories": [
                    {
                        "title": "Test story",
                        "description": "A description",
                        "acceptanceCriteria": ["AC1"],
                        "priority": "medium",
                    }
                ]
            },
        )
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is True
        assert result["phase"] == "R"
        assert result["errors"] == []

    def test_empty_stories_array_is_valid(self, tmp_path: Path) -> None:
        """Empty stories array is valid."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(spiral_dir / "_research_output.json", {"stories": []})
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is True

    def test_missing_stories_key(self, tmp_path: Path) -> None:
        """Missing 'stories' key returns error."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(spiral_dir / "_research_output.json", {"other": []})
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False
        assert any("stories" in err["expected"] for err in result["errors"])

    def test_stories_not_array(self, tmp_path: Path) -> None:
        """stories must be array."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(spiral_dir / "_research_output.json", {"stories": "not-array"})
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False
        assert any("array" in err["expected"] for err in result["errors"])

    def test_story_missing_required_field(self, tmp_path: Path) -> None:
        """Story item missing required field returns error."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            spiral_dir / "_research_output.json",
            {
                "stories": [
                    {
                        "title": "Only title",
                        # missing description, acceptanceCriteria, priority
                    }
                ]
            },
        )
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        """Missing phase output file returns file-missing error."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False
        assert any("missing" in err["got"] for err in result["errors"])

    def test_malformed_json_returns_error(self, tmp_path: Path) -> None:
        """Malformed JSON returns parse error."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()
        (spiral_dir / "_research_output.json").write_text("{not valid", encoding="utf-8")
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False
        assert any("valid JSON" in err["expected"] for err in result["errors"])

    def test_error_format_has_required_keys(self, tmp_path: Path) -> None:
        """Each error dict has file, line, expected, got keys."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(spiral_dir / "_research_output.json", {"wrong": 1})
        result = validate_phase("R", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False
        for err in result["errors"]:
            assert "file" in err
            assert "line" in err
            assert "expected" in err
            assert "got" in err


class TestValidatePhaseT:
    """Phase T (_test_stories_output.json) validation."""

    def test_valid_test_stories_output(self, tmp_path: Path) -> None:
        """Valid _test_stories_output.json passes."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            spiral_dir / "_test_stories_output.json",
            {
                "stories": [
                    {
                        "title": "Regression test story",
                        "description": "Desc",
                        "acceptanceCriteria": ["Test passes"],
                        "priority": "high",
                    }
                ]
            },
        )
        result = validate_phase("T", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is True

    def test_missing_file(self, tmp_path: Path) -> None:
        """Missing _test_stories_output.json returns error."""
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()
        result = validate_phase("T", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False


class TestValidatePhaseS:
    """Phase S (_validated_stories.json) validation."""

    def test_valid_validated_stories(self, tmp_path: Path) -> None:
        """Valid _validated_stories.json passes."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            spiral_dir / "_validated_stories.json",
            {
                "stories": [
                    {
                        "title": "Validated story",
                        "description": "Desc",
                        "acceptanceCriteria": ["AC1"],
                        "priority": "low",
                    }
                ]
            },
        )
        result = validate_phase("S", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is True


class TestValidatePhaseM:
    """Phase M (prd.json) validation."""

    def test_valid_prd_json(self, tmp_path: Path) -> None:
        """Valid prd.json passes."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            tmp_path / "prd.json",
            {"userStories": [{"id": "US-001", "title": "Test story", "passes": False}]},
        )
        result = validate_phase("M", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is True

    def test_prd_missing_user_stories(self, tmp_path: Path) -> None:
        """prd.json missing 'userStories' returns error."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(tmp_path / "prd.json", {"stories": []})
        result = validate_phase("M", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False

    def test_story_passes_must_be_bool(self, tmp_path: Path) -> None:
        """Story 'passes' field must be boolean."""
        spiral_dir = tmp_path / ".spiral"
        _write_json(
            tmp_path / "prd.json",
            {"userStories": [{"id": "US-001", "title": "Test", "passes": "yes"}]},
        )
        result = validate_phase("M", spiral_dir=spiral_dir, schema_dir=SCHEMA_DIR)
        assert result["valid"] is False


class TestValidatePhases:
    """validate_phases() validates multiple phases at once."""

    def test_default_validates_all_phases(self, tmp_path: Path) -> None:
        """Default call validates all phases (R, T, S, M)."""
        results = validate_phases(phases=list(VALID_PHASES), spiral_dir=tmp_path, schema_dir=SCHEMA_DIR)
        assert len(results) == len(VALID_PHASES)
        returned_phases = {r["phase"] for r in results}
        assert returned_phases == set(VALID_PHASES)

    def test_specific_subset(self, tmp_path: Path) -> None:
        """Validate only specified phases."""
        results = validate_phases(phases=["R", "T"], spiral_dir=tmp_path, schema_dir=SCHEMA_DIR)
        assert len(results) == 2
        returned_phases = {r["phase"] for r in results}
        assert returned_phases == {"R", "T"}

    def test_invalid_phase_letter(self, tmp_path: Path) -> None:
        """Unknown phase returns validation error."""
        results = validate_phases(phases=["Z"], spiral_dir=tmp_path, schema_dir=SCHEMA_DIR)
        assert len(results) == 1
        assert results[0]["valid"] is False

    def test_result_has_valid_phase_errors_keys(self, tmp_path: Path) -> None:
        """Each result has valid, phase, errors keys."""
        results = validate_phases(phases=["R"], spiral_dir=tmp_path, schema_dir=SCHEMA_DIR)
        for result in results:
            assert "valid" in result
            assert "phase" in result
            assert "errors" in result


class TestFormatTextReport:
    """format_text_report() produces human-readable output."""

    def test_all_valid(self) -> None:
        """All valid phases show [ok]."""
        results = [
            {"valid": True, "phase": "R", "errors": []},
            {"valid": True, "phase": "T", "errors": []},
        ]
        text = format_text_report(results)
        assert "[ok] Phase R" in text
        assert "[ok] Phase T" in text
        assert "fail" not in text

    def test_with_errors(self) -> None:
        """Errors listed under failing phase."""
        results = [
            {
                "valid": False,
                "phase": "R",
                "errors": [
                    {
                        "file": "_research_output.json",
                        "line": 0,
                        "expected": "field 'stories' at $",
                        "got": "missing",
                    }
                ],
            }
        ]
        text = format_text_report(results)
        assert "[fail] Phase R" in text
        assert "stories" in text

    def test_mixed_results(self) -> None:
        """Mixed valid/invalid phases are both shown."""
        results = [
            {"valid": True, "phase": "R", "errors": []},
            {
                "valid": False,
                "phase": "S",
                "errors": [{"file": "f", "line": 0, "expected": "x", "got": "y"}],
            },
        ]
        text = format_text_report(results)
        assert "[ok] Phase R" in text
        assert "[fail] Phase S" in text
