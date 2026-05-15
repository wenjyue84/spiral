"""Tests for US-1329: timeout_handler and scope_reducer modules."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from timeout_handler import timeout_scope_reducer
from impl.scope_reducer import strip_optional_ac

# Import validate_prd for schema validation tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))
from prd_schema import validate_prd  # type: ignore[import-untyped]

# Minimal valid story fixture
_BASE_STORY: dict[str, object] = {
    "id": "US-001",
    "title": "Test story for scope reduction",
    "priority": "medium",
    "passes": False,
    "dependencies": [],
    "acceptanceCriteria": [
        "Non-optional AC 1 — must remain",
        "Non-optional AC 2 — must remain",
        "@optional AC 3 — should be stripped",
        "@optional AC 4 — should be stripped",
    ],
}


class TestScopeReducerStripsOptionalAC:
    """AC1: strip_optional_ac removes @optional ACs, keeps non-optional."""

    def test_scope_reducer_strips_optional_ac(self) -> None:
        """Two @optional ACs are removed; non-optional ACs are intact."""
        result = strip_optional_ac(_BASE_STORY)
        acs = result["acceptanceCriteria"]
        assert isinstance(acs, list)
        assert len(acs) == 2, f"Expected 2 ACs after stripping, got {len(acs)}: {acs}"
        assert "Non-optional AC 1 — must remain" in acs
        assert "Non-optional AC 2 — must remain" in acs
        for ac in acs:
            assert not str(ac).startswith("@optional"), f"@optional AC not stripped: {ac}"

    def test_original_story_is_not_mutated(self) -> None:
        """strip_optional_ac returns a copy — original story is unchanged."""
        original_acs = list(_BASE_STORY["acceptanceCriteria"])  # type: ignore[arg-type]
        strip_optional_ac(_BASE_STORY)
        assert _BASE_STORY["acceptanceCriteria"] == original_acs


class TestScopeReducerNoOptionalAC:
    """AC2: story with zero @optional ACs is returned unchanged."""

    def test_no_optional_ac_returns_story_unchanged(self) -> None:
        """Zero @optional ACs → story returned unchanged (same ACs)."""
        story: dict[str, object] = {
            "id": "US-002",
            "title": "Story without optional ACs",
            "priority": "medium",
            "passes": False,
            "acceptanceCriteria": [
                "Regular AC 1",
                "Regular AC 2",
            ],
        }
        result = strip_optional_ac(story)
        assert result["acceptanceCriteria"] == story["acceptanceCriteria"]


class TestTimeoutScopeReducer:
    """timeout_scope_reducer delegates to strip_optional_ac correctly."""

    def test_timeout_scope_reducer_strips_optional_ac(self) -> None:
        """timeout_scope_reducer with story_id removes @optional ACs."""
        result = timeout_scope_reducer("US-001", _BASE_STORY)
        acs = result["acceptanceCriteria"]
        assert isinstance(acs, list)
        assert len(acs) == 2
        for ac in acs:
            assert not str(ac).startswith("@optional")

    def test_timeout_scope_reducer_no_optional(self) -> None:
        """timeout_scope_reducer on story with no @optional ACs is unchanged."""
        story: dict[str, object] = {
            "id": "US-003",
            "title": "No optional ACs",
            "priority": "low",
            "passes": False,
            "acceptanceCriteria": ["Plain AC"],
        }
        result = timeout_scope_reducer("US-003", story)
        assert result["acceptanceCriteria"] == ["Plain AC"]


class TestReducedStorySchemaValidation:
    """AC3: reduced story dict passes Phase S JSON schema validation."""

    def test_reduced_story_passes_schema_validation(self) -> None:
        """Wrap reduced story in minimal prd dict and validate via prd_schema."""
        reduced = timeout_scope_reducer("US-001", _BASE_STORY)
        prd: dict[str, object] = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [reduced],
        }
        errors = validate_prd(prd)
        assert errors == [], f"Schema validation failed: {errors}"
