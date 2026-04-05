"""Tests for per-story verification contracts (prd.schema.json + prd_schema.py).

Validates that the `verification` field is accepted/rejected correctly by the
schema validator, and that Phase V can use it.
"""

from __future__ import annotations

from lib.prd.prd_schema import validate_prd


def _make_prd(stories: list[dict]) -> dict:  # type: ignore[type-arg]
    """Create a minimal valid prd.json with the given stories."""
    return {
        "productName": "test",
        "branchName": "main",
        "userStories": stories,
    }


def _make_story(**overrides: object) -> dict:  # type: ignore[type-arg]
    """Create a minimal valid story with optional overrides."""
    base = {
        "id": "US-100",
        "title": "Test story",
        "priority": "medium",
        "acceptanceCriteria": ["criterion 1"],
        "passes": False,
        "dependencies": [],
    }
    base.update(overrides)
    return base


class TestVerificationSchemaValidation:
    """Test that validate_prd() handles the verification field correctly."""

    def test_valid_with_test_files(self) -> None:
        story = _make_story(verification={"testFiles": ["tests/test_foo.py", "tests/test_bar.py"]})
        errors = validate_prd(_make_prd([story]))
        verification_errors = [e for e in errors if "verification" in e]
        assert verification_errors == []

    def test_valid_with_test_marker(self) -> None:
        story = _make_story(verification={"testMarker": "US_100"})
        errors = validate_prd(_make_prd([story]))
        verification_errors = [e for e in errors if "verification" in e]
        assert verification_errors == []

    def test_valid_with_command(self) -> None:
        story = _make_story(verification={"command": "bash check.sh"})
        errors = validate_prd(_make_prd([story]))
        verification_errors = [e for e in errors if "verification" in e]
        assert verification_errors == []

    def test_valid_with_all_fields(self) -> None:
        story = _make_story(
            verification={
                "testFiles": ["tests/test_foo.py"],
                "testMarker": "US_100",
                "command": "bash check.sh",
            }
        )
        errors = validate_prd(_make_prd([story]))
        verification_errors = [e for e in errors if "verification" in e]
        assert verification_errors == []

    def test_valid_without_verification(self) -> None:
        """Stories without verification field should still validate fine."""
        story = _make_story()
        errors = validate_prd(_make_prd([story]))
        verification_errors = [e for e in errors if "verification" in e]
        assert verification_errors == []

    def test_invalid_verification_not_object(self) -> None:
        story = _make_story(verification="not an object")
        errors = validate_prd(_make_prd([story]))
        assert any("verification must be an object" in e for e in errors)

    def test_invalid_empty_verification(self) -> None:
        """Empty verification object should fail (no fields)."""
        story = _make_story(verification={})
        errors = validate_prd(_make_prd([story]))
        assert any("must have at least one of" in e for e in errors)

    def test_invalid_test_files_not_list(self) -> None:
        story = _make_story(verification={"testFiles": "not a list"})
        errors = validate_prd(_make_prd([story]))
        assert any("testFiles" in e and "must be a list" in e for e in errors)

    def test_invalid_test_files_item_not_string(self) -> None:
        story = _make_story(verification={"testFiles": [123]})
        errors = validate_prd(_make_prd([story]))
        assert any("testFiles" in e and "must be a string" in e for e in errors)

    def test_invalid_test_marker_not_string(self) -> None:
        story = _make_story(verification={"testMarker": 123})
        errors = validate_prd(_make_prd([story]))
        assert any("testMarker" in e and "must be a string" in e for e in errors)

    def test_invalid_command_not_string(self) -> None:
        story = _make_story(verification={"command": 123})
        errors = validate_prd(_make_prd([story]))
        assert any("command" in e and "must be a string" in e for e in errors)
