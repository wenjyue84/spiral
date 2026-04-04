#!/usr/bin/env python3
"""tests/test_velocity_tracker.py — Unit tests for velocity_tracker.py."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.velocity_tracker import (
    VelocitySnapshot,
    check_and_warn,
    compute_rolling_velocity,
    detect_stall,
    emit_stall_warning,
    generate_suggestions,
)


@pytest.fixture
def tmp_results_tsv(tmp_path: Path) -> Path:
    """Create a temporary results.tsv file."""
    path = tmp_path / "results.tsv"
    return path


@pytest.fixture
def tmp_prd_json(tmp_path: Path) -> Path:
    """Create a temporary prd.json file."""
    path = tmp_path / "prd.json"
    return path


@pytest.fixture
def tmp_events_jsonl(tmp_path: Path) -> Path:
    """Create a temporary spiral_events.jsonl path."""
    path = tmp_path / "spiral_events.jsonl"
    return path


class TestComputeRollingVelocity:
    """Tests for compute_rolling_velocity()."""

    def test_empty_results_file(self, tmp_results_tsv: Path) -> None:
        """Velocity is empty for non-existent file."""
        result = compute_rolling_velocity(str(tmp_results_tsv))
        assert result == []

    def test_nonexistent_file(self) -> None:
        """Velocity is empty for non-existent file."""
        result = compute_rolling_velocity("/nonexistent/path/results.tsv")
        assert result == []

    def test_single_iteration_single_pass(self, tmp_results_tsv: Path) -> None:
        """Single iteration with 1 pass yields velocity of 1.0."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest Story\tpass\t100\n")

        result = compute_rolling_velocity(str(tmp_results_tsv))
        assert len(result) == 1
        assert result[0].iteration == 1
        assert result[0].stories_passed == 1
        assert result[0].velocity == 1.0

    def test_multiple_iterations_varying_passes(self, tmp_results_tsv: Path) -> None:
        """Multiple iterations with varying pass counts."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            # Iter 1: 3 passes
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest Story 1\tpass\t100\n")
            f.write("2026-04-05T00:05:00Z\t1\t2\tUS-101\tTest Story 2\tpass\t100\n")
            f.write("2026-04-05T00:10:00Z\t1\t3\tUS-102\tTest Story 3\tpass\t100\n")
            # Iter 2: 1 pass (2 rejects)
            f.write("2026-04-05T00:15:00Z\t2\t1\tUS-103\tTest Story 4\tpass\t100\n")
            f.write("2026-04-05T00:20:00Z\t2\t2\tUS-104\tTest Story 5\treject\t100\n")
            f.write("2026-04-05T00:25:00Z\t2\t3\tUS-105\tTest Story 6\treject\t100\n")

        result = compute_rolling_velocity(str(tmp_results_tsv))
        assert len(result) == 2
        assert result[0].iteration == 1
        assert result[0].stories_passed == 3
        assert result[0].velocity == 3.0
        assert result[1].iteration == 2
        assert result[1].stories_passed == 1
        assert result[1].velocity == 1.0

    def test_only_passes_counted(self, tmp_results_tsv: Path) -> None:
        """Only 'pass' status is counted, rejects and errors ignored."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest\tpass\t100\n")
            f.write("2026-04-05T00:05:00Z\t1\t2\tUS-101\tTest\treject\t100\n")
            f.write("2026-04-05T00:10:00Z\t1\t3\tUS-102\tTest\terror\t100\n")
            f.write("2026-04-05T00:15:00Z\t1\t4\tUS-103\tTest\tskip\t100\n")

        result = compute_rolling_velocity(str(tmp_results_tsv))
        assert len(result) == 1
        assert result[0].iteration == 1
        assert result[0].stories_passed == 1
        assert result[0].velocity == 1.0

    def test_acceptance_criteria_fixture(self, tmp_results_tsv: Path) -> None:
        """AC4: Simulate iteration sequence [3, 1, 0, 0, 0]."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            # Iter 1: 3 passes
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest\tpass\t100\n")
            f.write("2026-04-05T00:05:00Z\t1\t2\tUS-101\tTest\tpass\t100\n")
            f.write("2026-04-05T00:10:00Z\t1\t3\tUS-102\tTest\tpass\t100\n")
            # Iter 2: 1 pass
            f.write("2026-04-05T00:15:00Z\t2\t1\tUS-103\tTest\tpass\t100\n")
            # Iter 3: 0 passes
            f.write("2026-04-05T00:20:00Z\t3\t1\tUS-104\tTest\treject\t100\n")
            # Iter 4: 0 passes
            f.write("2026-04-05T00:25:00Z\t4\t1\tUS-105\tTest\treject\t100\n")
            # Iter 5: 0 passes
            f.write("2026-04-05T00:30:00Z\t5\t1\tUS-106\tTest\treject\t100\n")

        result = compute_rolling_velocity(str(tmp_results_tsv))
        assert len(result) == 5
        assert [v.stories_passed for v in result] == [3, 1, 0, 0, 0]


class TestDetectStall:
    """Tests for detect_stall()."""

    def test_no_stall_with_sufficient_velocity(self) -> None:
        """No stall when velocity >= 0.5 for all iterations."""
        history = [
            VelocitySnapshot(1, 1, 1.0),
            VelocitySnapshot(2, 2, 2.0),
            VelocitySnapshot(3, 1, 1.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is False
        assert stall_start is None

    def test_short_history_no_stall(self) -> None:
        """Fewer than 3 iterations never triggers stall."""
        history = [
            VelocitySnapshot(1, 0, 0.0),
            VelocitySnapshot(2, 0, 0.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is False
        assert stall_start is None

    def test_exactly_three_below_threshold(self) -> None:
        """3 consecutive iterations below 0.5 threshold triggers stall."""
        history = [
            VelocitySnapshot(1, 0, 0.0),
            VelocitySnapshot(2, 0, 0.0),
            VelocitySnapshot(3, 0, 0.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is True
        assert stall_start == 1

    def test_acceptance_criteria_fixture(self) -> None:
        """AC4: Sequence [3, 1, 0, 0, 0] should stall at iter 3."""
        history = [
            VelocitySnapshot(1, 3, 3.0),
            VelocitySnapshot(2, 1, 1.0),
            VelocitySnapshot(3, 0, 0.0),
            VelocitySnapshot(4, 0, 0.0),
            VelocitySnapshot(5, 0, 0.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is True
        assert stall_start == 3

    def test_stall_start_iteration_captured(self) -> None:
        """Stall start iteration is the first low-velocity iteration."""
        history = [
            VelocitySnapshot(1, 5, 5.0),
            VelocitySnapshot(2, 4, 4.0),
            VelocitySnapshot(3, 0, 0.0),
            VelocitySnapshot(4, 0, 0.0),
            VelocitySnapshot(5, 0, 0.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is True
        assert stall_start == 3

    def test_stall_at_end_of_history(self) -> None:
        """Stall detected at the tail end of history."""
        history = [
            VelocitySnapshot(1, 2, 2.0),
            VelocitySnapshot(2, 2, 2.0),
            VelocitySnapshot(3, 1, 1.0),
            VelocitySnapshot(4, 0, 0.0),
            VelocitySnapshot(5, 0, 0.0),
            VelocitySnapshot(6, 0, 0.0),
        ]
        is_stalled, stall_start = detect_stall(history)
        assert is_stalled is True
        assert stall_start == 4


class TestGenerateSuggestions:
    """Tests for generate_suggestions()."""

    def test_nonexistent_prd_uses_fallback(self) -> None:
        """Missing prd.json returns fallback suggestions."""
        suggestions = generate_suggestions("/nonexistent/prd.json")
        assert len(suggestions) > 0
        assert any("logs" in s or "error" in s or "scope" in s for s in suggestions)

    def test_suggestions_with_valid_prd(self, tmp_prd_json: Path) -> None:
        """Suggestions include decompose, escalate, and skip."""
        prd = {
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Large pending story",
                    "description": "A" * 500,
                    "passes": False,
                    "estimatedComplexity": "large",
                    "priority": "high",
                    "_source": "seed",
                },
                {
                    "id": "US-2",
                    "title": "Low priority story",
                    "passes": False,
                    "priority": "low",
                    "_source": "ai-example",
                },
            ]
        }
        with open(tmp_prd_json, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        suggestions = generate_suggestions(str(tmp_prd_json))
        assert len(suggestions) >= 1
        # Should include decompose, escalate, or skip suggestions
        assert any("decompose" in s.lower() or "escalate" in s.lower() or "skip" in s.lower() for s in suggestions)

    def test_no_pending_stories_uses_fallback(self, tmp_prd_json: Path) -> None:
        """All stories passed returns fallback suggestions."""
        prd = {
            "userStories": [
                {
                    "id": "US-1",
                    "title": "Done",
                    "passes": True,
                },
            ]
        }
        with open(tmp_prd_json, "w", encoding="utf-8") as f:
            json.dump(prd, f)

        suggestions = generate_suggestions(str(tmp_prd_json))
        assert len(suggestions) > 0


class TestEmitStallWarning:
    """Tests for emit_stall_warning()."""

    def test_event_written_to_file(self, tmp_events_jsonl: Path) -> None:
        """Stall warning event is written to spiral_events.jsonl."""
        history = [VelocitySnapshot(1, 0, 0.0), VelocitySnapshot(2, 0, 0.0), VelocitySnapshot(3, 0, 0.0)]
        suggestions = ["suggestion 1", "suggestion 2"]

        emit_stall_warning(3, history, suggestions, str(tmp_events_jsonl))

        assert tmp_events_jsonl.exists()
        with open(tmp_events_jsonl, encoding="utf-8") as f:
            event = json.loads(f.readline())

        assert event["event"] == "stall_warning"
        assert event["iteration"] == 3
        assert event["velocity_threshold"] == 0.5
        assert event["consecutive_below_threshold"] == 3
        assert event["suggestions"] == suggestions
        assert "velocity_samples" in event
        assert "timestamp" in event

    def test_event_format_valid_json(self, tmp_events_jsonl: Path) -> None:
        """Event is valid JSON and can be parsed."""
        history = [VelocitySnapshot(5, 0, 0.0)]
        emit_stall_warning(5, history, ["test"], str(tmp_events_jsonl))

        with open(tmp_events_jsonl, encoding="utf-8") as f:
            # Ensure it's valid JSON
            event = json.loads(f.readline())
            assert isinstance(event, dict)

    def test_velocity_samples_included(self, tmp_events_jsonl: Path) -> None:
        """Event includes velocity samples from history."""
        history = [
            VelocitySnapshot(1, 3, 3.0),
            VelocitySnapshot(2, 1, 1.0),
            VelocitySnapshot(3, 0, 0.0),
            VelocitySnapshot(4, 0, 0.0),
            VelocitySnapshot(5, 0, 0.0),
        ]
        emit_stall_warning(5, history, [], str(tmp_events_jsonl))

        with open(tmp_events_jsonl, encoding="utf-8") as f:
            event = json.loads(f.readline())

        samples = event["velocity_samples"]
        assert len(samples) <= 5  # Last 5 samples
        assert all("iteration" in s and "stories_passed" in s and "velocity" in s for s in samples)


class TestCheckAndWarn:
    """Tests for check_and_warn()."""

    def test_no_warning_when_not_stalled(
        self, tmp_results_tsv: Path, tmp_prd_json: Path, tmp_events_jsonl: Path
    ) -> None:
        """No warning emitted when velocity is healthy."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest\tpass\t100\n")

        with open(tmp_prd_json, "w", encoding="utf-8") as f:
            json.dump({"userStories": []}, f)

        result = check_and_warn(str(tmp_results_tsv), str(tmp_prd_json), 1, str(tmp_events_jsonl))
        assert result is False
        assert not tmp_events_jsonl.exists()

    def test_warning_emitted_on_stall(self, tmp_results_tsv: Path, tmp_prd_json: Path, tmp_events_jsonl: Path) -> None:
        """Warning emitted when stall detected."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest\tpass\t100\n")
            f.write("2026-04-05T00:05:00Z\t2\t1\tUS-101\tTest\treject\t100\n")
            f.write("2026-04-05T00:10:00Z\t3\t1\tUS-102\tTest\treject\t100\n")
            f.write("2026-04-05T00:15:00Z\t4\t1\tUS-103\tTest\treject\t100\n")

        with open(tmp_prd_json, "w", encoding="utf-8") as f:
            json.dump({"userStories": []}, f)

        result = check_and_warn(str(tmp_results_tsv), str(tmp_prd_json), 4, str(tmp_events_jsonl))
        assert result is True
        assert tmp_events_jsonl.exists()

    def test_acceptance_criteria_fixture_integration(
        self, tmp_results_tsv: Path, tmp_prd_json: Path, tmp_events_jsonl: Path
    ) -> None:
        """AC4: Full integration test with [3, 1, 0, 0, 0] sequence."""
        with open(tmp_results_tsv, "w", encoding="utf-8") as f:
            f.write("timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\n")
            f.write("2026-04-05T00:00:00Z\t1\t1\tUS-100\tTest\tpass\t100\n")
            f.write("2026-04-05T00:05:00Z\t1\t2\tUS-101\tTest\tpass\t100\n")
            f.write("2026-04-05T00:10:00Z\t1\t3\tUS-102\tTest\tpass\t100\n")
            f.write("2026-04-05T00:15:00Z\t2\t1\tUS-103\tTest\tpass\t100\n")
            f.write("2026-04-05T00:20:00Z\t3\t1\tUS-104\tTest\treject\t100\n")
            f.write("2026-04-05T00:25:00Z\t4\t1\tUS-105\tTest\treject\t100\n")
            f.write("2026-04-05T00:30:00Z\t5\t1\tUS-106\tTest\treject\t100\n")

        with open(tmp_prd_json, "w", encoding="utf-8") as f:
            json.dump({"userStories": []}, f)

        # At iteration 5, should detect stall and emit warning
        result = check_and_warn(str(tmp_results_tsv), str(tmp_prd_json), 5, str(tmp_events_jsonl))
        assert result is True
        assert tmp_events_jsonl.exists()

        with open(tmp_events_jsonl, encoding="utf-8") as f:
            event = json.loads(f.readline())
            assert event["event"] == "stall_warning"
            assert event["iteration"] == 5
            assert "suggestions" in event
            assert len(event["suggestions"]) > 0
