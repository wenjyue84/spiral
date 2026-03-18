"""Tests for US-456: routing metrics analysis."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from analyze_routing_metrics import analyze, format_table


def _write_events(path, events):
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _write_results_tsv(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("story_id\tstatus\tmodel\n")
        for row in rows:
            f.write(f"{row['story_id']}\t{row['status']}\t{row['model']}\n")


class TestAnalyze:
    def test_basic_metrics(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        results_path = str(tmp_path / "results.tsv")

        _write_events(events_path, [
            {"type": "route_story_assigned", "story_id": "US-001", "complexity_score": 20, "model_tier": "haiku"},
            {"type": "route_story_assigned", "story_id": "US-002", "complexity_score": 60, "model_tier": "sonnet"},
        ])
        _write_results_tsv(results_path, [
            {"story_id": "US-001", "status": "pass", "model": "haiku"},
            {"story_id": "US-002", "status": "pass", "model": "sonnet"},
        ])

        metrics = analyze(events_path, results_path)
        assert len(metrics["tiers"]) == 2
        assert metrics["savings_pct"] > 0  # haiku saves tokens vs sonnet

    def test_empty_data(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        results_path = str(tmp_path / "results.tsv")

        metrics = analyze(events_path, results_path)
        assert metrics["tiers"] == []
        assert metrics["savings_pct"] == 0.0

    def test_events_only_no_results(self, tmp_path):
        events_path = str(tmp_path / "events.jsonl")
        results_path = str(tmp_path / "results.tsv")

        _write_events(events_path, [
            {"type": "route_story_assigned", "story_id": "US-001", "complexity_score": 20, "model_tier": "haiku"},
        ])

        metrics = analyze(events_path, results_path)
        assert len(metrics["tiers"]) == 1
        assert metrics["tiers"][0]["model_tier"] == "haiku"


class TestFormatTable:
    def test_no_data_message(self):
        table = format_table({"tiers": [], "baseline_tokens": 0, "actual_tokens": 0, "savings_pct": 0})
        assert "No routing telemetry" in table

    def test_table_has_headers(self, tmp_path):
        metrics = {
            "tiers": [{"model_tier": "haiku", "samples": 5, "mean_tokens": 5000, "success_rate": 0.8}],
            "baseline_tokens": 75000,
            "actual_tokens": 25000,
            "savings_pct": 66.7,
        }
        table = format_table(metrics)
        assert "model_tier" in table
        assert "haiku" in table
        assert "66.7%" in table
