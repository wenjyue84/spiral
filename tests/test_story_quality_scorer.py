#!/usr/bin/env python3
"""
tests/test_story_quality_scorer.py — Unit tests for story quality scoring

Tests the scoring logic across all four dimensions:
  1. Production value (Tier 1-4)
  2. Constitution alignment
  3. Acceptance criteria quality
  4. Scope clarity
"""

import json
from pathlib import Path

from lib.story_quality_scorer import (
    filter_stories,
    load_constitution,
    score_acceptance_criteria_quality,
    score_constitution_alignment,
    score_production_value,
    score_scope_clarity,
    score_story,
)


class TestLoadConstitution:
    """Tests for loading constitution.md"""

    def test_load_constitution_success(self, tmp_path: Path) -> None:
        """Test successful loading of constitution."""
        constitution_file = tmp_path / "constitution.md"
        constitution_file.write_text("# Constitution\n\nRule 1: Never break things")
        content = load_constitution(str(constitution_file))
        assert "Rule 1" in content

    def test_load_constitution_missing_file(self) -> None:
        """Test graceful handling of missing file."""
        content = load_constitution("/nonexistent/path/constitution.md")
        assert content == ""


class TestScoreProductionValue:
    """Tests for production value scoring (Tier 1-4)"""

    def test_tier1_dashboard_ui(self) -> None:
        """Dashboard improvements are Tier 1 (user-facing)."""
        story = {
            "title": "Improve Dashboard UI",
            "description": "Add dashboard improvements for better visibility",
        }
        score, reasons = score_production_value(story)
        assert score >= 85.0
        assert "user-facing" in " ".join(reasons).lower()

    def test_tier1_performance(self) -> None:
        """Performance improvements are Tier 1."""
        story = {
            "title": "Speed up processing",
            "description": "Reduce query latency and improve performance",
        }
        score, reasons = score_production_value(story)
        assert score >= 85.0

    def test_tier2_reliability(self) -> None:
        """Reliability improvements are Tier 2."""
        story = {
            "title": "Crash recovery",
            "description": "Implement crash recovery and data integrity checks",
        }
        score, reasons = score_production_value(story)
        assert score >= 70.0

    def test_tier3_configuration(self) -> None:
        """Configuration options are Tier 3."""
        story = {
            "title": "Add config option",
            "description": "Add new configuration flag for advanced control",
        }
        score, reasons = score_production_value(story)
        assert score >= 50.0

    def test_tier4_infrastructure(self) -> None:
        """Infrastructure work is Tier 4 (lowest)."""
        story = {
            "title": "Infrastructure work",
            "description": "Improve observability and telemetry infrastructure",
        }
        score, reasons = score_production_value(story)
        assert score < 30.0

    def test_tier4_internal_format(self) -> None:
        """Internal format changes are Tier 4."""
        story = {
            "title": "Internal format",
            "description": "Restructure internal data structure",
        }
        score, reasons = score_production_value(story)
        assert score < 30.0


