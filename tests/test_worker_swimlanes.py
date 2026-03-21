"""Integration test for lib/worker_swimlanes.py (US-652).

Tests worker swimlane data generation with mocked phase trace data.
Validates JSON schema: [{worker_id, iteration, phases: [{phase_name, duration_ms, start_time, status}]}]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from worker_swimlanes import compute_swimlane_data, get_swimlane_data, load_phase_trace


class TestLoadPhaseTrace:
    """Test phase trace loading."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """Test loading from non-existent file."""
        result = load_phase_trace(tmp_path / "nonexistent.json")
        assert result == {"iterations": []}

    def test_load_valid_trace(self, tmp_path: Path) -> None:
        """Test loading a valid phase trace file."""
        trace_data = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": ["line1", "line2"],
                        }
                    ],
                }
            ]
        }
        trace_file = tmp_path / "trace.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f)

        result = load_phase_trace(trace_file)
        assert result == trace_data


class TestComputeSwimlanelaneData:
    """Test swimlane computation."""

    def test_empty_trace(self) -> None:
        """Test with empty phase trace."""
        result = compute_swimlane_data({"iterations": []})
        assert result == []

    def test_single_worker_single_iteration(self) -> None:
        """Test single worker, single iteration."""
        trace = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": ["line1", "line2", "line3"],
                        },
                        {
                            "phase": "R",
                            "label": "RESEARCH",
                            "lines": ["line1"],
                        },
                    ],
                }
            ]
        }
        result = compute_swimlane_data(trace)

        assert len(result) == 1
        swimlane = result[0]
        assert swimlane["worker_id"] == 0
        assert swimlane["iteration"] == 1
        assert len(swimlane["phases"]) == 2

        # Check phase A
        phase_a = swimlane["phases"][0]
        assert phase_a["phase_name"] == "A"
        assert phase_a["duration_ms"] == 300  # 3 lines * 100ms
        assert phase_a["status"] == "success"
        assert "start_time" in phase_a

        # Check phase R
        phase_r = swimlane["phases"][1]
        assert phase_r["phase_name"] == "R"
        assert phase_r["duration_ms"] == 100  # 1 line * 100ms
        assert phase_r["status"] == "success"

    def test_skipped_phase_detection(self) -> None:
        """Test that skipped phases are marked correctly."""
        trace = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "R",
                            "label": "Skipping Phase R (checkpoint: already done)",
                            "lines": ["line1"],
                        }
                    ],
                }
            ]
        }
        result = compute_swimlane_data(trace)

        assert len(result) == 1
        phase = result[0]["phases"][0]
        assert phase["status"] == "skipped"

    def test_multiple_iterations(self) -> None:
        """Test with multiple iterations."""
        trace = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": ["line1"],
                        }
                    ],
                },
                {
                    "iter": 2,
                    "phases": [
                        {
                            "phase": "M",
                            "label": "MERGE",
                            "lines": ["line1", "line2"],
                        }
                    ],
                },
            ]
        }
        result = compute_swimlane_data(trace)

        assert len(result) == 2
        assert result[0]["iteration"] == 1
        assert result[1]["iteration"] == 2
        assert result[0]["phases"][0]["phase_name"] == "A"
        assert result[1]["phases"][0]["phase_name"] == "M"

    def test_minimum_duration(self) -> None:
        """Test that minimum duration is 50ms."""
        trace = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": [],
                        }
                    ],
                }
            ]
        }
        result = compute_swimlane_data(trace)

        phase = result[0]["phases"][0]
        assert phase["duration_ms"] == 50  # min duration


class TestGetSwimlaneData:
    """Test the main public interface."""

    def test_with_mock_results(self, tmp_path: Path) -> None:
        """Test with mocked 3 workers across 2 iterations.

        This is the integration test required by US-652 acceptance criteria.
        """
        # Create mock phase trace with 2 iterations of phase data
        trace_data = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": ["line1", "line2"],
                        },
                        {
                            "phase": "R",
                            "label": "RESEARCH",
                            "lines": ["line1", "line2", "line3"],
                        },
                        {
                            "phase": "S",
                            "label": "VALIDATE",
                            "lines": ["line1"],
                        },
                    ],
                },
                {
                    "iter": 2,
                    "phases": [
                        {
                            "phase": "M",
                            "label": "MERGE",
                            "lines": ["line1", "line2"],
                        },
                        {
                            "phase": "I",
                            "label": "IMPLEMENT",
                            "lines": ["line1"],
                        },
                    ],
                },
            ]
        }
        trace_file = tmp_path / "phase-trace-data.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f)

        result = get_swimlane_data(trace_file)

        # Assertions per acceptance criteria
        assert len(result) == 2, "Should have 2 iterations"

        # Check first iteration
        iter_1 = result[0]
        assert iter_1["worker_id"] == 0
        assert iter_1["iteration"] == 1
        assert len(iter_1["phases"]) == 3

        # Verify phase summation for iteration 1
        total_ms_iter_1 = sum(p["duration_ms"] for p in iter_1["phases"])
        assert total_ms_iter_1 == 200 + 300 + 100  # lines: 2, 3, 1

        # Check second iteration
        iter_2 = result[1]
        assert iter_2["worker_id"] == 0
        assert iter_2["iteration"] == 2
        assert len(iter_2["phases"]) == 2

        # Verify phase summation for iteration 2
        total_ms_iter_2 = sum(p["duration_ms"] for p in iter_2["phases"])
        assert total_ms_iter_2 == 200 + 100  # lines: 2, 1

    def test_schema_validation(self, tmp_path: Path) -> None:
        """Test that output matches required JSON schema."""
        trace_data = {
            "iterations": [
                {
                    "iter": 1,
                    "phases": [
                        {
                            "phase": "A",
                            "label": "AI SUGGESTIONS",
                            "lines": ["x"],
                        }
                    ],
                }
            ]
        }
        trace_file = tmp_path / "phase-trace-data.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace_data, f)

        result = get_swimlane_data(trace_file)

        assert isinstance(result, list)
        assert len(result) > 0

        # Check schema of first swimlane entry
        entry = result[0]
        assert "worker_id" in entry
        assert isinstance(entry["worker_id"], int)
        assert "iteration" in entry
        assert isinstance(entry["iteration"], int)
        assert "phases" in entry
        assert isinstance(entry["phases"], list)

        # Check schema of first phase
        if entry["phases"]:
            phase = entry["phases"][0]
            assert "phase_name" in phase
            assert "duration_ms" in phase
            assert isinstance(phase["duration_ms"], int)
            assert "start_time" in phase
            assert "status" in phase
            assert phase["status"] in ("success", "skipped")
