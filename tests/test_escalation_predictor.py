"""tests/test_escalation_predictor.py — Integration tests for US-1058.

Tests the model escalation predictor against a synthetic 5-story progression
chain (haiku→sonnet→opus) to verify >85% confidence on obvious progressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.escalation_predictor import (
    HAIKU_TO_SONNET_THRESHOLD,
    SONNET_TO_OPUS_THRESHOLD,
    EscalationPrediction,
    predict_all_stories,
    predict_for_story,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TSV_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\t"
    "duration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit\t"
    "cache_read_tokens\tcache_creation_tokens\treview_tokens\t"
    "wall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
)


def _make_row(
    story_id: str,
    model: str,
    retry_num: int,
    cache_read: int = 0,
    cache_create: int = 0,
    review: int = 0,
) -> str:
    return (
        f"2026-01-01T00:00:00Z\t1\t1\t{story_id}\tTitle\tpass\t10\t"
        f"{model}\t{retry_num}\t\t\tfalse\t"
        f"{cache_read}\t{cache_create}\t{review}\t"
        f"0\t0\t0\t0\t\n"
    )


def _write_tsv(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "results.tsv"
    p.write_text(TSV_HEADER + "".join(rows), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# AC1 — CLI reads results.tsv and predicts model for given story
# ---------------------------------------------------------------------------


class TestPredictForStory:
    def test_no_data_returns_none(self, tmp_path: Path) -> None:
        tsv = _write_tsv(tmp_path, [])
        result = predict_for_story("US-999", tsv)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = predict_for_story("US-999", tmp_path / "nonexistent.tsv")
        assert result is None

    def test_haiku_below_threshold_stays_haiku(self, tmp_path: Path) -> None:
        """Story with low token usage stays on haiku."""
        rows = [
            _make_row("US-1", "haiku", 0, cache_read=5_000),
            _make_row("US-1", "haiku", 1, cache_read=8_000),
        ]
        tsv = _write_tsv(tmp_path, rows)
        pred = predict_for_story("US-1", tsv)
        assert pred is not None
        assert pred.current_model == "haiku"
        assert pred.predicted_model == "haiku"
        assert pred.tokens_until_escalation > 0

    def test_haiku_above_threshold_predicts_sonnet(self, tmp_path: Path) -> None:
        """Story with accelerating tokens predicts sonnet escalation."""
        # Trend: 20K → 45K → clearly heading past 50K threshold
        rows = [
            _make_row("US-2", "haiku", 0, cache_read=20_000),
            _make_row("US-2", "haiku", 1, cache_read=45_000),
        ]
        tsv = _write_tsv(tmp_path, rows)
        pred = predict_for_story("US-2", tsv)
        assert pred is not None
        assert pred.current_model == "haiku"
        assert pred.predicted_model == "sonnet"

    def test_sonnet_above_threshold_predicts_opus(self, tmp_path: Path) -> None:
        """Story already on sonnet with high tokens predicts opus."""
        rows = [
            _make_row("US-3", "sonnet", 1, cache_read=100_000),
            _make_row("US-3", "sonnet", 2, cache_read=145_000),
        ]
        tsv = _write_tsv(tmp_path, rows)
        pred = predict_for_story("US-3", tsv)
        assert pred is not None
        assert pred.current_model == "sonnet"
        assert pred.predicted_model == "opus"

    def test_opus_stays_opus(self, tmp_path: Path) -> None:
        """Story already on opus: no further escalation possible."""
        rows = [_make_row("US-4", "opus", 2, cache_read=200_000)]
        tsv = _write_tsv(tmp_path, rows)
        pred = predict_for_story("US-4", tsv)
        assert pred is not None
        assert pred.current_model == "opus"
        assert pred.predicted_model == "opus"
        assert pred.confidence_pct == 100.0


# ---------------------------------------------------------------------------
# AC3 — 5-story progression chain: verify >85% confidence on obvious escalations
# ---------------------------------------------------------------------------


class TestFiveStoryProgressionChain:
    """Integration test: feed obvious haiku→sonnet→opus progressions, verify
    the predictor identifies each escalation with >85% confidence."""

    @pytest.fixture()
    def progression_tsv(self, tmp_path: Path) -> Path:
        """Build a TSV with 5 stories at different stages of escalation:

        US-P1: haiku, clearly heading to sonnet (50K+ on next attempt)
        US-P2: haiku, heading to sonnet with high confidence
        US-P3: sonnet, clearly heading to opus (150K+ on next attempt)
        US-P4: sonnet, heading to opus with high confidence
        US-P5: opus, already at ceiling
        """
        rows = [
            # US-P1: haiku, attempt 0→1 trending 30K→55K (next ~80K, past 50K threshold)
            _make_row("US-P1", "haiku", 0, cache_read=30_000),
            _make_row("US-P1", "haiku", 1, cache_read=55_000),
            # US-P2: haiku, 10K→35K→60K strong trend
            _make_row("US-P2", "haiku", 0, cache_read=10_000),
            _make_row("US-P2", "haiku", 1, cache_read=35_000),
            _make_row("US-P2", "haiku", 2, cache_read=60_000),
            # US-P3: sonnet, 80K→130K→180K — next attempt beyond 150K opus threshold
            _make_row("US-P3", "sonnet", 1, cache_read=80_000),
            _make_row("US-P3", "sonnet", 2, cache_read=130_000),
            _make_row("US-P3", "sonnet", 3, cache_read=180_000),
            # US-P4: sonnet, 100K→155K clear overshoot
            _make_row("US-P4", "sonnet", 1, cache_read=100_000),
            _make_row("US-P4", "sonnet", 2, cache_read=155_000),
            # US-P5: already at opus
            _make_row("US-P5", "opus", 3, cache_read=210_000),
        ]
        return _write_tsv(tmp_path, rows)

    def _get_pred(self, preds: list[EscalationPrediction], sid: str) -> EscalationPrediction:
        matches = [p for p in preds if p.story_id == sid]
        assert matches, f"No prediction for {sid}"
        return matches[0]

    def test_escalating_stories_predicted_with_high_confidence(
        self, progression_tsv: Path
    ) -> None:
        """Each obviously escalating story should be predicted with >85% confidence."""
        preds = predict_all_stories(progression_tsv)
        assert len(preds) == 5

        # US-P1 and US-P2: haiku → sonnet
        for sid in ("US-P1", "US-P2"):
            p = self._get_pred(preds, sid)
            assert p.current_model == "haiku", f"{sid}: expected haiku"
            assert p.predicted_model == "sonnet", f"{sid}: should escalate to sonnet"
            assert p.confidence_pct > 85.0, (
                f"{sid}: confidence {p.confidence_pct:.1f}% should be >85%"
            )

        # US-P3 and US-P4: sonnet → opus
        for sid in ("US-P3", "US-P4"):
            p = self._get_pred(preds, sid)
            assert p.current_model == "sonnet", f"{sid}: expected sonnet"
            assert p.predicted_model == "opus", f"{sid}: should escalate to opus"
            assert p.confidence_pct > 85.0, (
                f"{sid}: confidence {p.confidence_pct:.1f}% should be >85%"
            )

        # US-P5: already at opus — no escalation
        p5 = self._get_pred(preds, "US-P5")
        assert p5.current_model == "opus"
        assert p5.predicted_model == "opus"

    def test_escalating_stories_sorted_first(self, progression_tsv: Path) -> None:
        """Escalating stories appear before stable stories in the result list."""
        preds = predict_all_stories(progression_tsv)
        escalating = [p for p in preds if p.predicted_model != p.current_model]
        stable = [p for p in preds if p.predicted_model == p.current_model]

        # All escalating predictions should come before stable ones
        if escalating and stable:
            last_escalating_idx = max(preds.index(p) for p in escalating)
            first_stable_idx = min(preds.index(p) for p in stable)
            assert last_escalating_idx < first_stable_idx, (
                "Escalating stories should be sorted before stable stories"
            )

    def test_tokens_until_escalation_correct(self, progression_tsv: Path) -> None:
        """tokens_until_escalation should reflect distance from last recorded tokens."""
        preds = predict_all_stories(progression_tsv)

        # US-P1 last tokens = 55K; threshold = 50K → already past, so 0
        p1 = self._get_pred(preds, "US-P1")
        # Already past haiku→sonnet threshold
        assert p1.tokens_until_escalation == 0

        # US-P5 is at opus → tokens_until = 0
        p5 = self._get_pred(preds, "US-P5")
        assert p5.tokens_until_escalation == 0


# ---------------------------------------------------------------------------
# Threshold constants
# ---------------------------------------------------------------------------


class TestThresholds:
    def test_haiku_sonnet_threshold(self) -> None:
        assert HAIKU_TO_SONNET_THRESHOLD == 50_000

    def test_sonnet_opus_threshold(self) -> None:
        assert SONNET_TO_OPUS_THRESHOLD == 150_000
