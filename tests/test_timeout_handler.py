"""Tests for US-1329/US-1330: timeout_handler and scope_reducer modules."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from impl.scope_reducer import strip_optional_ac
from timeout_handler import reduce_story_for_timeout, timeout_scope_reducer

# Import validate_prd for schema validation tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "prd"))
from prd_schema import validate_prd

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
        original_acs = list(_BASE_STORY["acceptanceCriteria"])  # type: ignore[call-overload]
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


# ── US-1330: Integration tests for timeout retry path scope reduction ──────────


_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestTimeoutTrigersScopeReductionNotDecompose:
    """US-1330 AC1+AC2: retry path calls scope_reducer and writes temp file."""

    def test_timeout_triggers_scope_reduction_not_decompose(self) -> None:
        """Fixture story with @optional ACs → reduced file written to disk.

        Simulates what try_timeout_scope_reduction in retry.sh does: calls
        reduce_story_for_timeout(), which writes the reduced story to a temp
        file before decompose_story() would be called.
        """
        fixture_path = os.path.join(_FIXTURES_DIR, "sample-stories-with-optional-ac.json")
        reduced_path = reduce_story_for_timeout(fixture_path)
        assert reduced_path != "", "Expected a temp file path, got empty string"
        assert os.path.exists(reduced_path), f"Reduced story temp file not on disk: {reduced_path}"

        try:
            with open(reduced_path, encoding="utf-8") as fh:
                on_disk: dict[str, object] = json.load(fh)

            disk_acs = on_disk.get("acceptanceCriteria", [])
            assert isinstance(disk_acs, list)
            assert len(disk_acs) == 2, f"Expected 2 ACs after stripping, got {len(disk_acs)}"
            for ac in disk_acs:
                assert not str(ac).startswith("@optional"), f"@optional AC not stripped: {ac}"
        finally:
            os.unlink(reduced_path)

    def test_no_optional_ac_falls_through_to_decompose(self) -> None:
        """US-1330 AC3: story with no @optional ACs returns '' (no temp file written)."""
        import tempfile

        story: dict[str, object] = {
            "id": "US-no-optional",
            "title": "Story with no optional ACs",
            "priority": "low",
            "passes": False,
            "dependencies": [],
            "acceptanceCriteria": ["Required AC only"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(story, tmp, ensure_ascii=False)
            tmp_path = tmp.name

        try:
            result = reduce_story_for_timeout(tmp_path)
            assert result == "", (
                f"Expected empty string (no scope reduction) for story with no @optional ACs, got: {result!r}"
            )
        finally:
            os.unlink(tmp_path)
