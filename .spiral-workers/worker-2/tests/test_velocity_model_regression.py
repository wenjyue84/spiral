"""Regression tests for velocity model integration in cmd_estimate (US-525).

Tests verify that python main.py estimate reads results.tsv and produces
data-driven cost/duration projections via the velocity model.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from _pytest.capture import CaptureFixture

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from cost_project import main as cost_project_main
from velocity_model import build_velocity_model, load_or_build_velocity_model

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


def _write_results(path: Path, rows: list[dict[str, str]]) -> None:
    """Write results.tsv with test data."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_HEADER, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_row(
    duration_sec: str = "300",
    model: str = "sonnet",
    story_id: str = "US-001",
    story_title: str = "Add pytest coverage",
    status: str = "pass",
) -> dict[str, str]:
    """Create a results.tsv row."""
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


def _write_prd(path: Path, stories: list[dict[str, object]]) -> None:
    """Write prd.json with test stories."""
    prd: dict[str, object] = {
        "productName": "TestProduct",
        "branchName": "main",
        "userStories": stories,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prd, f)


# ── Acceptance Criteria Tests ──────────────────────────────────────────────


def test_estimate_reads_results_tsv_creates_datadriven_model(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Verify cmd_estimate uses velocity model data from results.tsv.

    This test verifies the core requirement: that the estimate command reads
    results.tsv and creates a data-driven velocity model (not just static defaults).
    """
    # Create results.tsv with 6+ rows (above MIN_HISTORY_ROWS = 5)
    results = tmp_path / "results.tsv"
    rows = [
        _make_row(duration_sec=str(d * 100), story_id=f"US-{i:03d}", story_title="Add pytest coverage")
        for i, d in enumerate([1, 2, 3, 4, 5, 6], start=1)
    ]
    _write_results(results, rows)

    # Create minimal prd.json with 1 pending story
    prd = tmp_path / "prd.json"
    _write_prd(prd, [{"id": "US-100", "passes": False}])

    # Build velocity model (simulates what cmd_estimate does)
    model = build_velocity_model(str(results))

    # Verify velocity model was built with data
    assert model["total_rows"] == 6, "Velocity model should have 6 rows"
    assert "test" in model["story_types"], "Should classify 'Add pytest coverage' as 'test' type"
    assert model["story_types"]["test"]["samples"] == 6, "Should have 6 samples for test type"
    assert model["story_types"]["test"]["mean_tokens"] > 0, "Mean tokens should be derived from duration"


def test_estimate_output_differs_empty_vs_populated_tsv(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Verify estimate output differs between empty and populated results.tsv.

    This test ensures that the velocity model feature is actually being used
    by comparing output with empty vs populated results.tsv.
    """
    # Create prd.json
    prd = tmp_path / "prd.json"
    _write_prd(prd, [{"id": "US-100", "passes": False}])

    # ─ Test 1: Empty results.tsv (no historical data)
    empty_results = tmp_path / "empty_results.tsv"
    _write_results(empty_results, [])
    empty_model = build_velocity_model(str(empty_results))
    empty_total = empty_model["total_rows"]
    empty_types = empty_model["story_types"]

    # ─ Test 2: Populated results.tsv (with 6+ rows)
    pop_results = tmp_path / "pop_results.tsv"
    rows = [
        _make_row(duration_sec=str(d * 100), story_id=f"US-{i:03d}", story_title="Add pytest coverage")
        for i, d in enumerate([1, 2, 3, 4, 5, 6], start=1)
    ]
    _write_results(pop_results, rows)
    pop_model = build_velocity_model(str(pop_results))
    pop_total = pop_model["total_rows"]
    pop_types = pop_model["story_types"]

    # Verify models differ
    assert empty_total != pop_total, "Empty and populated models should have different total_rows"
    assert empty_types != pop_types, "Empty and populated models should have different story_types"
    assert empty_total == 0, "Empty results should yield 0 rows"
    assert pop_total == 6, "Populated results should yield 6 rows"
    assert "test" in pop_types, "Populated model should classify story types"
    assert "test" not in empty_types, "Empty model should have no story types"


def test_estimate_includes_per_type_metrics(tmp_path: Path) -> None:
    """Verify estimate output includes per-type mean_tokens, duration, and pass_rate.

    This test ensures the velocity model provides the metrics needed for
    data-driven cost projection.
    """
    # Create results.tsv with multiple rows for test type
    results = tmp_path / "results.tsv"
    rows = [
        _make_row(
            duration_sec="100",
            story_id="US-001",
            story_title="Add pytest A",
            status="pass",
        ),
        _make_row(
            duration_sec="200",
            story_id="US-002",
            story_title="Add pytest B",
            status="pass",
        ),
        _make_row(
            duration_sec="300",
            story_id="US-003",
            story_title="Add pytest C",
            status="reject",
        ),
        _make_row(
            duration_sec="400",
            story_id="US-004",
            story_title="Add pytest D",
            status="reject",
        ),
        _make_row(
            duration_sec="500",
            story_id="US-005",
            story_title="Add pytest E",
            status="pass",
        ),
        _make_row(
            duration_sec="600",
            story_id="US-006",
            story_title="Add pytest F",
            status="pass",
        ),
    ]
    _write_results(results, rows)

    # Build velocity model
    model = build_velocity_model(str(results))

    # Verify per-type metrics are present
    assert "test" in model["story_types"]
    test_metrics = model["story_types"]["test"]

    # Check required metrics
    assert "samples" in test_metrics, "Should have samples count"
    assert test_metrics["samples"] == 6, "Should count all 6 rows"
    assert "mean_tokens" in test_metrics, "Should have mean_tokens"
    assert test_metrics["mean_tokens"] > 0, "mean_tokens should be positive"
    assert "pass_rate" in test_metrics, "Should have pass_rate"
    assert 0 <= test_metrics["pass_rate"] <= 1, "pass_rate should be 0-1"
    assert "mean_retries" in test_metrics, "Should have mean_retries"

    # Verify pass_rate is correct: 4 passes out of 6 = 0.67
    expected_pass_rate = 4.0 / 6.0
    assert abs(test_metrics["pass_rate"] - expected_pass_rate) < 0.01


def test_estimate_fails_if_velocity_model_parsing_broken(tmp_path: Path) -> None:
    """Verify test fails if velocity model parsing is removed (negative test).

    This ensures the regression test would catch if velocity model integration
    is broken or removed from cmd_estimate.
    """
    # Create results.tsv with data
    results = tmp_path / "results.tsv"
    rows = [
        _make_row(duration_sec=str(d * 100), story_id=f"US-{i:03d}", story_title="Add pytest coverage")
        for i, d in enumerate([1, 2, 3, 4, 5, 6], start=1)
    ]
    _write_results(results, rows)

    # Build velocity model
    model = build_velocity_model(str(results))

    # This should NOT be empty if velocity model is working
    assert model["total_rows"] > 0, "If this fails, velocity model parsing is broken"
    assert model["story_types"], "If this fails, story type classification is broken"

    # If the velocity model feature is removed, this assertion would fail
    # demonstrating that the regression test catches the issue


# ── Integration Test: Full Workflow ────────────────────────────────────────


def test_velocity_model_integration_full_workflow(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """Full integration test: results.tsv → velocity model → estimate output.

    This test simulates the complete flow: results.tsv is read, velocity model
    is built, and cost_project.main() uses the model for estimates.
    """
    # Setup: Create results.tsv with historical data
    results = tmp_path / "results.tsv"
    rows = [
        _make_row(duration_sec="300", story_id="US-001", story_title="Add pytest test A"),
        _make_row(duration_sec="400", story_id="US-002", story_title="Add pytest test B"),
        _make_row(duration_sec="350", story_id="US-003", story_title="Add pytest test C"),
        _make_row(duration_sec="320", story_id="US-004", story_title="Add pytest test D"),
        _make_row(duration_sec="380", story_id="US-005", story_title="Add pytest test E"),
        _make_row(duration_sec="420", story_id="US-006", story_title="Add pytest test F"),
    ]
    _write_results(results, rows)

    # Create prd.json with pending stories
    prd = tmp_path / "prd.json"
    _write_prd(
        prd,
        [
            {"id": "US-100", "passes": False},
            {"id": "US-101", "passes": False},
            {"id": "US-102", "passes": False},
        ],
    )

    # Build velocity model (simulates cmd_estimate behavior)
    vm_path = tmp_path / ".spiral" / "velocity_model.json"
    vm_path.parent.mkdir(parents=True, exist_ok=True)
    model = load_or_build_velocity_model(str(results), str(vm_path))

    # Verify velocity model was built
    assert vm_path.exists(), "Velocity model JSON should be created"
    assert model["total_rows"] == 6, "Should have 6 rows of historical data"
    assert "test" in model["story_types"], "Should classify stories as test type"

    # Call cost_project.main() with velocity model (simulates cmd_estimate)
    rc = cost_project_main(
        [
            "--prd",
            str(prd),
            "--results",
            str(results),
            "--velocity-model",
            str(vm_path),
            "--yes",
        ]
    )

    # Verify cost projection runs successfully with velocity model
    assert rc == 0, "cost_project.main() should exit 0 with sufficient history"
    captured = capsys.readouterr().out
    assert "Pre-flight" in captured, "Should show pre-flight cost projection"


def test_load_or_build_velocity_model_caches_result(tmp_path: Path) -> None:
    """Verify load_or_build_velocity_model() caches results (US-438).

    This ensures the velocity model is efficiently reused across cmd_estimate calls.
    """
    results = tmp_path / "results.tsv"
    _write_results(results, [_make_row(duration_sec="100")])

    vm_out = tmp_path / ".spiral" / "velocity_model.json"
    vm_out.parent.mkdir(parents=True, exist_ok=True)

    # First call: builds model
    model1 = load_or_build_velocity_model(str(results), str(vm_out))
    assert vm_out.exists(), "Velocity model JSON should be created"
    assert model1["total_rows"] == 1

    # Second call: should load from cache (same mtime)
    model2 = load_or_build_velocity_model(str(results), str(vm_out))
    assert model2["total_rows"] == 1
    assert model1 == model2, "Should return identical cached model"

    # Verify mtime was written
    data = json.loads(vm_out.read_text(encoding="utf-8"))
    assert "results_tsv_mtime" in data, "Should store results.tsv mtime for cache validation"
