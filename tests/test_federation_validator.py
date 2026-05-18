"""test_federation_validator.py — Tests for federation namespace collision detection."""

from __future__ import annotations

from lib.spiral.federation_validator import (
    ValidationResult,
    build_story_id_map,
    detect_collisions,
    extract_namespace_prefix,
    suggest_namespace_renames,
    validate_federation_namespaces,
)


class TestExtractNamespacePrefix:
    """Tests for namespace prefix extraction."""

    def test_simple_prefix(self) -> None:
        """Extract simple two-part ID."""
        assert extract_namespace_prefix("US-100") == "US"

    def test_long_prefix(self) -> None:
        """Extract multi-letter prefix."""
        assert extract_namespace_prefix("PAYMENTS-50") == "PAYMENTS"

    def test_three_part_id(self) -> None:
        """Extract prefix from three-part ID (ignore version)."""
        assert extract_namespace_prefix("US-100-v2") == "US"

    def test_empty_string(self) -> None:
        """Handle empty string."""
        assert extract_namespace_prefix("") == ""

    def test_no_dash(self) -> None:
        """Handle ID without dash."""
        assert extract_namespace_prefix("US100") == ""


class TestBuildStoryIdMap:
    """Tests for building namespace maps."""

    def test_single_project(self) -> None:
        """Build map for single project."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"id": "US-101"},
            ]
        }
        result = build_story_id_map(prd_dict)
        assert result == {
            "US-100": {"main": "US"},
            "US-101": {"main": "US"},
        }

    def test_multiple_projects(self) -> None:
        """Build map with sub_project field."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"id": "PAYMENTS-50", "sub_project": "payments"},
            ]
        }
        result = build_story_id_map(prd_dict)
        assert result == {
            "US-100": {"main": "US"},
            "PAYMENTS-50": {"payments": "PAYMENTS"},
        }

    def test_collision_same_id_different_prefixes(self) -> None:
        """Build map detecting same ID with different prefixes."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"id": "PAYMENTS-100", "sub_project": "payments"},
            ]
        }
        result = build_story_id_map(prd_dict)
        assert "US-100" in result or "PAYMENTS-100" in result

    def test_skip_invalid_stories(self) -> None:
        """Skip stories without ID."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"title": "No ID"},
                None,
                {"id": ""},
            ]
        }
        result = build_story_id_map(prd_dict)
        assert result == {"US-100": {"main": "US"}}


class TestDetectCollisions:
    """Tests for collision detection."""

    def test_no_collisions_single_project(self) -> None:
        """No collisions with single project."""
        namespace_map = {
            "US-100": {"main": "US"},
            "US-101": {"main": "US"},
        }
        collisions = detect_collisions(namespace_map)
        assert collisions == []

    def test_no_collisions_different_ids(self) -> None:
        """No collisions when different sub-projects have different IDs."""
        namespace_map = {
            "US-100": {"main": "US"},
            "PAYMENTS-50": {"payments": "PAYMENTS"},
        }
        collisions = detect_collisions(namespace_map)
        assert collisions == []

    def test_detect_namespace_collision(self) -> None:
        """Detect collision: same ID with different prefixes."""
        namespace_map = {
            "US-100": {"main": "US", "payments": "PAYMENTS"},
        }
        collisions = detect_collisions(namespace_map)
        assert len(collisions) == 1
        assert collisions[0]["story_id"] == "US-100"
        assert collisions[0]["conflict"] is True
        assert set(collisions[0]["prefixes"]) == {"US", "PAYMENTS"}

    def test_detect_multiple_collisions(self) -> None:
        """Detect multiple collisions."""
        namespace_map = {
            "ID-1": {"main": "ID", "payments": "PAYMENT"},
            "ID-2": {"main": "ID", "inventory": "INV"},
            "ID-3": {"main": "ID"},
        }
        collisions = detect_collisions(namespace_map)
        assert len(collisions) == 2


