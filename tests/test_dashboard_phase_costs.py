"""Tests for GET /api/dashboard/phase-cost-breakdown endpoint (US-641)."""

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


def _row(story_id: str = "US-001", model: str = "haiku", read: int = 1000, creation: int = 500, review: int = 200) -> dict:  # type: ignore[type-arg]
    return {
        "timestamp": "2024-01-01T00:00:00",
        "spiral_iter": "1",
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


def test_phase_cost_breakdown_empty(tmp_path: pytest.fixture, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[valid-type]
    """Empty results.tsv → phases list is empty."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results.tsv").write_text("", encoding="utf-8")
    resp = client.get("/api/dashboard/phase-cost-breakdown")
    assert resp.status_code == 200
    assert resp.json()["phases"] == []


def test_phase_cost_model_dist_sums_to_one(tmp_path: pytest.fixture, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[valid-type]
    """20-row fixture: model_dist values sum to ~1.0 per phase."""
    monkeypatch.chdir(tmp_path)
    models = ["haiku", "sonnet", "opus"]
    rows = [_row(story_id=f"US-{i:03d}", model=models[i % 3]) for i in range(20)]
    _make_tsv(tmp_path, rows)
    resp = client.get("/api/dashboard/phase-cost-breakdown")
    assert resp.status_code == 200
    phases = resp.json()["phases"]
    assert len(phases) > 0
    for p in phases:
        total = sum(p["model_dist"].values())
        assert abs(total - 1.0) < 0.02, f"model_dist should sum to ~1.0, got {total}"
        assert p["story_count"] == 20
        assert p["token_count"] > 0
        assert p["cost_usd"] > 0


def test_phase_i_cost_ge_phase_r(tmp_path: pytest.fixture, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[valid-type]
    """Phase I cost >= Phase R cost (Phase R has no rows in results.tsv)."""
    monkeypatch.chdir(tmp_path)
    rows = [_row(story_id=f"US-{i:03d}") for i in range(20)]
    _make_tsv(tmp_path, rows)
    resp = client.get("/api/dashboard/phase-cost-breakdown")
    assert resp.status_code == 200
    by_phase = {p["phase"]: p for p in resp.json()["phases"]}
    phase_i_cost = by_phase.get("Phase I", {}).get("cost_usd", 0)
    phase_r_cost = by_phase.get("Phase R", {}).get("cost_usd", 0)
    assert phase_i_cost >= phase_r_cost
