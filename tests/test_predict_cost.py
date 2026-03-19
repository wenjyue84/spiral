"""Tests for lib/predict_cost.py — KNN-based story cost estimator."""

from __future__ import annotations

import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from predict_cost import KNNEstimator, main, predict_story

RESULTS_HEADER = [
    "timestamp",
    "spiral_iter",
    "ralph_iter",
    "story_id",
    "story_title",
    "status",
    "duration_sec",
    "model",
    "retry_num",
    "commit_sha",
]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_row(
    story_id: str = "US-001",
    story_title: str = "Test story",
    duration_sec: str = "300",
    model: str = "sonnet",
    status: str = "keep",
) -> dict[str, str]:
    return {
        "timestamp": "2026-03-13T10:00:00Z",
        "spiral_iter": "1",
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": story_title,
        "status": status,
        "duration_sec": duration_sec,
        "model": model,
        "retry_num": "0",
        "commit_sha": "abc123",
    }


def _write_results(path: object, rows: list[dict[str, str]]) -> None:
    with open(str(path), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_prd(path: object, stories: list[dict[str, object]]) -> None:
    prd = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }
    with open(str(path), "w", encoding="utf-8") as f:
        json.dump(prd, f)


# ── test_similar_story_lookup ────────────────────────────────────────────────


def test_similar_story_lookup(tmp_path: object) -> None:
    """KNN returns same-type stories as the nearest neighbors."""
    tsv = tmp_path / "results.tsv"  # type: ignore[operator]
    _write_results(
        tsv,
        [
            _make_row("US-001", "Run pytest unit tests for merge module", "200", "haiku"),
            _make_row("US-002", "Add pytest coverage for validate_stories", "220", "haiku"),
            _make_row("US-003", "Write bats regression tests for phase R", "180", "haiku"),
            _make_row("US-004", "Add hypothesis tests for edge cases", "210", "haiku"),
            _make_row("US-005", "Write test for cost projection", "195", "sonnet"),
            # Unrelated stories (non-test)
            _make_row("US-010", "Implement dashboard UI widget", "400", "sonnet"),
            _make_row("US-011", "Build WebSocket endpoint for workers", "350", "sonnet"),
        ],
    )

    estimator = KNNEstimator(k=3)
    estimator.fit(str(tsv))

    story = {"id": "US-999", "title": "Add pytest tests for new feature"}
    result = estimator.predict(story)

    assert "estimated_tokens" in result
    assert "estimated_cost" in result
    assert "confidence_pct" in result
    assert "similar_stories" in result

    # The nearest neighbors should be test-type stories (US-001..005)
    similar_ids = {s["story_id"] for s in result["similar_stories"]}
    test_ids = {"US-001", "US-002", "US-003", "US-004", "US-005"}
    # All returned similar stories should be from the test group
    assert similar_ids.issubset(test_ids), (
        f"Expected neighbors from test stories, got: {similar_ids}"
    )

    assert result["estimated_tokens"] > 0
    assert result["estimated_cost"] > 0.0


def test_similar_story_lookup_returns_k_neighbors(tmp_path: object) -> None:
    """predict() returns at most k similar stories."""
    tsv = tmp_path / "results.tsv"  # type: ignore[operator]
    rows = [
        _make_row(f"US-{i:03d}", f"Run pytest test #{i}", "200", "haiku")
        for i in range(1, 10)
    ]
    _write_results(tsv, rows)

    estimator = KNNEstimator(k=3)
    estimator.fit(str(tsv))

    result = estimator.predict({"id": "US-999", "title": "Add more pytest tests"})
    assert len(result["similar_stories"]) <= 3


# ── test_confidence_calculation ──────────────────────────────────────────────


def test_confidence_calculation(tmp_path: object) -> None:
    """Confidence increases with more data and same-type neighbors."""
    tsv_small = tmp_path / "small.tsv"  # type: ignore[operator]
    tsv_large = tmp_path / "large.tsv"  # type: ignore[operator]

    # Small consistent dataset (exactly MIN_HISTORY_ROWS = 5)
    _write_results(
        tsv_small,
        [
            _make_row(f"US-{i:03d}", f"Run pytest tests #{i}", "200", "haiku")
            for i in range(1, 6)
        ],
    )

    # Large consistent dataset (20+ rows)
    _write_results(
        tsv_large,
        [
            _make_row(f"US-{i:03d}", f"Run pytest tests #{i}", "200", "haiku")
            for i in range(1, 21)
        ],
    )

    story = {"id": "US-999", "title": "Add pytest regression tests"}

    est_small = KNNEstimator(k=3)
    est_small.fit(str(tsv_small))
    result_small = est_small.predict(story)

    est_large = KNNEstimator(k=3)
    est_large.fit(str(tsv_large))
    result_large = est_large.predict(story)

    assert 0.0 <= result_small["confidence_pct"] <= 100.0
    assert 0.0 <= result_large["confidence_pct"] <= 100.0
    # More history → equal or higher confidence
    assert result_large["confidence_pct"] >= result_small["confidence_pct"]


