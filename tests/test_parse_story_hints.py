"""Integration tests for parse_story_hints — complexity band extraction and prompt building."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from parse_story_hints import build_hint_context, extract_complexity_band

# ── extract_complexity_band ──────────────────────────────────────────────────


class TestExtractComplexityBand:
    def test_extracts_small(self) -> None:
        text = "Implement feature X. @spiral:hint-complexity-band:small"
        assert extract_complexity_band(text) == "small"

    def test_extracts_medium(self) -> None:
        text = "Big feature @spiral:hint-complexity-band:medium with details"
        assert extract_complexity_band(text) == "medium"

    def test_extracts_large(self) -> None:
        text = "@spiral:hint-complexity-band:large\nMulti-line description"
        assert extract_complexity_band(text) == "large"

    def test_case_insensitive(self) -> None:
        text = "Story text @spiral:hint-complexity-band:MEDIUM end"
        assert extract_complexity_band(text) == "medium"

    def test_no_marker_returns_none(self) -> None:
        text = "A normal story description without any hints"
        assert extract_complexity_band(text) is None

    def test_invalid_band_returns_none(self) -> None:
        text = "@spiral:hint-complexity-band:huge"
        assert extract_complexity_band(text) is None

    def test_empty_string(self) -> None:
        assert extract_complexity_band("") is None


# ── build_hint_context ───────────────────────────────────────────────────────


class TestBuildHintContext:
    def test_small_band_guidance(self) -> None:
        result = build_hint_context("small")
        assert "SMALL scope" in result
        assert 'band="small"' in result

    def test_medium_band_guidance(self) -> None:
        result = build_hint_context("medium")
        assert "MEDIUM scope" in result
        assert "3 sub-stories" in result

    def test_large_band_guidance(self) -> None:
        result = build_hint_context("large")
        assert "LARGE scope" in result
        assert "4 sub-stories" in result

    def test_invalid_band_returns_empty(self) -> None:
        assert build_hint_context("unknown") == ""
        assert build_hint_context("") == ""


# ── Integration: 3 stories with hints → decomposed guidance ──────────────────


class TestIntegrationHintedStories:
    """Simulate 3 stories with different hints and verify decomposition context."""

    @pytest.fixture()
    def stories_with_hints(self) -> list[dict[str, str]]:
        return [
            {
                "id": "US-100",
                "description": "Add login form @spiral:hint-complexity-band:small",
            },
            {
                "id": "US-101",
                "description": "Refactor auth module @spiral:hint-complexity-band:medium",
            },
            {
                "id": "US-102",
                "description": "Full dashboard rewrite @spiral:hint-complexity-band:large",
            },
        ]

    def test_all_bands_extracted(self, stories_with_hints: list[dict[str, str]]) -> None:
        bands = [extract_complexity_band(s["description"]) for s in stories_with_hints]
        assert bands == ["small", "medium", "large"]

    def test_hint_contexts_reflect_guidance(self, stories_with_hints: list[dict[str, str]]) -> None:
        for story in stories_with_hints:
            band = extract_complexity_band(story["description"])
            assert band is not None
            context = build_hint_context(band)
            assert context != ""
            assert f'band="{band}"' in context

    def test_small_prefers_fewer_substories(self, stories_with_hints: list[dict[str, str]]) -> None:
        band = extract_complexity_band(stories_with_hints[0]["description"])
        assert band == "small"
        context = build_hint_context(band)
        assert "2 sub-stories" in context

    def test_large_decomposes_aggressively(self, stories_with_hints: list[dict[str, str]]) -> None:
        band = extract_complexity_band(stories_with_hints[2]["description"])
        assert band == "large"
        context = build_hint_context(band)
        assert "4 sub-stories" in context
