"""Unit tests for lib/cost_project.py — pre-flight cost projection."""
import csv
import json
import os
import sys
from io import StringIO
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cost_project import (
    MIN_HISTORY_ROWS,
    DEFAULT_TOKENS_PER_STORY,
    PRICING,
    compute_mean_tokens,
    count_pending,
    format_table,
    normalise_model,
    project_cost,
    run_projection,
    main,
)

RESULTS_HEADER = [
    "timestamp", "spiral_iter", "ralph_iter", "story_id", "story_title",
    "status", "duration_sec", "model", "retry_num", "commit_sha",
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _write_results(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_row(duration_sec="300", model="sonnet", story_id="US-001", status="keep"):
    return {
        "timestamp": "2026-03-13T10:00:00Z",
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": "Test story",
        "status": status,
        "duration_sec": str(duration_sec),
        "model": model,
        "retry_num": "0",
        "commit_sha": "abc123",
    }


def _write_prd(path, stories):
    prd = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prd, f)


# ── normalise_model ────────────────────────────────────────────────────────

class TestNormaliseModel:
    def test_haiku(self):
        assert normalise_model("claude-haiku-4-5") == "haiku"

    def test_sonnet(self):
        assert normalise_model("claude-sonnet-4-6") == "sonnet"

    def test_opus(self):
        assert normalise_model("claude-opus-4-6") == "opus"

    def test_empty_falls_back_to_sonnet(self):
        assert normalise_model("") == "sonnet"

    def test_unknown_falls_back_to_sonnet(self):
        assert normalise_model("gpt-4") == "sonnet"


# ── project_cost ───────────────────────────────────────────────────────────

class TestProjectCost:
    def test_zero_tokens_is_zero(self):
        assert project_cost(0, "sonnet") == 0.0

    def test_positive_cost(self):
        cost = project_cost(1_000_000, "sonnet")
        assert cost > 0

    def test_haiku_cheaper_than_sonnet(self):
        assert project_cost(1_000_000, "haiku") < project_cost(1_000_000, "sonnet")

    def test_sonnet_cheaper_than_opus(self):
        assert project_cost(1_000_000, "sonnet") < project_cost(1_000_000, "opus")


# ── compute_mean_tokens ────────────────────────────────────────────────────

class TestComputeMeanTokens:
    def test_missing_file_returns_zeros(self, tmp_path):
        mean, std, count = compute_mean_tokens(str(tmp_path / "no.tsv"))
        assert (mean, std, count) == (0.0, 0.0, 0)

    def test_empty_file_returns_zeros(self, tmp_path):
        p = tmp_path / "results.tsv"
        _write_results(p, [])
        mean, std, count = compute_mean_tokens(str(p))
        assert (mean, std, count) == (0.0, 0.0, 0)

    def test_rows_with_zero_duration_excluded(self, tmp_path):
        p = tmp_path / "results.tsv"
        _write_results(p, [_make_row(duration_sec="0")])
        mean, std, count = compute_mean_tokens(str(p))
        assert count == 0

    def test_single_row_std_zero(self, tmp_path):
        p = tmp_path / "results.tsv"
        _write_results(p, [_make_row(duration_sec="100")])
        mean, std, count = compute_mean_tokens(str(p))
        assert count == 1
        assert mean > 0
        assert std == 0.0

    def test_multiple_rows_correct_count(self, tmp_path):
        p = tmp_path / "results.tsv"
        _write_results(p, [_make_row(duration_sec=str(d)) for d in [100, 200, 300, 400, 500]])
        mean, std, count = compute_mean_tokens(str(p))
        assert count == 5
        assert mean > 0
        assert std > 0

    def test_mean_scales_with_duration(self, tmp_path):
        p1 = tmp_path / "r1.tsv"
        p2 = tmp_path / "r2.tsv"
        _write_results(p1, [_make_row(duration_sec="100")])
        _write_results(p2, [_make_row(duration_sec="200")])
        mean1, _, _ = compute_mean_tokens(str(p1))
        mean2, _, _ = compute_mean_tokens(str(p2))
        assert abs(mean2 / mean1 - 2.0) < 0.001


# ── count_pending ──────────────────────────────────────────────────────────

class TestCountPending:
    def test_missing_prd_returns_zero(self, tmp_path):
        assert count_pending(str(tmp_path / "no.json")) == 0

    def test_all_passed(self, tmp_path):
        p = tmp_path / "prd.json"
        _write_prd(p, [{"id": "US-001", "passes": True}])
        assert count_pending(str(p)) == 0

    def test_skipped_excluded(self, tmp_path):
        p = tmp_path / "prd.json"
        _write_prd(p, [{"id": "US-001", "passes": False, "_skipped": True}])
        assert count_pending(str(p)) == 0

    def test_decomposed_excluded(self, tmp_path):
        p = tmp_path / "prd.json"
        _write_prd(p, [{"id": "US-001", "passes": False, "_decomposed": True}])
        assert count_pending(str(p)) == 0

    def test_pending_counted(self, tmp_path):
        p = tmp_path / "prd.json"
        _write_prd(p, [
            {"id": "US-001", "passes": True},
            {"id": "US-002", "passes": False},
            {"id": "US-003", "passes": False},
        ])
        assert count_pending(str(p)) == 2

    def test_empty_prd(self, tmp_path):
        p = tmp_path / "prd.json"
        _write_prd(p, [])
        assert count_pending(str(p)) == 0


# ── format_table ───────────────────────────────────────────────────────────

class TestFormatTable:
    def test_returns_non_empty_string(self):
        table_str, est_usd = format_table(
            pending_count=5, model="sonnet", mean_tokens=8000.0,
            std_tokens=1000.0, row_count=10, default_tokens=8000,
        )
        assert len(table_str) > 0
        assert est_usd > 0

    def test_shows_pending_count(self):
        table_str, _ = format_table(
            pending_count=7, model="sonnet", mean_tokens=8000.0,
            std_tokens=0, row_count=10, default_tokens=8000,
        )
        assert "7" in table_str

    def test_shows_model_name(self):
        table_str, _ = format_table(
            pending_count=1, model="haiku", mean_tokens=8000.0,
            std_tokens=0, row_count=10, default_tokens=8000,
        )
        assert "haiku" in table_str

    def test_confidence_range_shown_with_std(self):
        table_str, _ = format_table(
            pending_count=5, model="sonnet", mean_tokens=8000.0,
            std_tokens=2000.0, row_count=10, default_tokens=8000,
        )
        assert "σ" in table_str or "–" in table_str

    def test_no_confidence_range_without_std(self):
        table_str, _ = format_table(
            pending_count=5, model="sonnet", mean_tokens=8000.0,
            std_tokens=0.0, row_count=10, default_tokens=8000,
        )
        assert "σ" not in table_str


# ── run_projection (integration) ───────────────────────────────────────────

class TestRunProjection:
    def _make_results_with_rows(self, tmp_path, n_rows, duration=300):
        p = tmp_path / "results.tsv"
        _write_results(p, [_make_row(duration_sec=str(duration), story_id=f"US-{i:03d}") for i in range(n_rows)])
        return str(p)

    def _make_prd_file(self, tmp_path, n_pending=3):
        p = tmp_path / "prd.json"
        stories = [{"id": f"US-{i:03d}", "passes": False} for i in range(n_pending)]
        _write_prd(p, stories)
        return str(p)

    # ── Skip conditions ────────────────────────────────────────────────────

    def test_skip_when_fewer_than_5_rows(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 4)
        prd = self._make_prd_file(tmp_path)
        rc = run_projection(prd, results, "sonnet", 5.00, True, DEFAULT_TOKENS_PER_STORY)
        assert rc == 2
        out = capsys.readouterr().out
        # No table should be printed
        assert "Pre-flight" not in out

    def test_skip_when_results_missing(self, tmp_path, capsys):
        prd = self._make_prd_file(tmp_path)
        rc = run_projection(prd, str(tmp_path / "no.tsv"), "sonnet", 5.00, True, DEFAULT_TOKENS_PER_STORY)
        assert rc == 2

    def test_proceed_when_zero_pending(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 10)
        p = tmp_path / "prd.json"
        _write_prd(p, [{"id": "US-001", "passes": True}])
        rc = run_projection(str(p), results, "sonnet", 5.00, True, DEFAULT_TOKENS_PER_STORY)
        assert rc == 0

    # ── Table display ──────────────────────────────────────────────────────

    def test_table_printed_with_sufficient_history(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 10)
        prd = self._make_prd_file(tmp_path)
        run_projection(prd, results, "sonnet", 0.0, True, DEFAULT_TOKENS_PER_STORY)
        out = capsys.readouterr().out
        assert "Pre-flight" in out
        assert "sonnet" in out

    # ── Threshold prompting ────────────────────────────────────────────────

    def test_no_prompt_when_cost_below_threshold(self, tmp_path, capsys):
        # Very short duration → tiny cost; high threshold
        results = self._make_results_with_rows(tmp_path, 10, duration=1)
        prd = self._make_prd_file(tmp_path, n_pending=1)
        rc = run_projection(prd, results, "haiku", 100.0, False, DEFAULT_TOKENS_PER_STORY)
        assert rc == 0

    def test_yes_flag_skips_prompt(self, tmp_path, capsys):
        # Force a large cost (long duration, many pending, opus)
        results = self._make_results_with_rows(tmp_path, 10, duration=3600)
        prd = self._make_prd_file(tmp_path, n_pending=50)
        rc = run_projection(prd, results, "opus", 0.01, yes=True, default_tokens=DEFAULT_TOKENS_PER_STORY)
        assert rc == 0
        out = capsys.readouterr().out
        assert "--yes flag set" in out

    def test_user_answers_yes_returns_0(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 10, duration=3600)
        prd = self._make_prd_file(tmp_path, n_pending=50)
        with patch("builtins.input", return_value="y"):
            rc = run_projection(prd, results, "opus", 0.01, yes=False, default_tokens=DEFAULT_TOKENS_PER_STORY)
        assert rc == 0

    def test_user_answers_no_returns_1(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 10, duration=3600)
        prd = self._make_prd_file(tmp_path, n_pending=50)
        with patch("builtins.input", return_value="n"):
            rc = run_projection(prd, results, "opus", 0.01, yes=False, default_tokens=DEFAULT_TOKENS_PER_STORY)
        assert rc == 1

    def test_eof_on_prompt_returns_1(self, tmp_path, capsys):
        results = self._make_results_with_rows(tmp_path, 10, duration=3600)
        prd = self._make_prd_file(tmp_path, n_pending=50)
        with patch("builtins.input", side_effect=EOFError):
            rc = run_projection(prd, results, "opus", 0.01, yes=False, default_tokens=DEFAULT_TOKENS_PER_STORY)
        assert rc == 1

    # ── Error handling ─────────────────────────────────────────────────────

    def test_corrupt_prd_returns_3(self, tmp_path):
        p = tmp_path / "prd.json"
        p.write_text("not json", encoding="utf-8")
        results = self._make_results_with_rows(tmp_path, 10)
        rc = run_projection(str(p), results, "sonnet", 5.0, True, DEFAULT_TOKENS_PER_STORY)
        assert rc == 3


# ── main() CLI ─────────────────────────────────────────────────────────────

class TestMainCli:
    def test_main_returns_2_for_insufficient_history(self, tmp_path, capsys):
        prd = tmp_path / "prd.json"
        _write_prd(prd, [{"id": "US-001", "passes": False}])
        results = tmp_path / "results.tsv"
        _write_results(results, [_make_row(duration_sec="100")])  # only 1 row < 5
        rc = main(["--prd", str(prd), "--results", str(results)])
        assert rc == 2

    def test_main_yes_flag_accepted(self, tmp_path, capsys):
        """--yes flag prevents interactive prompt when cost exceeds threshold."""
        prd = tmp_path / "prd.json"
        _write_prd(prd, [{"id": f"US-{i:03d}", "passes": False} for i in range(50)])
        results = tmp_path / "results.tsv"
        _write_results(results, [_make_row(duration_sec="3600", model="opus") for _ in range(10)])
        rc = main(["--prd", str(prd), "--results", str(results), "--model", "opus",
                   "--threshold", "0.01", "--yes"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "--yes flag set" in out

    def test_main_default_tokens_flag(self, tmp_path, capsys):
        """--default-tokens is accepted and uses default when < MIN_HISTORY_ROWS."""
        prd = tmp_path / "prd.json"
        _write_prd(prd, [{"id": "US-001", "passes": False}])
        results = tmp_path / "results.tsv"
        _write_results(results, [])  # 0 rows
        rc = main(["--prd", str(prd), "--results", str(results),
                   "--default-tokens", "5000"])
        assert rc == 2  # skipped due to insufficient history