def test_confidence_lower_with_mixed_types(tmp_path: object) -> None:
    """Confidence is lower when neighbors are all different types from the query."""
    tsv = tmp_path / "results.tsv"  # type: ignore[operator]

    # All non-test stories, but query is test-type
    _write_results(
        tsv,
        [
            _make_row("US-001", "Implement dashboard UI widget", "300", "sonnet"),
            _make_row("US-002", "Build WebSocket endpoint", "320", "sonnet"),
            _make_row("US-003", "Add otel tracing spans", "280", "sonnet"),
            _make_row("US-004", "Implement schema validation", "350", "sonnet"),
            _make_row("US-005", "Deploy to production infra", "310", "sonnet"),
        ],
    )

    estimator = KNNEstimator(k=3)
    estimator.fit(str(tsv))

    result_mismatched = estimator.predict(
        {"id": "US-999", "title": "Write pytest tests for coverage"}
    )
    result_matched = estimator.predict(
        {"id": "US-998", "title": "Build dashboard UI for real-time metrics"}
    )

    # When types don't match, confidence should be lower
    assert result_mismatched["confidence_pct"] <= result_matched["confidence_pct"]


# ── Low-data edge cases ─────────────────────────────────────────────────────


def test_fewer_than_min_rows_returns_zero_confidence(tmp_path: object) -> None:
    """When results.tsv has fewer than MIN_HISTORY_ROWS (5) rows, confidence=0.0 and similar_stories=[]."""
    tsv = tmp_path / "results.tsv"  # type: ignore[operator]
    _write_results(
        tsv,
        [
            _make_row("US-001", "Run pytest tests", "200"),
            _make_row("US-002", "Run more tests", "220"),
        ],
    )

    estimator = KNNEstimator()
    estimator.fit(str(tsv))

    result = estimator.predict({"id": "US-999", "title": "Add tests"})

    assert result["confidence_pct"] == 0.0
    assert result["similar_stories"] == []


def test_missing_history_file_returns_zero_confidence(tmp_path: object) -> None:
    """When results.tsv does not exist, returns zero-confidence estimate."""
    estimator = KNNEstimator()
    estimator.fit(str(tmp_path / "nonexistent.tsv"))  # type: ignore[operator]

    result = estimator.predict({"id": "US-999", "title": "Add tests"})

    assert result["confidence_pct"] == 0.0
    assert result["similar_stories"] == []
    assert result["estimated_tokens"] == 0


# ── CLI tests ────────────────────────────────────────────────────────────────


def test_cli_exits_zero_and_prints_json(tmp_path: object) -> None:
    """CLI exits 0 and prints valid JSON with required keys."""
    import io
    from contextlib import redirect_stdout

    tsv = tmp_path / "results.tsv"  # type: ignore[operator]
    _write_results(
        tsv,
        [
            _make_row(f"US-{i:03d}", f"Run pytest tests #{i}", "200", "haiku")
            for i in range(1, 10)
        ],
    )

    prd_path = tmp_path / "prd.json"  # type: ignore[operator]
    _write_prd(
        prd_path,
        [
            {
                "id": "US-001",
                "title": "Run pytest tests for merge",
                "passes": False,
            }
        ],
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(
            [
                "--story-id",
                "US-001",
                "--prd",
                str(prd_path),
                "--history",
                str(tsv),
            ]
        )

    output = buf.getvalue()
    result = json.loads(output)

    assert "estimated_tokens" in result
    assert "estimated_cost" in result
    assert "confidence_pct" in result
    assert "similar_stories" in result


def test_predict_story_raises_on_missing_prd(tmp_path: object) -> None:
    """predict_story() raises FileNotFoundError when prd.json doesn't exist."""
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        predict_story(
            "US-001",
            str(tmp_path / "no_prd.json"),  # type: ignore[operator]
            str(tmp_path / "no.tsv"),  # type: ignore[operator]
        )


def test_predict_story_raises_on_missing_story_id(tmp_path: object) -> None:
    """predict_story() raises ValueError when story ID is not in prd.json."""
    prd_path = tmp_path / "prd.json"  # type: ignore[operator]
    _write_prd(prd_path, [{"id": "US-001", "title": "Something", "passes": False}])
    tsv = tmp_path / "results.tsv"  # type: ignore[operator]
    _write_results(tsv, [])

    with pytest.raises(ValueError, match="US-999"):
        predict_story("US-999", str(prd_path), str(tsv))
