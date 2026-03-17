"""Tests for lib/velocity_model.py (US-352)."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from velocity_model import (
    build_velocity_model,
    classify_story,
    format_report,
    get_story_estimate,
    load_velocity_model,
    save_velocity_model,
)

# ── classify_story ────────────────────────────────────────────────────────────


def test_classify_story_test():
    assert classify_story("Add pytest coverage for merge module") == "test"


def test_classify_story_ci():
    assert classify_story("Extract repeated CI steps into composite actions") == "ci"


def test_classify_story_ui():
    assert classify_story("Add TUI dashboard widget for live progress") == "ui"


def test_classify_story_schema():
    assert classify_story("Migrate prd.schema.json to JSON Schema Draft 2020-12") == "schema"


def test_classify_story_cost():
    assert classify_story("Derive cross-iteration story velocity model from cost estimates") == "cost"


def test_classify_story_general():
    assert classify_story("Do something with rabbits") == "general"


def test_classify_story_case_insensitive():
    assert classify_story("PYTEST parallel xdist") == "test"


# ── build_velocity_model ──────────────────────────────────────────────────────


def _write_tsv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["timestamp", "spiral_iter", "ralph_iter", "story_id",
                  "story_title", "status", "duration_sec", "model", "retry_num", "commit_sha"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_build_velocity_model_empty(tmp_path):
    tsv = tmp_path / "results.tsv"
    _write_tsv(tsv, [])
    model = build_velocity_model(str(tsv))
    assert model["total_rows"] == 0
    assert model["story_types"] == {}


def test_build_velocity_model_missing_file(tmp_path):
    model = build_velocity_model(str(tmp_path / "nonexistent.tsv"))
    assert model["story_types"] == {}
    assert model["total_rows"] == 0


def test_build_velocity_model_groups_by_type(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest coverage A", "status": "pass", "duration_sec": 100,
         "model": "haiku", "retry_num": 0},
        {"story_title": "Add pytest coverage B", "status": "pass", "duration_sec": 200,
         "model": "haiku", "retry_num": 1},
        {"story_title": "Add TUI dashboard widget", "status": "reject", "duration_sec": 500,
         "model": "sonnet", "retry_num": 2},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    assert "test" in model["story_types"]
    assert "ui" in model["story_types"]
    assert model["story_types"]["test"]["samples"] == 2
    assert model["story_types"]["ui"]["samples"] == 1


def test_build_velocity_model_pass_rate(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest A", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
        {"story_title": "Add pytest B", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
        {"story_title": "Add pytest C", "status": "reject", "duration_sec": 100, "model": "haiku", "retry_num": 1},
        {"story_title": "Add pytest D", "status": "reject", "duration_sec": 100, "model": "haiku", "retry_num": 1},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    test_entry = model["story_types"]["test"]
    assert test_entry["pass_rate"] == pytest.approx(0.5, abs=0.01)
    assert test_entry["mean_retries"] == pytest.approx(0.5, abs=0.01)


def test_build_velocity_model_mean_tokens_positive(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest coverage", "status": "pass", "duration_sec": 60,
         "model": "haiku", "retry_num": 0},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    entry = model["story_types"]["test"]
    assert entry["mean_tokens"] > 0
    assert entry["mean_cost_usd"] > 0


def test_build_velocity_model_skips_zero_duration(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest A", "status": "pass", "duration_sec": 0, "model": "haiku", "retry_num": 0},
        {"story_title": "Add pytest B", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    entry = model["story_types"]["test"]
    assert entry["usable_duration_samples"] == 1


# ── get_story_estimate ────────────────────────────────────────────────────────


def test_get_story_estimate_returns_none_below_threshold(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest A", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    assert get_story_estimate("Add pytest for module X", model, min_samples=5) is None


def test_get_story_estimate_returns_data_above_threshold(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": f"Add pytest row {i}", "status": "pass", "duration_sec": 100,
         "model": "haiku", "retry_num": 0}
        for i in range(6)
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    est = get_story_estimate("Add pytest for feature X", model, min_samples=5)
    assert est is not None
    assert est["story_type"] == "test"
    assert est["mean_tokens"] > 0


def test_get_story_estimate_unknown_type_returns_none():
    model = {"story_types": {}, "total_rows": 0, "source": ""}
    assert get_story_estimate("Do something with rabbits", model) is None


# ── save / load velocity_model ────────────────────────────────────────────────


def test_save_and_load_velocity_model(tmp_path):
    model = {
        "story_types": {"test": {"samples": 3, "mean_tokens": 1234.5}},
        "total_rows": 3,
        "source": "results.tsv",
    }
    output = str(tmp_path / "sub" / "velocity_model.json")
    save_velocity_model(model, output)
    loaded = load_velocity_model(output)
    assert loaded["total_rows"] == 3
    assert loaded["story_types"]["test"]["samples"] == 3


def test_load_velocity_model_missing_file(tmp_path):
    result = load_velocity_model(str(tmp_path / "nonexistent.json"))
    assert result["story_types"] == {}


# ── format_report ─────────────────────────────────────────────────────────────


def test_format_report_empty():
    model = {"story_types": {}, "total_rows": 0, "source": ""}
    report = format_report(model)
    assert "No historical data" in report


def test_format_report_contains_type_names(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest A", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
        {"story_title": "Add TUI widget", "status": "reject", "duration_sec": 200, "model": "sonnet", "retry_num": 1},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    report = format_report(model)
    assert "test" in report
    assert "ui" in report
    assert "story_type" in report
    assert "mean_tokens" in report
    assert "pass_rate" in report


def test_format_report_asterisk_marks_low_sample_types(tmp_path):
    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest A", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
    ]
    _write_tsv(tsv, rows)
    model = build_velocity_model(str(tsv))
    report = format_report(model)
    assert "* = fewer than" in report


# ── CLI main ──────────────────────────────────────────────────────────────────


def test_velocity_model_main_creates_output_file(tmp_path):
    from velocity_model import main as vm_main

    tsv = tmp_path / "results.tsv"
    _write_tsv(tsv, [])
    out = tmp_path / "vm.json"
    rc = vm_main(["--results", str(tsv), "--output", str(out)])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "story_types" in data


def test_velocity_model_main_report_flag(tmp_path, capsys):
    from velocity_model import main as vm_main

    tsv = tmp_path / "results.tsv"
    rows = [
        {"story_title": "Add pytest row", "status": "pass", "duration_sec": 100, "model": "haiku", "retry_num": 0},
    ]
    _write_tsv(tsv, rows)
    out = tmp_path / "vm.json"
    rc = vm_main(["--results", str(tsv), "--output", str(out), "--report"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "velocity" in captured.out.lower() or "story_type" in captured.out.lower()
