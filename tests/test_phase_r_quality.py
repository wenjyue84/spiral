"""
Tests for lib/research_quality_checker.py — Phase R Quality Checker

Tests the quality scoring and replay decision logic for research results.
Regression test suite for US-1281: Phase R quality checker.
Run with: pytest tests/test_phase_r_quality.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from research_quality_checker import (
    ResearchResult,
    compute_quality_score,
    should_replay,
)


class TestComputeQualityScore:
    """Tests for compute_quality_score() function."""

    def test_compute_quality_score(self) -> None:
        """Test that compute_quality_score returns a float in [0.0, 1.0]."""
        result = ResearchResult(
            citations=["source1", "source2", "source3"],
            sources=["site1.com", "site2.com"],
            content="This is research about testing",
        )
        score = compute_quality_score(result, "testing")

        # Score must be a float in [0.0, 1.0]
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_with_many_citations(self) -> None:
        """Higher citation count should increase score."""
        result_low = ResearchResult(
            citations=["s1"],
            sources=["site1.com"],
            content="research content",
        )
        result_high = ResearchResult(
            citations=["s1", "s2", "s3", "s4", "s5"],
            sources=["site1.com"],
            content="research content",
        )

        score_low = compute_quality_score(result_low, "research")
        score_high = compute_quality_score(result_high, "research")

        assert score_high > score_low

    def test_score_with_diverse_sources(self) -> None:
        """More diverse sources should increase score."""
        result_low = ResearchResult(
            citations=["s1"],
            sources=["site1.com"],
            content="research content",
        )
        result_high = ResearchResult(
            citations=["s1"],
            sources=["site1.com", "site2.com", "site3.com"],
            content="research content",
        )

        score_low = compute_quality_score(result_low, "research")
        score_high = compute_quality_score(result_high, "research")

        assert score_high > score_low

    def test_score_with_relevant_content(self) -> None:
        """Content matching story title should increase score."""
        result_low = ResearchResult(
            citations=["s1"],
            sources=["site1.com"],
            content="unrelated content about weather",
        )
        result_high = ResearchResult(
            citations=["s1"],
            sources=["site1.com"],
            content="detailed information about testing frameworks",
        )

        score_low = compute_quality_score(result_low, "testing")
        score_high = compute_quality_score(result_high, "testing")

        assert score_high > score_low

    def test_score_with_dict_input(self) -> None:
        """compute_quality_score should accept dict input."""
        result_dict = {
            "citations": ["s1", "s2"],
            "sources": ["site1.com"],
            "content": "research about testing",
        }
        score = compute_quality_score(result_dict, "testing")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_with_empty_result(self) -> None:
        """Empty research result should have low but valid score."""
        result = ResearchResult(
            citations=[],
            sources=[],
            content="",
        )
        score = compute_quality_score(result, "testing")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        assert score >= 0.0  # Should not be negative


class TestShouldReplay:
    """Tests for should_replay() function."""

    def test_should_replay_below_threshold(self) -> None:
        """Test that should_replay returns True when score < 0.7 and attempt < 3."""
        # Score below threshold, first attempt
        assert should_replay(0.5, 0) is True
        assert should_replay(0.69, 1) is True
        assert should_replay(0.6, 2) is True

    def test_should_not_replay_above_threshold(self) -> None:
        """Test that should_replay returns False when score >= 0.7."""
        assert should_replay(0.7, 0) is False
        assert should_replay(0.8, 1) is False
        assert should_replay(1.0, 2) is False

    def test_should_not_replay_at_max_attempts(self) -> None:
        """Test that should_replay returns False when attempt_count >= 3."""
        # Should not replay even with low score when max attempts reached
        assert should_replay(0.5, 3) is False
        assert should_replay(0.1, 4) is False
        assert should_replay(0.0, 3) is False

    def test_replay_threshold_boundary(self) -> None:
        """Test boundary condition at 0.7 score threshold."""
        # Just below threshold
        assert should_replay(0.699, 0) is True
        # At threshold
        assert should_replay(0.7, 0) is False
        # Just above threshold
        assert should_replay(0.701, 0) is False

    def test_replay_attempt_boundary(self) -> None:
        """Test boundary condition at 3 attempt limit."""
        # Below limit
        assert should_replay(0.5, 2) is True
        # At limit
        assert should_replay(0.5, 3) is False
        # Above limit
        assert should_replay(0.5, 4) is False

    def test_replay_all_conditions(self) -> None:
        """Test all combinations of score and attempt."""
        # Low score, low attempt -> replay
        assert should_replay(0.3, 0) is True

        # High score, low attempt -> no replay
        assert should_replay(0.9, 0) is False

        # Low score, high attempt -> no replay
        assert should_replay(0.3, 3) is False

        # High score, high attempt -> no replay
        assert should_replay(0.9, 3) is False
