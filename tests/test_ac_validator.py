#!/usr/bin/env python3
"""
tests/test_ac_validator.py — Tests for AC validator
"""

import json
import tempfile
from pathlib import Path

from lib.ac_validator import (
    calculate_risk_level,
    check_ac_word_count,
    check_empty_acs,
    detect_technical_references,
    score_acceptance_criteria,
    validate_story_acs,
)


def test_empty_ac_list() -> None:
    """Empty AC list should be detected."""
    is_empty, msg = check_empty_acs([])
    assert is_empty and "Empty" in msg


def test_short_ac() -> None:
    """ACs with <5 words should be flagged."""
    warnings = check_ac_word_count(["This is short"])
    assert len(warnings) == 1 and "only 3 words" in warnings[0]


def test_sufficient_words() -> None:
    """ACs with >=5 words should pass."""
    warnings = check_ac_word_count(["This acceptance criterion has enough words"])
    assert len(warnings) == 0


def test_filename_reference() -> None:
    """ACs with filenames should pass."""
    warnings = detect_technical_references(["Update lib/api_handler.py to handle errors"])
    assert len(warnings) == 0


def test_function_reference() -> None:
    """ACs with functions should pass."""
    warnings = detect_technical_references(["Implement validate_input() function"])
    assert len(warnings) == 0


def test_no_technical_reference() -> None:
    """ACs without technical references should be flagged."""
    warnings = detect_technical_references(["The system should work better"])
    assert len(warnings) == 1 and "lacks technical reference" in warnings[0]


def test_risk_level_low() -> None:
    """No or few warnings = low risk."""
    assert calculate_risk_level([]) == "low"
    assert calculate_risk_level(["AC 1 is short"]) == "low"


def test_risk_level_medium() -> None:
    """Two warnings = medium risk."""
    assert calculate_risk_level(["AC 1 is short", "AC 2 is short"]) == "medium"


def test_risk_level_high() -> None:
    """Empty AC or 3+ warnings = high risk."""
    assert calculate_risk_level(["Empty acceptance criteria list"]) == "high"
    assert calculate_risk_level(["AC 1 is short", "AC 2 is short", "AC 3 is short"]) == "high"


def test_well_formed_story() -> None:
    """Story with good ACs should have low risk."""
    story = {
        "id": "US-100",
        "acceptanceCriteria": [
            "Implement error handling in lib/api_handler.py",
            "Create test_error_handling() function",
        ],
    }
    result = validate_story_acs(story)
    assert result.story_id == "US-100" and result.risk_level == "low"


def test_empty_story_acs() -> None:
    """Story with empty ACs should be flagged."""
    story = {"id": "US-101", "acceptanceCriteria": []}
    result = validate_story_acs(story)
    assert result.risk_level == "high" and len(result.warnings) == 1


def test_vague_story_acs() -> None:
    """Story with vague ACs should be flagged."""
    story = {
        "id": "US-102",
        "acceptanceCriteria": ["The system works", "It should be fast", "User experience is good"],
    }
    result = validate_story_acs(story)
    assert result.risk_level == "high" and len(result.warnings) >= 3


def test_score_acceptance_criteria() -> None:
    """Should validate all stories in PRD."""
    prd_data = {
        "userStories": [
            {
                "id": "US-1",
                "acceptanceCriteria": [
                    "Implement error handling in lib/handler.py",
                    "Add comprehensive test_handler() validation function",
                ],
            },
            {"id": "US-2", "acceptanceCriteria": ["This is vague"]},
            {"id": "US-3", "acceptanceCriteria": []},
        ]
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(prd_data, f)
        temp_file = f.name
    try:
        results = score_acceptance_criteria(temp_file)
        assert len(results) == 2
        assert any(r.story_id == "US-2" for r in results)
    finally:
        Path(temp_file).unlink()


def test_missing_prd_file() -> None:
    """Should handle missing PRD file gracefully."""
    assert score_acceptance_criteria("/nonexistent/file.json") == []
