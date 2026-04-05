"""Tests for historical model routing (lib/routing/complexity_scorer.py).

Validates that recommend_model_from_history() queries results.tsv pass rates
and returns the cheapest viable model tier.
"""

from __future__ import annotations

from pathlib import Path

from lib.routing.complexity_scorer import recommend_model_from_history


def _write_results_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a minimal results.tsv with the columns needed for history routing."""
    header = "story_id\tstatus\tmodel\testimated_complexity\n"
    lines = [header]
    for row in rows:
        lines.append(f"{row['story_id']}\t{row['status']}\t{row['model']}\t{row['complexity']}\n")
    path.write_text("".join(lines), encoding="utf-8")


class TestRecommendModelFromHistory:
    """Test historical model routing recommendations."""

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        result = recommend_model_from_history(
            estimated_complexity="medium",
            results_tsv_path=tmp_path / "nonexistent.tsv",
        )
        assert result is None

    def test_returns_none_when_insufficient_samples(self, tmp_path: Path) -> None:
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {"story_id": "US-1", "status": "pass", "model": "haiku", "complexity": "medium"},
                {"story_id": "US-2", "status": "pass", "model": "haiku", "complexity": "medium"},
            ],
        )
        result = recommend_model_from_history(
            estimated_complexity="medium",
            results_tsv_path=tsv,
            min_sample_size=3,
        )
        assert result is None

    def test_returns_cheapest_passing_model(self, tmp_path: Path) -> None:
        """When haiku has 80% pass rate, it should be recommended over sonnet."""
        tsv = tmp_path / "results.tsv"
        _write_results_tsv(
            tsv,
            [
                {"story_id": "US-1", "status": "pass", "model": "haiku", "complexity": "small"},
                {"story_id": "US-2", "status": "pass", "model": "haiku", "complexity": "small"},
                {"story_id": "US-3", "status": "pass", "model": "haiku", "complexity": "small"},
                {"story_id": "US-4", "status": "pass", "model": "haiku", "complexity": "small"},
                {"story_id": "US-5", "status": "reject", "model": "haiku", "complexity": "small"},
            ],
        )
        result = recommend_model_from_history(
            estimated_complexity="small",
            results_tsv_path=tsv,
        )
        assert result == "haiku"

    def test_skips_haiku_when_low_pass_rate(self, tmp_path: Path) -> None:
        """When haiku has 20% pass rate but sonnet has 90%, recommend sonnet."""
        tsv = tmp_path / "results.tsv"
        rows = [
            # haiku: 1 pass, 4 rejects = 20%
            {"story_id": "US-1", "status": "pass", "model": "haiku", "complexity": "large"},
            {"story_id": "US-2", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-3", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-4", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-5", "status": "reject", "model": "haiku", "complexity": "large"},
            # sonnet: 3 pass, 0 rejects = 100%
            {"story_id": "US-6", "status": "pass", "model": "sonnet", "complexity": "large"},
            {"story_id": "US-7", "status": "pass", "model": "sonnet", "complexity": "large"},
            {"story_id": "US-8", "status": "pass", "model": "sonnet", "complexity": "large"},
        ]
        _write_results_tsv(tsv, rows)
        result = recommend_model_from_history(
            estimated_complexity="large",
            results_tsv_path=tsv,
        )
        assert result == "sonnet"

    def test_filters_by_complexity_band(self, tmp_path: Path) -> None:
        """Only stories with matching complexity should be considered."""
        tsv = tmp_path / "results.tsv"
        rows = [
            # haiku great for small stories
            {"story_id": "US-1", "status": "pass", "model": "haiku", "complexity": "small"},
            {"story_id": "US-2", "status": "pass", "model": "haiku", "complexity": "small"},
            {"story_id": "US-3", "status": "pass", "model": "haiku", "complexity": "small"},
            # haiku bad for large stories
            {"story_id": "US-4", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-5", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-6", "status": "reject", "model": "haiku", "complexity": "large"},
            {"story_id": "US-7", "status": "pass", "model": "opus", "complexity": "large"},
            {"story_id": "US-8", "status": "pass", "model": "opus", "complexity": "large"},
            {"story_id": "US-9", "status": "pass", "model": "opus", "complexity": "large"},
        ]
        _write_results_tsv(tsv, rows)

        # For small: haiku should be recommended
        assert recommend_model_from_history("small", tsv) == "haiku"
        # For large: opus should be recommended (haiku has 0% pass rate)
        assert recommend_model_from_history("large", tsv) == "opus"

    def test_threshold_boundary(self, tmp_path: Path) -> None:
        """Pass rate exactly at threshold should be accepted."""
        tsv = tmp_path / "results.tsv"
        rows = [
            # haiku: 3 pass, 2 reject = 60% exactly
            {"story_id": "US-1", "status": "pass", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-2", "status": "pass", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-3", "status": "pass", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-4", "status": "reject", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-5", "status": "reject", "model": "haiku", "complexity": "medium"},
        ]
        _write_results_tsv(tsv, rows)
        result = recommend_model_from_history(
            estimated_complexity="medium",
            results_tsv_path=tsv,
            pass_rate_threshold=0.60,
        )
        assert result == "haiku"

    def test_returns_none_when_all_models_below_threshold(self, tmp_path: Path) -> None:
        """If no model meets the threshold, return None."""
        tsv = tmp_path / "results.tsv"
        rows = [
            {"story_id": "US-1", "status": "reject", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-2", "status": "reject", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-3", "status": "reject", "model": "haiku", "complexity": "medium"},
            {"story_id": "US-4", "status": "reject", "model": "sonnet", "complexity": "medium"},
            {"story_id": "US-5", "status": "reject", "model": "sonnet", "complexity": "medium"},
            {"story_id": "US-6", "status": "reject", "model": "sonnet", "complexity": "medium"},
        ]
        _write_results_tsv(tsv, rows)
        result = recommend_model_from_history(
            estimated_complexity="medium",
            results_tsv_path=tsv,
        )
        assert result is None

    def test_normalizes_full_model_ids(self, tmp_path: Path) -> None:
        """Full model IDs like 'claude-haiku-4-5-20251001' should normalize to 'haiku'."""
        tsv = tmp_path / "results.tsv"
        rows = [
            {"story_id": "US-1", "status": "pass", "model": "claude-haiku-4-5-20251001", "complexity": "small"},
            {"story_id": "US-2", "status": "pass", "model": "claude-haiku-4-5-20251001", "complexity": "small"},
            {"story_id": "US-3", "status": "pass", "model": "claude-haiku-4-5-20251001", "complexity": "small"},
        ]
        _write_results_tsv(tsv, rows)
        result = recommend_model_from_history("small", tsv)
        assert result == "haiku"