class TestScoreConstitutionAlignment:
    """Tests for constitution alignment"""

    def test_constitution_violation_skip_phases(self) -> None:
        """Flagged if story tries to skip phases."""
        story = {
            "title": "Skip validation",
            "description": "Skip phase S validation to speed up processing",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score < 30.0
        assert any("violation" in r.lower() for r in reasons)

    def test_constitution_violation_remove_gates(self) -> None:
        """Flagged if story tries to remove quality gates."""
        story = {
            "title": "Remove test requirement",
            "description": "Remove test coverage requirement to speed up merges",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score < 30.0

    def test_constitution_alignment_improve_phases(self) -> None:
        """Good score for improving existing phases."""
        story = {
            "title": "Improve Phase A",
            "description": "Improving existing phases by enhancing Phase A story generation quality",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score >= 50.0  # Phrase must explicitly match "improving existing phases"

    def test_constitution_alignment_optional_features(self) -> None:
        """High score for optional capabilities."""
        story = {
            "title": "Add optional features",
            "description": "Add optional capabilities via environment variables",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score >= 70.0

    def test_constitution_alignment_test_coverage(self) -> None:
        """High score for test coverage expansion."""
        story = {
            "title": "Expand tests",
            "description": "Expand test coverage for edge cases",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score >= 70.0

    def test_constitution_alignment_bug_fix(self) -> None:
        """Score for bug fixes."""
        story = {
            "title": "Fix critical bug",
            "description": "Bug fix in merge logic for correctness",
        }
        score, reasons = score_constitution_alignment(story, "")
        assert score >= 50.0  # Bug fixes align with constitution


class TestScoreAcceptanceCriteriaQuality:
    """Tests for acceptance criteria quality"""

    def test_no_acceptance_criteria(self) -> None:
        """Low score when no ACs defined."""
        story = {
            "title": "Story",
            "acceptanceCriteria": [],
        }
        score, reasons = score_acceptance_criteria_quality(story)
        assert score < 30.0

    def test_clear_measurable_testable_acs(self) -> None:
        """High score when ACs are clear, measurable, and testable."""
        story = {
            "title": "Implement feature",
            "acceptanceCriteria": [
                "Unit test verifies API returns 200 status code",
                "Performance metric: response time < 100ms",
                "Integration test confirms feature works end-to-end",
            ],
        }
        score, reasons = score_acceptance_criteria_quality(story)
        assert score >= 75.0
        assert "clear" in " ".join(reasons).lower()
        assert "testable" in " ".join(reasons).lower()

    def test_vague_acceptance_criteria(self) -> None:
        """Lower score when ACs are vague."""
        story = {
            "title": "Do something",
            "acceptanceCriteria": [
                "Maybe improve performance",
                "Consider adding caching",
                "Might want to add logging",
            ],
        }
        score, reasons = score_acceptance_criteria_quality(story)
        assert score < 60.0

    def test_mixed_quality_acceptance_criteria(self) -> None:
        """Medium score for mixed quality ACs."""
        story = {
            "title": "Feature",
            "acceptanceCriteria": [
                "Unit test verifies score calculation",
                "Maybe add caching",
                "Performance improves",
            ],
        }
        score, reasons = score_acceptance_criteria_quality(story)
        assert 40 <= score <= 70


class TestScopeClarityScoring:
    """Tests for scope clarity"""

    def test_small_story_well_scoped(self) -> None:
        """High score for small story with few ACs."""
        story = {
            "title": "Add config",
            "estimatedComplexity": "small",
            "description": "Add a new configuration variable with proper defaults and documentation",
            "acceptanceCriteria": [
                "Variable is documented",
                "Variable has default value",
            ],
        }
        score, reasons = score_scope_clarity(story)
        assert score >= 75.0

    def test_medium_story_well_scoped(self) -> None:
        """Good score for medium story with proportional ACs."""
        story = {
            "title": "Implement quality scoring system",
            "estimatedComplexity": "medium",
            "description": "Implement a quality scoring system to evaluate stories across all dimensions",
            "acceptanceCriteria": [
                "AC 1",
                "AC 2",
                "AC 3",
                "AC 4",
                "AC 5",
            ],
        }
        score, reasons = score_scope_clarity(story)
        assert score >= 70.0

    def test_small_story_scope_creep(self) -> None:
        """Low score for small story marked with many ACs."""
        story = {
            "title": "Small task",
            "estimatedComplexity": "small",
            "description": "A small task",
            "acceptanceCriteria": ["AC " + str(i) for i in range(10)],
        }
        score, reasons = score_scope_clarity(story)
        assert score < 50.0

    def test_brief_description(self) -> None:
        """Penalizes very brief descriptions."""
        story = {
            "title": "Task",
            "estimatedComplexity": "small",
            "description": "Do it",
            "acceptanceCriteria": ["AC 1"],
        }
        score, reasons = score_scope_clarity(story)
        assert any("too brief" in r.lower() for r in reasons)

    def test_long_description(self) -> None:
        """Penalizes overly long descriptions."""
        long_desc = " ".join(["word"] * 120)  # ~600 characters
        story = {
            "title": "Task",
            "estimatedComplexity": "large",
            "description": long_desc,
            "acceptanceCriteria": ["AC " + str(i) for i in range(10)],
        }
        score, reasons = score_scope_clarity(story)
        assert any("long" in r.lower() for r in reasons)


class TestScoreStory:
    """Tests for complete story scoring"""

    def test_high_quality_story(self) -> None:
        """Well-written story with user value scores high."""
        story = {
            "id": "US-1",
            "title": "Improve dashboard performance",
            "description": "Optimize dashboard rendering to reduce latency",
            "estimatedComplexity": "medium",
            "acceptanceCriteria": [
                "Performance test verifies <100ms render time",
                "Unit test checks optimization logic",
                "Feature works with existing components",
            ],
        }
        breakdown = score_story(story)
        assert breakdown["total_score"] >= 70.0
        assert breakdown["production_value"] >= 85.0

    def test_poor_quality_story(self) -> None:
        """Infrastructure-only story with vague ACs scores low."""
        story = {
            "id": "US-2",
            "title": "Infrastructure work",
            "description": "Maybe improve telemetry infrastructure",
            "estimatedComplexity": "small",
            "acceptanceCriteria": [
                "Consider adding metrics",
                "Might improve observability",
            ],
        }
        breakdown = score_story(story)
        assert breakdown["total_score"] < 50.0
        assert breakdown["production_value"] < 30.0

    def test_story_scoring_weights(self) -> None:
        """Verify that production value is weighted heavily (35%)."""
        # A story with high production value but poor constitution alignment
        # should still score reasonably well
        story = {
            "id": "US-3",
            "title": "Add dashboard widget",
            "description": "Add new widget to user dashboard",
            "estimatedComplexity": "small",
            "acceptanceCriteria": [
                "Widget renders correctly",
                "Widget responds to user input",
            ],
        }
        breakdown = score_story(story)
        # Should score well due to dashboard (Tier 1) in description
        assert breakdown["total_score"] >= 70.0

    def test_story_with_constitution_violation(self) -> None:
        """Infrastructure-only story should score low."""
        story = {
            "id": "US-4",
            "title": "Add observability infrastructure",
            "description": "Add infrastructure for observability and telemetry",
            "estimatedComplexity": "small",
            "acceptanceCriteria": [
                "Metrics are collected",
                "Telemetry is exported",
            ],
        }
        breakdown = score_story(story)
        # Infrastructure-only stories score in the 20-40 range
        assert breakdown["total_score"] < 50.0


class TestFilterStories:
    """Tests for story filtering"""

    def test_filter_stories_basic(self) -> None:
        """Filter stories by min score."""
        stories = [
            {
                "id": "US-1",
                "title": "Good story",
                "description": "Improve dashboard performance",
                "estimatedComplexity": "medium",
                "acceptanceCriteria": [
                    "Performance improves",
                    "Unit test verifies",
                ],
            },
            {
                "id": "US-2",
                "title": "Infrastructure",
                "description": "Maybe add telemetry infrastructure",
                "estimatedComplexity": "small",
                "acceptanceCriteria": [
                    "Consider adding metrics",
                ],
            },
        ]
        passing, filtered = filter_stories(stories, min_score=50)
        assert len(passing) >= 1  # At least the good story
        assert len(filtered) >= 1  # At least the infrastructure story

    def test_filter_stories_empty(self) -> None:
        """Handle empty story list."""
        passing, filtered = filter_stories([])
        assert len(passing) == 0
        assert len(filtered) == 0

    def test_filter_stories_all_pass(self) -> None:
        """When all stories pass threshold."""
        stories = [
            {
                "id": "US-1",
                "title": "Good story 1",
                "description": "Improve dashboard",
                "estimatedComplexity": "medium",
                "acceptanceCriteria": ["AC 1", "AC 2"],
            },
            {
                "id": "US-2",
                "title": "Good story 2",
                "description": "Optimize performance",
                "estimatedComplexity": "medium",
                "acceptanceCriteria": ["AC 1", "AC 2"],
            },
        ]
        passing, filtered = filter_stories(stories, min_score=30)
        assert len(passing) >= 1
        assert len(filtered) == 0 or len(filtered) == 1  # May filter some

    def test_filter_stories_all_fail(self) -> None:
        """When all stories fail threshold."""
        stories = [
            {
                "id": "US-1",
                "title": "Infrastructure work",
                "description": "Infrastructure improvements",
                "estimatedComplexity": "large",
                "acceptanceCriteria": ["Maybe improve"],
            },
            {
                "id": "US-2",
                "title": "Telemetry",
                "description": "Telemetry and observability",
                "estimatedComplexity": "large",
                "acceptanceCriteria": ["Improve metrics"],
            },
        ]
        passing, filtered = filter_stories(stories, min_score=70)
        # Infrastructure stories likely score below 70
        assert len(filtered) >= 1

    def test_filter_stories_constitution_check(self) -> None:
        """Constitution text should be passed to scorer."""
        constitution = "Never remove quality gates"
        story = {
            "id": "US-1",
            "title": "Infrastructure work",
            "description": "Infrastructure telemetry improvements",
            "estimatedComplexity": "small",
            "acceptanceCriteria": ["Add metrics"],
        }
        passing, filtered = filter_stories([story], min_score=50, constitution_text=constitution)
        # Infrastructure-only story should be filtered with higher threshold
        assert len(filtered) >= 1


class TestIntegration:
    """Integration tests with files"""

    def test_score_and_filter_workflow(self, tmp_path: Path) -> None:
        """End-to-end workflow: generate, score, filter."""
        # Create input stories
        input_file = tmp_path / "stories.json"
        stories = [
            {
                "id": "US-1",
                "title": "Improve UI responsiveness",
                "description": "Optimize dashboard for faster rendering",
                "estimatedComplexity": "medium",
                "acceptanceCriteria": [
                    "Performance test confirms <100ms",
                    "Unit tests verify logic",
                    "E2E test confirms UX",
                ],
            },
            {
                "id": "US-2",
                "title": "Internal telemetry",
                "description": "Add internal observability infrastructure",
                "estimatedComplexity": "medium",
                "acceptanceCriteria": [
                    "Maybe improve observability",
                ],
            },
        ]
        input_file.write_text(json.dumps(stories))

        # Score and filter
        output_file = tmp_path / "filtered.json"
        passing, filtered = filter_stories(stories, min_score=50)

        # Verify at least one passes (the UI one)
        assert len(passing) >= 1
        assert any(s.get("id") == "US-1" for s in passing)

        # Verify at least one is filtered (the telemetry one)
        assert len(filtered) >= 1
        assert any(s_id == "US-2" for s_id, _, _ in filtered)
