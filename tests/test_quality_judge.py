"""Tests for lib/quality_judge.py — LLM-as-Judge quality evaluation (US-248).

Tests scoring, checkpoint storage, warning emission, and disable flag.
Does NOT invoke Claude CLI — uses monkeypatching to avoid network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from quality_judge import (
    _parse_score_json,
    _update_checkpoint_scores,
    cmd_judge_phase_i,
    cmd_judge_phase_r,
    cmd_show,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_args(**kwargs):
    """Build a simple argparse.Namespace-like object."""
    import argparse

    return argparse.Namespace(**kwargs)


def _write_research_output(tmp_path: Path, content: str = "story candidates") -> Path:
    p = tmp_path / "_research_output.json"
    p.write_text(json.dumps({"stories": [{"title": content}]}), encoding="utf-8")
    return p


def _write_prd(tmp_path: Path, stories: list[dict]) -> Path:
    p = tmp_path / "prd.json"
    p.write_text(json.dumps({"userStories": stories}), encoding="utf-8")
    return p


_GOOD_R_RESPONSE = json.dumps(
    {
        "relevance": 4,
        "completeness": 4,
        "score": 4.0,
        "rationale": "Research covers most required areas.",
    }
)

_LOW_R_RESPONSE = json.dumps(
    {
        "relevance": 2,
        "completeness": 1,
        "score": 1.5,
        "rationale": "Research is off-topic and sparse.",
    }
)

_GOOD_I_RESPONSE = json.dumps(
    {
        "criteria_coverage": 5,
        "quality": 4,
        "score": 4.5,
        "rationale": "All acceptance criteria are addressed cleanly.",
    }
)


# ── _parse_score_json ─────────────────────────────────────────────────────────


class TestParseScoreJson:
    def test_parses_plain_json(self) -> None:
        raw = '{"score": 3.5, "rationale": "ok"}'
        result = _parse_score_json(raw)
        assert result is not None
        assert result["score"] == 3.5

    def test_extracts_json_from_prose(self) -> None:
        raw = 'Here is my evaluation:\n{"score": 4, "rationale": "good"}\nEnd.'
        result = _parse_score_json(raw)
        assert result is not None
        assert result["score"] == 4

    def test_returns_none_for_empty(self) -> None:
        assert _parse_score_json("") is None
        assert _parse_score_json("no json here") is None

    def test_returns_none_for_invalid_json(self) -> None:
        assert _parse_score_json("{invalid}") is None


# ── _update_checkpoint_scores ─────────────────────────────────────────────────


class TestUpdateCheckpointScores:
    def test_creates_checkpoint_if_missing(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "checkpoint.json"
        _update_checkpoint_scores(str(ckpt), "R", {"score": 4.0, "rationale": "good"})
        data = json.loads(ckpt.read_text())
        assert "_qualityScores" in data
        assert data["_qualityScores"]["R"][0]["score"] == 4.0

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "checkpoint.json"
        _update_checkpoint_scores(str(ckpt), "R", {"score": 3.0})
        _update_checkpoint_scores(str(ckpt), "R", {"score": 4.5})
        data = json.loads(ckpt.read_text())
        assert len(data["_qualityScores"]["R"]) == 2

    def test_preserves_existing_checkpoint_data(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "checkpoint.json"
        ckpt.write_text(json.dumps({"iter": 5, "phase": "I"}))
        _update_checkpoint_scores(str(ckpt), "I", {"score": 3.5})
        data = json.loads(ckpt.read_text())
        assert data["iter"] == 5
        assert data["_qualityScores"]["I"][0]["score"] == 3.5

    def test_stores_multiple_phases_separately(self, tmp_path: Path) -> None:
        ckpt = tmp_path / "checkpoint.json"
        _update_checkpoint_scores(str(ckpt), "R", {"score": 4.0})
        _update_checkpoint_scores(str(ckpt), "I", {"score": 3.0})
        data = json.loads(ckpt.read_text())
        assert "R" in data["_qualityScores"]
        assert "I" in data["_qualityScores"]


# ── cmd_judge_phase_r ─────────────────────────────────────────────────────────


class TestJudgePhaseR:
    def test_scores_written_to_checkpoint(self, tmp_path: Path) -> None:
        research = _write_research_output(tmp_path)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(research),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        with patch("quality_judge._call_judge", return_value=_GOOD_R_RESPONSE):
            cmd_judge_phase_r(args)
        data = json.loads(ckpt.read_text())
        assert data["_qualityScores"]["R"][0]["score"] == 4.0
        assert "relevance" in data["_qualityScores"]["R"][0]
        assert "timestamp" in data["_qualityScores"]["R"][0]

    def test_skips_missing_research_output(self, tmp_path: Path, capsys) -> None:
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(tmp_path / "missing.json"),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        cmd_judge_phase_r(args)
        assert not ckpt.exists()

    def test_warns_when_score_below_threshold(self, tmp_path: Path, capsys) -> None:
        research = _write_research_output(tmp_path)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(research),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        with patch("quality_judge._call_judge", return_value=_LOW_R_RESPONSE):
            cmd_judge_phase_r(args)
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "1.5" in captured.err

    def test_no_warning_when_score_meets_threshold(self, tmp_path: Path, capsys) -> None:
        research = _write_research_output(tmp_path)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(research),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        with patch("quality_judge._call_judge", return_value=_GOOD_R_RESPONSE):
            cmd_judge_phase_r(args)
        captured = capsys.readouterr()
        assert "WARNING" not in captured.err

    def test_disabled_via_env_var(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("SPIRAL_QUALITY_JUDGE_DISABLE", "1")
        research = _write_research_output(tmp_path)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(research),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        with patch("quality_judge._call_judge") as mock_judge:
            cmd_judge_phase_r(args)
            mock_judge.assert_not_called()
        assert not ckpt.exists()

    def test_handles_unparseable_judge_response(self, tmp_path: Path) -> None:
        research = _write_research_output(tmp_path)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(
            research_output=str(research),
            checkpoint=str(ckpt),
            iteration=1,
            threshold=3.0,
        )
        with patch("quality_judge._call_judge", return_value="not json at all"):
            cmd_judge_phase_r(args)
        assert not ckpt.exists()


# ── cmd_judge_phase_i ─────────────────────────────────────────────────────────


class TestJudgePhaseI:
    def test_scores_written_to_checkpoint(self, tmp_path: Path) -> None:
        stories = [
            {"id": "US-1", "title": "Story 1", "passes": True, "acceptanceCriteria": ["AC1"]},
            {"id": "US-2", "title": "Story 2", "passes": False, "acceptanceCriteria": []},
        ]
        prd = _write_prd(tmp_path, stories)
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(prd=str(prd), checkpoint=str(ckpt), iteration=2, threshold=3.0)
        with patch("quality_judge._call_judge", return_value=_GOOD_I_RESPONSE):
            cmd_judge_phase_i(args)
        data = json.loads(ckpt.read_text())
        assert data["_qualityScores"]["I"][0]["score"] == 4.5
        assert data["_qualityScores"]["I"][0]["iteration"] == 2

    def test_handles_empty_prd(self, tmp_path: Path) -> None:
        prd = _write_prd(tmp_path, [])
        ckpt = tmp_path / "checkpoint.json"
        args = _make_args(prd=str(prd), checkpoint=str(ckpt), iteration=1, threshold=3.0)
        with patch("quality_judge._call_judge", return_value=_GOOD_I_RESPONSE):
            cmd_judge_phase_i(args)
        data = json.loads(ckpt.read_text())
        assert data["_qualityScores"]["I"][0]["pass_rate"] == 0


# ── cmd_show ──────────────────────────────────────────────────────────────────


class TestCmdShow:
    def test_shows_no_scores_message(self, tmp_path: Path, capsys) -> None:
        ckpt = tmp_path / "checkpoint.json"
        ckpt.write_text(json.dumps({}))
        cmd_show(_make_args(checkpoint=str(ckpt)))
        captured = capsys.readouterr()
        assert "No quality scores" in captured.out

    def test_displays_phase_averages(self, tmp_path: Path, capsys) -> None:
        ckpt = tmp_path / "checkpoint.json"
        ckpt.write_text(
            json.dumps(
                {
                    "_qualityScores": {
                        "R": [
                            {"score": 3.0, "rationale": "ok", "timestamp": "2026-03-16T00:00:00Z"},
                            {"score": 4.0, "rationale": "good", "timestamp": "2026-03-16T01:00:00Z"},
                        ],
                    }
                }
            )
        )
        cmd_show(_make_args(checkpoint=str(ckpt)))
        captured = capsys.readouterr()
        assert "Phase R" in captured.out
        assert "3.5" in captured.out  # average of 3.0 and 4.0
