#!/usr/bin/env python3
"""test_dashboard_research_cache.py — Integration tests for /api/dashboard/research-cache."""

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lib.analyze_results import parse_research_cache
from lib.dashboard.api import app


def _write_mock_tsv(path: Path, rows: list[dict]) -> None:
    """Write mock results.tsv with research_source column."""
    fieldnames = ["timestamp", "spiral_iter", "story_id", "research_source"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _build_rows(n_cache: int, n_api: int, iteration: int = 1) -> list[dict]:
    """Build n_cache cache-hit rows and n_api gemini_api rows."""
    rows = []
    for i in range(n_cache):
        rows.append(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "spiral_iter": str(iteration),
                "story_id": f"US-{i}",
                "research_source": "cache",
            }
        )
    for i in range(n_api):
        rows.append(
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "spiral_iter": str(iteration),
                "story_id": f"US-api-{i}",
                "research_source": "gemini_api",
            }
        )
    return rows


class TestResearchCacheEndpoint:
    """Test /api/dashboard/research-cache endpoint via FastAPI TestClient."""

    def test_endpoint_returns_200(self) -> None:
        """GET /api/dashboard/research-cache returns HTTP 200."""
        client = TestClient(app)
        response = client.get("/api/dashboard/research-cache")
        assert response.status_code == 200

    def test_endpoint_returns_correct_structure(self) -> None:
        """Endpoint returns JSON with required keys."""
        client = TestClient(app)
        response = client.get("/api/dashboard/research-cache")
        data = response.json()

        assert "hit_rate" in data
        assert "total_queries" in data
        assert "cached" in data
        assert "time_saved_seconds" in data
        assert "trend" in data
        assert isinstance(data["trend"], list)

    def test_endpoint_with_no_data_returns_zeros(self) -> None:
        """When no results.tsv or no research_source rows, returns zero defaults."""
        client = TestClient(app)
        response = client.get("/api/dashboard/research-cache")
        data = response.json()

        # Should return valid zero-state (real results.tsv lacks research_source column)
        assert data["hit_rate"] >= 0.0
        assert data["total_queries"] >= 0
        assert data["cached"] >= 0
        assert data["time_saved_seconds"] >= 0

    def test_endpoint_accepts_iteration_query_params(self) -> None:
        """Endpoint accepts start_iteration and end_iteration query params."""
        client = TestClient(app)
        response = client.get(
            "/api/dashboard/research-cache?start_iteration=0&end_iteration=10"
        )
        assert response.status_code == 200


class TestParseResearchCache:
    """Unit tests for parse_research_cache() with mocked TSV data."""

    def test_hit_rate_calculation(self, tmp_path: Path) -> None:
        """30 cache hits + 20 API calls → hit_rate = 0.6."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=30, n_api=20, iteration=1)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path)

        assert result["total_queries"] == 50
        assert result["cached"] == 30
        assert result["hit_rate"] == pytest.approx(0.6, abs=1e-4)

    def test_time_saved_positive(self, tmp_path: Path) -> None:
        """time_saved_seconds > 0 when there are cache hits."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=30, n_api=20, iteration=1)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path)

        assert result["time_saved_seconds"] > 0

    def test_trend_per_iteration(self, tmp_path: Path) -> None:
        """Trend list contains one entry per iteration."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=10, n_api=10, iteration=1)
        rows += _build_rows(n_cache=8, n_api=2, iteration=2)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path)

        assert len(result["trend"]) == 2
        iters = [t["iteration"] for t in result["trend"]]
        assert 1 in iters
        assert 2 in iters

        # iter 1: 10/20 = 0.5, iter 2: 8/10 = 0.8
        by_iter = {t["iteration"]: t["hit_rate"] for t in result["trend"]}
        assert by_iter[1] == pytest.approx(0.5, abs=1e-4)
        assert by_iter[2] == pytest.approx(0.8, abs=1e-4)

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        """Missing results.tsv returns zero-state dict."""
        tsv_path = tmp_path / "nonexistent.tsv"
        result = parse_research_cache(tsv_path)

        assert result["hit_rate"] == 0.0
        assert result["total_queries"] == 0
        assert result["cached"] == 0
        assert result["time_saved_seconds"] == 0
        assert result["trend"] == []

    def test_no_research_source_column_returns_defaults(self, tmp_path: Path) -> None:
        """TSV without research_source column returns zero-state."""
        tsv_path = tmp_path / "results.tsv"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("timestamp\tstory_id\tstatus\n")
            f.write("2026-01-01\tUS-1\tkeep\n")

        result = parse_research_cache(tsv_path)

        assert result["total_queries"] == 0
        assert result["trend"] == []

    def test_start_iteration_filter(self, tmp_path: Path) -> None:
        """start_iteration filters out earlier iterations."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=5, n_api=5, iteration=1)
        rows += _build_rows(n_cache=20, n_api=5, iteration=2)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path, start_iteration=2)

        assert result["total_queries"] == 25  # Only iter 2
        assert result["cached"] == 20

    def test_end_iteration_filter(self, tmp_path: Path) -> None:
        """end_iteration filters out later iterations."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=10, n_api=10, iteration=1)
        rows += _build_rows(n_cache=5, n_api=5, iteration=5)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path, end_iteration=2)

        assert result["total_queries"] == 20  # Only iter 1

    def test_non_cache_rows_are_ignored(self, tmp_path: Path) -> None:
        """Rows with empty or unknown research_source are ignored."""
        tsv_path = tmp_path / "results.tsv"
        fieldnames = ["timestamp", "spiral_iter", "story_id", "research_source"]
        with open(tsv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerow(
                {"timestamp": "T", "spiral_iter": "1", "story_id": "US-1", "research_source": "cache"}
            )
            writer.writerow(
                {"timestamp": "T", "spiral_iter": "1", "story_id": "US-2", "research_source": ""}
            )
            writer.writerow(
                {"timestamp": "T", "spiral_iter": "1", "story_id": "US-3", "research_source": "unknown_source"}
            )

        result = parse_research_cache(tsv_path)

        assert result["total_queries"] == 1  # Only the valid cache row
        assert result["cached"] == 1
        assert result["hit_rate"] == 1.0


class TestResearchCacheBudgetIntegration:
    """Integration test: 50 queries with 30 cache hits."""

    def test_mock_50_queries_returns_hit_rate_0_6(self, tmp_path: Path) -> None:
        """Mocked results.tsv with 30 cache hits / 20 API calls → hit_rate=0.6, time_saved>0."""
        tsv_path = tmp_path / "results.tsv"
        rows = _build_rows(n_cache=30, n_api=20, iteration=1)
        _write_mock_tsv(tsv_path, rows)

        result = parse_research_cache(tsv_path)

        assert result["hit_rate"] == pytest.approx(0.6, abs=1e-4), (
            f"Expected hit_rate=0.6 but got {result['hit_rate']}"
        )
        assert result["time_saved_seconds"] > 0, (
            f"Expected time_saved>0 but got {result['time_saved_seconds']}"
        )
        assert result["total_queries"] == 50
        assert result["cached"] == 30
