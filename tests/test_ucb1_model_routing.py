"""tests/test_ucb1_model_routing.py — Regression tests for UCB1 model routing (US-1210).

Verifies that the UCB1 (Upper Confidence Bound) algorithm correctly recommends
Claude models based on historical pass rates from results.tsv.

These tests ensure that US-1210 regression test covers core observable behaviour:
1. UCB1 selects models based on historical pass rates
2. Tests fail if UCB1 feature is broken or removed
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "routing"))

from ucb1_select import (
    calculate_ucb1_score,
    extract_story_tag,
    parse_results_tsv,
    select_best_model,
)


class TestExtractStoryTag:
    """Test story tag extraction from titles."""

    def test_extract_bracket_tag(self) -> None:
        """Extract [Tag] from start of title."""
        assert extract_story_tag("[Regression Test] CLI: check-federated-deps") == "[Regression Test]"
        assert extract_story_tag("[Security Test] Auth Control") == "[Security Test]"

    def test_no_tag_returns_empty(self) -> None:
        """No [Tag] returns empty string."""
        assert extract_story_tag("Regular Story Title") == ""
        assert extract_story_tag("US-001 Some Feature") == ""

    def test_multiple_brackets_extracts_first(self) -> None:
        """Only first [Tag] is extracted."""
        assert extract_story_tag("[First] [Second] Title") == "[First]"


class TestParseResultsTsv:
    """Test parsing results.tsv."""

    def test_parse_empty_file(self) -> None:
        """Empty results.tsv returns empty groups."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("timestamp\tspiral_iter\tstory_title\tstatus\tmodel\n")
            temp_path = f.name

        try:
            groups = parse_results_tsv(temp_path)
            assert groups == {}
        finally:
            Path(temp_path).unlink()

    def test_parse_with_tagged_stories(self) -> None:
        """Parse stories with tags and group correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "spiral_iter", "story_title", "status", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerows([
                {
                    "timestamp": "2026-03-20T04:00:00Z",
                    "spiral_iter": "1",
                    "story_title": "[Regression Test] CLI: check-federated-deps",
                    "status": "pass",
                    "model": "haiku",
                },
                {
                    "timestamp": "2026-03-20T04:10:00Z",
                    "spiral_iter": "1",
                    "story_title": "[Regression Test] Another Test",
                    "status": "reject",
                    "model": "haiku",
                },
                {
                    "timestamp": "2026-03-20T04:20:00Z",
                    "spiral_iter": "2",
                    "story_title": "[Regression Test] Third Test",
                    "status": "pass",
                    "model": "sonnet",
                },
                {
                    "timestamp": "2026-03-20T04:30:00Z",
                    "spiral_iter": "2",
                    "story_title": "[Security Test] Auth Control",
                    "status": "pass",
                    "model": "sonnet",
                },
            ])
            temp_path = f.name

        try:
            groups = parse_results_tsv(temp_path)
            # Check group structure
            assert ("haiku", "[Regression Test]") in groups
            assert ("sonnet", "[Regression Test]") in groups
            assert ("sonnet", "[Security Test]") in groups

            # Check counts
            assert groups[("haiku", "[Regression Test]")] == {"wins": 1, "attempts": 2}
            assert groups[("sonnet", "[Regression Test]")] == {"wins": 1, "attempts": 1}
            assert groups[("sonnet", "[Security Test]")] == {"wins": 1, "attempts": 1}
        finally:
            Path(temp_path).unlink()

    def test_parse_nonexistent_file(self) -> None:
        """Nonexistent file returns empty groups."""
        groups = parse_results_tsv("/nonexistent/path/results.tsv")
        assert groups == {}


class TestCalculateUCB1Score:
    """Test UCB1 score calculation."""

    def test_unknown_model_returns_negative(self) -> None:
        """Unknown model+tag returns -1.0."""
        groups = {("haiku", "[Regression Test]"): {"wins": 5, "attempts": 10}}
        score = calculate_ucb1_score("opus", "[Regression Test]", groups)
        assert score == -1.0

    def test_too_few_attempts_returns_penalty(self) -> None:
        """Too few attempts (<min_attempts) returns penalty score."""
        groups = {("haiku", "[Regression Test]"): {"wins": 1, "attempts": 1}}
        score = calculate_ucb1_score("haiku", "[Regression Test]", groups, min_attempts=2)
        assert score == -0.5

    def test_ucb1_formula_high_winrate(self) -> None:
        """High win rate produces high UCB1 score."""
        # 9 wins out of 10 attempts
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 9, "attempts": 10},
            ("sonnet", "[Regression Test]"): {"wins": 9, "attempts": 10},
            ("opus", "[Regression Test]"): {"wins": 9, "attempts": 10},
        }
        score = calculate_ucb1_score("haiku", "[Regression Test]", groups)
        # 9/10 + sqrt(2*ln(30)/10) ≈ 0.9 + sqrt(0.219) ≈ 0.9 + 0.468 ≈ 1.368
        assert score > 1.0

    def test_ucb1_formula_low_winrate(self) -> None:
        """Low win rate produces low UCB1 score."""
        # 1 win out of 10 attempts
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 1, "attempts": 10},
            ("sonnet", "[Regression Test]"): {"wins": 1, "attempts": 10},
            ("opus", "[Regression Test]"): {"wins": 1, "attempts": 10},
        }
        score = calculate_ucb1_score("haiku", "[Regression Test]", groups)
        # 1/10 + sqrt(2*ln(30)/10) ≈ 0.1 + 0.468 ≈ 0.568
        assert 0.3 < score < 1.0


class TestSelectBestModel:
    """Test best model selection."""

    def test_select_best_model_single_winner(self) -> None:
        """Select model with highest win rate."""
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 2, "attempts": 10},
            ("sonnet", "[Regression Test]"): {"wins": 8, "attempts": 10},
            ("opus", "[Regression Test]"): {"wins": 5, "attempts": 10},
        }
        best = select_best_model("[Regression Test]", groups)
        # sonnet has win rate 0.8, haiku 0.2, opus 0.5
        assert best == "sonnet"

    def test_select_best_model_exploration_boost(self) -> None:
        """Model with fewer attempts but decent win rate might win due to exploration term."""
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 5, "attempts": 100},  # 0.05
            ("sonnet", "[Regression Test]"): {"wins": 3, "attempts": 5},     # 0.6
        }
        best = select_best_model("[Regression Test]", groups)
        # sonnet: 0.6 + sqrt(2*ln(105)/5) ≈ 0.6 + sqrt(3.19) ≈ 0.6 + 1.78 ≈ 2.38
        # haiku:  0.05 + sqrt(2*ln(105)/100) ≈ 0.05 + sqrt(0.13) ≈ 0.05 + 0.36 ≈ 0.41
        assert best == "sonnet"

    def test_select_best_model_no_valid_models(self) -> None:
        """Return None if no valid models for tag."""
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 0, "attempts": 1},
        }
        best = select_best_model("[Security Test]", groups)
        assert best is None

    def test_select_best_model_all_low_attempts(self) -> None:
        """All models with <min_attempts returns None."""
        groups = {
            ("haiku", "[Regression Test]"): {"wins": 1, "attempts": 1},
            ("sonnet", "[Regression Test]"): {"wins": 1, "attempts": 1},
        }
        best = select_best_model("[Regression Test]", groups)
        assert best is None


class TestRegressionUCB1Integration:
    """Integration tests for UCB1 regression — verify feature doesn't break."""

    def test_regression_parse_and_select_flow(self) -> None:
        """Full flow: parse TSV → calculate UCB1 → select best model."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "spiral_iter", "story_title", "status", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            # [Regression Test] stories: haiku 7/10, sonnet 9/10
            for i in range(7):
                writer.writerow({
                    "timestamp": f"2026-03-20T04:{i:02d}:00Z",
                    "spiral_iter": "1",
                    "story_title": f"[Regression Test] Test {i}",
                    "status": "pass",
                    "model": "haiku",
                })
            for i in range(3):
                writer.writerow({
                    "timestamp": f"2026-03-20T05:{i:02d}:00Z",
                    "spiral_iter": "1",
                    "story_title": f"[Regression Test] Test {i+10}",
                    "status": "reject",
                    "model": "haiku",
                })
            for i in range(9):
                writer.writerow({
                    "timestamp": f"2026-03-20T06:{i:02d}:00Z",
                    "spiral_iter": "2",
                    "story_title": f"[Regression Test] Test {i+20}",
                    "status": "pass",
                    "model": "sonnet",
                })
            for i in range(1):
                writer.writerow({
                    "timestamp": f"2026-03-20T07:{i:02d}:00Z",
                    "spiral_iter": "2",
                    "story_title": f"[Regression Test] Test {i+30}",
                    "status": "reject",
                    "model": "sonnet",
                })
            temp_path = f.name

        try:
            groups = parse_results_tsv(temp_path)
            # Verify parsing
            assert groups[("haiku", "[Regression Test]")] == {"wins": 7, "attempts": 10}
            assert groups[("sonnet", "[Regression Test]")] == {"wins": 9, "attempts": 10}

            # Calculate UCB1 scores
            haiku_score = calculate_ucb1_score("haiku", "[Regression Test]", groups)
            sonnet_score = calculate_ucb1_score("sonnet", "[Regression Test]", groups)

            # sonnet (90% win rate) should beat haiku (70% win rate)
            assert sonnet_score > haiku_score

            # Select best model
            best = select_best_model("[Regression Test]", groups)
            assert best == "sonnet"
        finally:
            Path(temp_path).unlink()
