"""Tests for GET /api/dashboard/cost-history endpoint (US-645)."""

import csv

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app
from lib.results_tsv import HEADER

client = TestClient(app)


def _make_tsv(tmp_path, rows):  # type: ignore[no-untyped-def]
    p = tmp_path / "results.tsv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in HEADER})
    return p


def _row(
    story_id: str = "US-001",
    spiral_iter: str = "1",
    model: str = "haiku",
    read: int = 1000,
    creation: int = 500,
    review: int = 200,
) -> dict:  # type: ignore[type-arg]
    return {
        "timestamp": "2024-01-01T00:00:00",
        "spiral_iter": spiral_iter,
        "ralph_iter": "1",
        "story_id": story_id,
        "story_title": "Test Story",
        "status": "pass",
        "duration_sec": "10",
        "model": model,
        "retry_num": "0",
        "commit_sha": "abc123",
        "run_id": "1",
        "cache_read_tokens": str(read),
        "cache_creation_tokens": str(creation),
        "review_tokens": str(review),
    }


def test_cost_history_empty(
    tmp_path: pytest.fixture,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[valid-type]
) -> None:
    """Empty results.tsv → history list is empty."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.tsv").write_text("", encoding="utf-8")
    resp = client.get("/api/dashboard/cost-history")
    assert resp.status_code == 200
    assert resp.json()["history"] == []


def test_cost_history_single_iteration(
    tmp_path: pytest.fixture,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[valid-type]
) -> None:
    """Single iteration: total_cost > 0, cumulative_cost == total_cost."""
    monkeypatch.chdir(tmp_path)
    rows = [_row("US-001", "1", "haiku", 1000, 500, 200)]
    _make_tsv(tmp_path, rows)
    resp = client.get("/api/dashboard/cost-history")
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["iteration"] == 1
    assert entry["total_tokens"] == 1700
    assert entry["total_cost"] > 0
    assert entry["cumulative_cost"] == entry["total_cost"]


def test_cost_history_multiple_iterations_sorted_cumulative(
    tmp_path: pytest.fixture,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[valid-type]
) -> None:
    """Two iterations: sorted by iteration, cumulative_cost is monotonically increasing."""
    monkeypatch.chdir(tmp_path)
    rows = [
        _row("US-001", "2", "haiku", 2000, 1000, 400),
        _row("US-002", "1", "sonnet", 1000, 500, 200),
        _row("US-003", "2", "haiku", 1000, 500, 100),
    ]
    _make_tsv(tmp_path, rows)
    resp = client.get("/api/dashboard/cost-history")
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert len(history) == 2
    assert history[0]["iteration"] == 1
    assert history[1]["iteration"] == 2
    # cumulative_cost must be monotonically increasing
    assert history[1]["cumulative_cost"] > history[0]["cumulative_cost"]
    # cumulative_cost[1] == sum of both iterations
    expected_cumulative = round(history[0]["total_cost"] + history[1]["total_cost"], 6)
    assert abs(history[1]["cumulative_cost"] - expected_cumulative) < 1e-9
