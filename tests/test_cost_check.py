"""Unit tests for lib/cost_check.py — cumulative API cost estimation."""
import csv
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cost_check import (
    compute_cumulative_cost,
    compute_row_cost,
    estimate_tokens_from_duration,
    format_cost_summary,
    main,
    normalise_model,
    PRICING,
    TOKENS_PER_SEC_OUTPUT,
    INPUT_OUTPUT_RATIO,
)

HEADER = [
    "timestamp", "spiral_iter", "ralph_iter", "story_id", "story_title",
    "status", "duration_sec", "model", "retry_num", "commit_sha",
]


def _write_tsv(path, rows):
    """Helper: write a results.tsv file with given row dicts."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_row(model="sonnet", duration_sec="300", story_id="US-001", status="keep"):
    return {
        "timestamp": "2026-03-13T10:00:00",
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


class TestNormaliseModel:
    def test_haiku(self):
        assert normalise_model("haiku") == "haiku"

    def test_sonnet_with_version(self):
        assert normalise_model("claude-sonnet-4-20250514") == "sonnet"

    def test_opus(self):
        assert normalise_model("opus") == "opus"

    def test_empty_defaults_to_sonnet(self):
        assert normalise_model("") == "sonnet"

    def test_none_defaults_to_sonnet(self):
        assert normalise_model(None) == "sonnet"

    def test_unknown_defaults_to_sonnet(self):
        assert normalise_model("gpt-4") == "sonnet"


class TestEstimateTokens:
    def test_zero_duration(self):
        inp, out = estimate_tokens_from_duration(0)
        assert inp == 0.0
        assert out == 0.0

    def test_positive_duration(self):
        inp, out = estimate_tokens_from_duration(100)
        assert out == 100 * TOKENS_PER_SEC_OUTPUT
        assert inp == out * INPUT_OUTPUT_RATIO


class TestComputeRowCost:
    def test_haiku_300s(self):
        row = _make_row(model="haiku", duration_sec="300")
        cost = compute_row_cost(row)
        # 300s * 20 tok/s = 6000 output tokens, 18000 input tokens
        # haiku: 18000/1M * 0.80 + 6000/1M * 4.00 = 0.0144 + 0.024 = 0.0384
        expected = (18000 / 1e6) * 0.80 + (6000 / 1e6) * 4.00
        assert abs(cost - expected) < 1e-10

    def test_sonnet_300s(self):
        row = _make_row(model="sonnet", duration_sec="300")
        cost = compute_row_cost(row)
        expected = (18000 / 1e6) * 3.00 + (6000 / 1e6) * 15.00
        assert abs(cost - expected) < 1e-10

    def test_opus_300s(self):
        row = _make_row(model="opus", duration_sec="300")
        cost = compute_row_cost(row)
        expected = (18000 / 1e6) * 15.00 + (6000 / 1e6) * 75.00
        assert abs(cost - expected) < 1e-10

    def test_zero_duration(self):
        row = _make_row(duration_sec="0")
        assert compute_row_cost(row) == 0.0

    def test_bad_duration(self):
        row = _make_row(duration_sec="not-a-number")
        assert compute_row_cost(row) == 0.0


class TestComputeCumulativeCost:
    def test_missing_file(self, tmp_path):
        total, count = compute_cumulative_cost(str(tmp_path / "nonexistent.tsv"))
        assert total == 0.0
        assert count == 0

    def test_single_row(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        _write_tsv(str(tsv), [_make_row(model="haiku", duration_sec="300")])
        total, count = compute_cumulative_cost(str(tsv))
        assert count == 1
        assert total > 0

    def test_multiple_rows(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        rows = [
            _make_row(model="haiku", duration_sec="300", story_id="US-001"),
            _make_row(model="sonnet", duration_sec="600", story_id="US-002"),
            _make_row(model="opus", duration_sec="120", story_id="US-003"),
        ]
        _write_tsv(str(tsv), rows)
        total, count = compute_cumulative_cost(str(tsv))
        assert count == 3
        # Verify total is sum of individual costs
        expected = sum(compute_row_cost(r) for r in rows)
        assert abs(total - expected) < 1e-10

    def test_known_token_counts(self, tmp_path):
        """Mock results.tsv with known durations and verify cost matches hand-calculated USD."""
        tsv = tmp_path / "results.tsv"
        # 5 haiku attempts at 300s each: 5 * 0.0384 = 0.192
        rows = [_make_row(model="haiku", duration_sec="300", story_id=f"US-{i:03d}") for i in range(5)]
        _write_tsv(str(tsv), rows)
        total, count = compute_cumulative_cost(str(tsv))
        assert count == 5
        single_cost = (18000 / 1e6) * 0.80 + (6000 / 1e6) * 4.00
        assert abs(total - 5 * single_cost) < 1e-10


class TestFormatCostSummary:
    def test_no_ceiling(self):
        out = format_cost_summary(1.23, 10, None)
        assert "$1.23" in out
        assert "10 attempts" in out
        assert "ceiling" not in out.lower()

    def test_with_ceiling(self):
        out = format_cost_summary(5.00, 20, 50.0)
        assert "$5.00" in out
        assert "$50.00" in out
        assert "$45.00" in out  # remaining


class TestMain:
    def test_under_ceiling(self, tmp_path, capsys):
        tsv = tmp_path / "results.tsv"
        _write_tsv(str(tsv), [_make_row(model="haiku", duration_sec="300")])
        rc = main(["--results", str(tsv), "--ceiling", "100.0"])
        assert rc == 0

    def test_over_ceiling(self, tmp_path, capsys):
        tsv = tmp_path / "results.tsv"
        # 1000 opus rows at 600s each — should exceed $0.01 ceiling easily
        rows = [_make_row(model="opus", duration_sec="600", story_id=f"US-{i:03d}") for i in range(100)]
        _write_tsv(str(tsv), rows)
        rc = main(["--results", str(tsv), "--ceiling", "0.01"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "BUDGET EXCEEDED" in captured.out

    def test_no_ceiling_always_passes(self, tmp_path):
        tsv = tmp_path / "results.tsv"
        rows = [_make_row(model="opus", duration_sec="600", story_id=f"US-{i:03d}") for i in range(100)]
        _write_tsv(str(tsv), rows)
        rc = main(["--results", str(tsv)])
        assert rc == 0

    def test_missing_file_returns_0(self, tmp_path):
        rc = main(["--results", str(tmp_path / "nope.tsv")])
        assert rc == 0
