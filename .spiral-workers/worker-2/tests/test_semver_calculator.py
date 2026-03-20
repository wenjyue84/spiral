"""Tests for lib/semver_calculator.py — Phase G Semantic Version Calculator (US-555)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from semver_calculator import calculate_next_version, generate_changelog_segment

# ── Helpers ────────────────────────────────────────────────────────────────────


def _story(story_id: str, score: float, story_type: str) -> dict:
    return {"story_id": story_id, "score": score, "type": story_type}


def _write_prd(tmp_dir: str, stories: list[dict]) -> str:
    """Write a minimal prd.json and return its path."""
    prd = {
        "userStories": [
            {"id": s["story_id"], "title": f"Title for {s['story_id']}", "description": "Some description"}
            for s in stories
        ]
    }
    path = os.path.join(tmp_dir, "prd.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prd, f)
    return path


# ── Version calculation tests ─────────────────────────────────────────────────


class TestCalculateNextVersion:
    """Verify SemVer 2.0.0 bump logic based on story types."""

    def test_breaking_bumps_major(self) -> None:
        """A single breaking story should bump major and reset minor & patch."""
        stories = [_story("US-100", 8.5, "breaking")]
        assert calculate_next_version("v1.2.3", stories) == "2.0.0"

    def test_feature_bumps_minor(self) -> None:
        """A single feature story should bump minor and reset patch."""
        stories = [_story("US-101", 5.0, "feature")]
        assert calculate_next_version("v1.2.3", stories) == "1.3.0"

    def test_fix_bumps_patch(self) -> None:
        """A single fix story should bump only patch."""
        stories = [_story("US-102", 2.0, "fix")]
        assert calculate_next_version("v1.2.3", stories) == "1.2.4"

    def test_mixed_types_highest_wins(self) -> None:
        """When stories include breaking + fix, breaking (highest tier) wins."""
        stories = [
            _story("US-200", 3.0, "fix"),
            _story("US-201", 7.5, "breaking"),
            _story("US-202", 4.0, "feature"),
        ]
        assert calculate_next_version("v1.2.3", stories) == "2.0.0"

    def test_feature_and_fix_feature_wins(self) -> None:
        """Feature + fix should bump minor (feature is higher than fix)."""
        stories = [
            _story("US-300", 2.0, "fix"),
            _story("US-301", 5.0, "feature"),
        ]
        assert calculate_next_version("v1.2.3", stories) == "1.3.0"

    def test_v0_to_v0_1_0_for_feature(self) -> None:
        """v0.0.1 with a feature story should bump to v0.1.0."""
        stories = [_story("US-400", 4.0, "feature")]
        assert calculate_next_version("v0.0.1", stories) == "0.1.0"

    def test_v0_to_v1_for_breaking(self) -> None:
        """v0.0.1 with a breaking story should bump to v1.0.0."""
        stories = [_story("US-401", 9.0, "breaking")]
        assert calculate_next_version("v0.0.1", stories) == "1.0.0"

    def test_tag_without_v_prefix(self) -> None:
        """Tags without 'v' prefix should also be parsed correctly."""
        stories = [_story("US-500", 2.0, "fix")]
        assert calculate_next_version("1.2.3", stories) == "1.2.4"

    def test_empty_stories_bumps_patch(self) -> None:
        """Empty story list defaults to patch bump (lowest tier)."""
        assert calculate_next_version("v1.0.0", []) == "1.0.1"

    def test_invalid_tag_raises_value_error(self) -> None:
        """Non-semver tags should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid semver tag"):
            calculate_next_version("not-a-version", [_story("US-001", 1.0, "fix")])

    def test_multiple_fixes_still_single_patch_bump(self) -> None:
        """Multiple fix stories should still only bump patch by 1."""
        stories = [
            _story("US-600", 1.0, "fix"),
            _story("US-601", 2.0, "fix"),
            _story("US-602", 3.0, "fix"),
        ]
        assert calculate_next_version("v2.5.9", stories) == "2.5.10"


# ── Changelog generation tests ────────────────────────────────────────────────


class TestGenerateChangelogSegment:
    """Verify changelog grouping and formatting."""

    def test_changelog_segment_format(self) -> None:
        """Changelog should group stories by tier with markdown headers."""
        stories = [
            _story("US-010", 9.0, "breaking"),
            _story("US-011", 5.0, "feature"),
            _story("US-012", 2.0, "fix"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_path = _write_prd(tmp_dir, stories)
            segment = generate_changelog_segment(stories, prd_path)

        assert "### Breaking Changes" in segment
        assert "### Features" in segment
        assert "### Fixes" in segment
        assert "**US-010**" in segment
        assert "**US-011**" in segment
        assert "**US-012**" in segment

    def test_changelog_includes_story_titles_from_prd(self) -> None:
        """Each entry should include the story title from prd.json."""
        stories = [_story("US-020", 4.0, "feature")]

        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_path = _write_prd(tmp_dir, stories)
            segment = generate_changelog_segment(stories, prd_path)

        assert "Title for US-020" in segment

    def test_changelog_without_prd_file(self) -> None:
        """Changelog should work even when prd.json does not exist."""
        stories = [_story("US-030", 2.0, "fix")]
        segment = generate_changelog_segment(stories, "/nonexistent/prd.json")

        assert "### Fixes" in segment
        assert "**US-030**" in segment

    def test_changelog_only_features(self) -> None:
        """When all stories are features, only the Features section should appear."""
        stories = [
            _story("US-040", 4.0, "feature"),
            _story("US-041", 5.0, "feature"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_path = _write_prd(tmp_dir, stories)
            segment = generate_changelog_segment(stories, prd_path)

        assert "### Features" in segment
        assert "### Breaking Changes" not in segment
        assert "### Fixes" not in segment

    def test_changelog_empty_stories(self) -> None:
        """Empty story list should produce empty output."""
        segment = generate_changelog_segment([], "/nonexistent/prd.json")
        assert segment.strip() == ""

    def test_changelog_ordering_breaking_features_fixes(self) -> None:
        """Breaking changes should appear before features, features before fixes."""
        stories = [
            _story("US-050", 2.0, "fix"),
            _story("US-051", 9.0, "breaking"),
            _story("US-052", 5.0, "feature"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            prd_path = _write_prd(tmp_dir, stories)
            segment = generate_changelog_segment(stories, prd_path)

        breaking_pos = segment.index("### Breaking Changes")
        features_pos = segment.index("### Features")
        fixes_pos = segment.index("### Fixes")
        assert breaking_pos < features_pos < fixes_pos
