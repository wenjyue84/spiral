"""Tests for lib/iteration_detail_aggregator.py — Iteration metrics aggregation API.

Tests verify that aggregate_iteration_metrics() correctly parses results.tsv
and spiral_events.jsonl to produce detailed iteration analytics.
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from lib.iteration_detail_aggregator import aggregate_iteration_metrics


class TestIterationDetailAggregator:
    """Tests for iteration detail aggregation from TSV and JSONL files."""

    def test_get_iteration_detail_aggregates_metrics(self) -> None:
        """Verify aggregate_iteration_metrics parses TSV/JSONL and returns correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create mock results.tsv
            results_file = tmpdir_path / "results.tsv"
            results_data = [
                {
                    "timestamp": "2026-05-18T10:00:00Z",
                    "spiral_iter": "5",
                    "ralph_iter": "1",
                    "story_id": "US-1001",
                    "story_title": "Test Story 1",
                    "status": "passed",
                    "duration_sec": "45.2",
                    "model": "haiku",
                    "retry_num": "0",
                    "cache_read_tokens": "5000",
                    "cache_creation_tokens": "1000",
                    "review_tokens": "500",
                },
                {
                    "timestamp": "2026-05-18T10:01:00Z",
                    "spiral_iter": "5",
                    "ralph_iter": "1",
                    "story_id": "US-1002",
                    "story_title": "Test Story 2",
                    "status": "failed",
                    "duration_sec": "32.1",
                    "model": "sonnet",
                    "retry_num": "1",
                    "cache_read_tokens": "10000",
                    "cache_creation_tokens": "2000",
                    "review_tokens": "1500",
                },
                {
                    "timestamp": "2026-05-18T10:02:00Z",
                    "spiral_iter": "6",
                    "ralph_iter": "1",
                    "story_id": "US-1003",
                    "story_title": "Test Story 3",
                    "status": "passed",
                    "duration_sec": "50.0",
                    "model": "opus",
                    "retry_num": "0",
                    "cache_read_tokens": "20000",
                    "cache_creation_tokens": "5000",
                    "review_tokens": "2000",
                },
            ]

            with open(results_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=results_data[0].keys(), delimiter="\t")
                writer.writeheader()
                writer.writerows(results_data)

            # Create mock spiral_events.jsonl
            events_file = tmpdir_path / "spiral_events.jsonl"
            events_data = [
                {
                    "event_type": "phase_start",
                    "timestamp": "2026-05-18T10:00:00Z",
                    "phase": "Phase I",
                    "iteration": 5,
                    "spiral_iter": 5,
                },
                {
                    "event_type": "story_complete",
                    "timestamp": "2026-05-18T10:00:45Z",
                    "story_id": "US-1001",
                    "phase": "Phase I",
                    "spiral_iter": 5,
                },
                {
                    "event_type": "story_complete",
                    "timestamp": "2026-05-18T10:01:17Z",
                    "story_id": "US-1002",
                    "phase": "Phase I",
                    "spiral_iter": 5,
                },
                {
                    "event_type": "phase_end",
                    "timestamp": "2026-05-18T10:01:30Z",
                    "phase": "Phase I",
                    "duration_ms": 90000,
                    "iteration": 5,
                    "spiral_iter": 5,
                },
                {
                    "event_type": "phase_start",
                    "timestamp": "2026-05-18T10:01:31Z",
                    "phase": "Phase V",
                    "iteration": 5,
                    "spiral_iter": 5,
                },
                {
                    "event_type": "phase_end",
                    "timestamp": "2026-05-18T10:02:00Z",
                    "phase": "Phase V",
                    "duration_ms": 29000,
                    "iteration": 5,
                    "spiral_iter": 5,
                },
            ]

            with open(events_file, "w", encoding="utf-8") as f:
                for event in events_data:
                    f.write(json.dumps(event) + "\n")

            # Call aggregator
            result = aggregate_iteration_metrics(
                iteration_num=5,
                results_tsv_path=str(results_file),
                events_jsonl_path=str(events_file),
            )

            # Verify structure
            assert result["iteration"] == 5
            assert result["totalTime_ms"] == int((45.2 + 32.1) * 1000)
            assert "totalCost_usd" in result
            assert isinstance(result["stories"], list)
            assert len(result["stories"]) == 2  # Only iteration 5 stories
            assert isinstance(result["phases"], list)
            assert len(result["phases"]) == 2  # Phase I and Phase V
            assert isinstance(result["cost_by_model"], dict)

            # Verify story details
            stories_by_id = {s["id"]: s for s in result["stories"]}
            assert "US-1001" in stories_by_id
            assert stories_by_id["US-1001"]["status"] == "passed"
            assert stories_by_id["US-1001"]["model"] == "haiku"
            assert stories_by_id["US-1001"]["retries"] == 0
            assert stories_by_id["US-1001"]["tokens_used"] == 6500

            assert "US-1002" in stories_by_id
            assert stories_by_id["US-1002"]["status"] == "failed"
            assert stories_by_id["US-1002"]["model"] == "sonnet"
            assert stories_by_id["US-1002"]["retries"] == 1

            # Verify phase details
            phases_by_name = {p["name"]: p for p in result["phases"]}
            assert "Phase I" in phases_by_name
            assert phases_by_name["Phase I"]["duration_ms"] == 90000
            assert phases_by_name["Phase I"]["story_count"] == 2

            assert "Phase V" in phases_by_name
            assert phases_by_name["Phase V"]["duration_ms"] == 29000

    def test_filter_by_status(self) -> None:
        """Verify status filtering works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            results_file = tmpdir_path / "results.tsv"
            results_data = [
                {
                    "timestamp": "2026-05-18T10:00:00Z",
                    "spiral_iter": "5",
                    "ralph_iter": "1",
                    "story_id": "US-1001",
                    "story_title": "Test",
                    "status": "passed",
                    "duration_sec": "10.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "cache_read_tokens": "1000",
                    "cache_creation_tokens": "0",
                    "review_tokens": "0",
                },
                {
                    "timestamp": "2026-05-18T10:01:00Z",
                    "spiral_iter": "5",
                    "ralph_iter": "1",
                    "story_id": "US-1002",
                    "story_title": "Test",
                    "status": "failed",
                    "duration_sec": "20.0",
                    "model": "sonnet",
                    "retry_num": "1",
                    "cache_read_tokens": "2000",
                    "cache_creation_tokens": "0",
                    "review_tokens": "0",
                },
            ]

            with open(results_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=results_data[0].keys(), delimiter="\t")
                writer.writeheader()
                writer.writerows(results_data)

            events_file = tmpdir_path / "spiral_events.jsonl"
            events_file.write_text("")

            # Filter by passed status
            result = aggregate_iteration_metrics(
                iteration_num=5,
                results_tsv_path=str(results_file),
                events_jsonl_path=str(events_file),
                status_filter="passed",
            )

            assert len(result["stories"]) == 1
            assert result["stories"][0]["id"] == "US-1001"
            assert result["stories"][0]["status"] == "passed"

            # Filter by failed status
            result = aggregate_iteration_metrics(
                iteration_num=5,
                results_tsv_path=str(results_file),
                events_jsonl_path=str(events_file),
                status_filter="failed",
            )

            assert len(result["stories"]) == 1
            assert result["stories"][0]["id"] == "US-1002"
            assert result["stories"][0]["status"] == "failed"

    def test_empty_files(self) -> None:
        """Verify aggregator handles empty/missing files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create empty files
            results_file = tmpdir_path / "results.tsv"
            events_file = tmpdir_path / "spiral_events.jsonl"
            results_file.write_text("timestamp\tspiral_iter\tstory_id\tstatus\tduration_sec\tmodel\n")
            events_file.write_text("")

            result = aggregate_iteration_metrics(
                iteration_num=5,
                results_tsv_path=str(results_file),
                events_jsonl_path=str(events_file),
            )

            assert result["iteration"] == 5
            assert result["totalTime_ms"] == 0
            assert result["totalCost_usd"] == 0.0
            assert len(result["stories"]) == 0
            assert len(result["phases"]) == 0

    def test_cost_estimation_by_model(self) -> None:
        """Verify cost estimation is correct for different models."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            results_file = tmpdir_path / "results.tsv"
            results_data = [
                {
                    "timestamp": "2026-05-18T10:00:00Z",
                    "spiral_iter": "5",
                    "ralph_iter": "1",
                    "story_id": "US-1001",
                    "story_title": "Test",
                    "status": "passed",
                    "duration_sec": "10.0",
                    "model": "haiku",
                    "retry_num": "0",
                    "cache_read_tokens": "1000000",  # 1M tokens
                    "cache_creation_tokens": "0",
                    "review_tokens": "0",
                },
            ]

            with open(results_file, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=results_data[0].keys(), delimiter="\t")
                writer.writeheader()
                writer.writerows(results_data)

            events_file = tmpdir_path / "spiral_events.jsonl"
            events_file.write_text("")

            result = aggregate_iteration_metrics(
                iteration_num=5,
                results_tsv_path=str(results_file),
                events_jsonl_path=str(events_file),
            )

            # Haiku costs $0.25 per 1M tokens
            # 1M tokens * $0.25 / 1M = $0.25
            assert result["totalCost_usd"] == pytest.approx(0.25, rel=0.01)
            assert result["cost_by_model"]["haiku"] == pytest.approx(0.25, rel=0.01)