class TestSuggestNamespaceRenames:
    """Tests for auto-fix suggestions."""

    def test_suggest_rename(self) -> None:
        """Suggest renaming to match main project."""
        collisions = [
            {
                "story_id": "US-100",
                "projects": {"main": "US", "payments": "PAYMENTS"},
                "prefixes": ["US", "PAYMENTS"],
            }
        ]
        suggestions = suggest_namespace_renames(collisions)
        assert len(suggestions) == 1
        assert "PAYMENTS-100" in suggestions[0]
        assert "payments" in suggestions[0]

    def test_suggest_multiple_renames(self) -> None:
        """Suggest renames for multiple collisions."""
        collisions = [
            {
                "story_id": "ID-1",
                "projects": {"main": "ID", "payments": "PAYMENT"},
                "prefixes": ["ID", "PAYMENT"],
            },
            {
                "story_id": "ID-2",
                "projects": {"main": "ID", "inventory": "INV"},
                "prefixes": ["ID", "INV"],
            },
        ]
        suggestions = suggest_namespace_renames(collisions)
        assert len(suggestions) == 2
        assert any("PAYMENT" in s for s in suggestions)
        assert any("INV" in s for s in suggestions)

    def test_no_suggestion_for_consistent_ids(self) -> None:
        """No suggestions when all prefixes match."""
        collisions = []
        suggestions = suggest_namespace_renames(collisions)
        assert suggestions == []


class TestValidateFederationNamespaces:
    """Integration tests for full validation flow."""

    def test_valid_federation(self) -> None:
        """Validate a valid federated PRD."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"id": "US-101"},
                {"id": "PAYMENTS-50", "sub_project": "payments"},
                {"id": "PAYMENTS-51", "sub_project": "payments"},
            ]
        }
        result = validate_federation_namespaces(prd_dict)
        assert result.is_valid is True
        assert result.collisions == []
        assert result.suggestions == []

    def test_detect_namespace_collision_integration(self) -> None:
        """Full integration test for namespace collision."""
        prd_dict = {
            "userStories": [
                {"id": "US-100"},
                {"id": "US-100", "sub_project": "payments"},  # Same ID, different project
            ]
        }
        result = validate_federation_namespaces(prd_dict)
        assert result.is_valid is False
        assert len(result.collisions) == 1
        assert result.collisions[0]["story_id"] == "US-100"
        assert len(result.suggestions) > 0

    def test_complex_federation(self) -> None:
        """Test complex federation with multiple sub-projects."""
        prd_dict = {
            "userStories": [
                {"id": "US-1", "title": "Main task 1"},
                {"id": "US-2", "title": "Main task 2"},
                {"id": "PAYMENTS-1", "sub_project": "payments", "title": "Payment task 1"},
                {"id": "PAYMENTS-100", "sub_project": "payments", "title": "Payment task 2"},
                {"id": "PAYMENTS-100", "sub_project": "inventory", "title": "Inventory task"},  # Collision
            ]
        }
        result = validate_federation_namespaces(prd_dict)
        assert result.is_valid is False
        collisions_for_100 = [c for c in result.collisions if c["story_id"] == "PAYMENTS-100"]
        assert len(collisions_for_100) >= 1

    def test_validation_result_type(self) -> None:
        """Verify ValidationResult structure."""
        prd_dict = {"userStories": [{"id": "US-100"}]}
        result = validate_federation_namespaces(prd_dict)
        assert isinstance(result, ValidationResult)
        assert isinstance(result.collisions, list)
        assert isinstance(result.namespace_map, dict)
        assert isinstance(result.suggestions, list)
        assert isinstance(result.is_valid, bool)

    def test_empty_prd(self) -> None:
        """Handle empty PRD."""
        prd_dict: dict = {}
        result = validate_federation_namespaces(prd_dict)
        assert result.is_valid is True
        assert result.collisions == []
