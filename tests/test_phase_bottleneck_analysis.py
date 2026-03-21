"""tests/test_phase_bottleneck_analysis.py — Phase bottleneck analysis module tests (US-664)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add lib directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from phase_bottleneck_analysis import (
    compute_phase_bottlenecks,
    filter_results,
    load_results,
)


class TestLoadResults:
    """Tests for load_results function."""

    def test_load_results_missing_file(self, tmp_path: Path) -> None:
        """Test load_results with missing file returns empty list."""
        missing = tmp_path / "missing.tsv"
        result = load_results(missing)
        assert result == []

    def test_load_results_empty_file(self, tmp_path: Path) -> None:
        """Test load_results with empty file returns empty list."""
        empty_file = tmp_path / "empty.tsv"
        empty_file.write_text("phase\tduration_sec\n")
        result = load_results(empty_file)
        assert result == []

    def test_load_results_single_row(self, tmp_path: Path) -> None:
        """Test load_results with single data row."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text("phase\tduration_sec\nI\t720\n")
        result = load_results(tsv_file)
        assert len(result) == 1
        assert result[0]["phase"] == "I"
        assert result[0]["duration_sec"] == "720"


class TestFilterResults:
    """Tests for filter_results function."""

    def test_filter_by_iteration_min(self) -> None:
        """Test filter_results with iteration_min."""
        results = [
            {"spiral_iter": "0", "phase": "I"},
            {"spiral_iter": "1", "phase": "I"},
            {"spiral_iter": "2", "phase": "I"},
        ]
        filtered = filter_results(results, iteration_min=1)
        assert len(filtered) == 2
        assert filtered[0]["spiral_iter"] == "1"
        assert filtered[1]["spiral_iter"] == "2"

    def test_filter_by_iteration_max(self) -> None:
        """Test filter_results with iteration_max."""
        results = [
            {"spiral_iter": "0", "phase": "I"},
            {"spiral_iter": "1", "phase": "I"},
            {"spiral_iter": "2", "phase": "I"},
        ]
        filtered = filter_results(results, iteration_max=1)
        assert len(filtered) == 2
        assert filtered[0]["spiral_iter"] == "0"
        assert filtered[1]["spiral_iter"] == "1"

    def test_filter_by_iteration_range(self) -> None:
        """Test filter_results with both min and max."""
        results = [
            {"spiral_iter": "0", "phase": "I"},
            {"spiral_iter": "1", "phase": "I"},
            {"spiral_iter": "2", "phase": "I"},
            {"spiral_iter": "3", "phase": "I"},
        ]
        filtered = filter_results(results, iteration_min=1, iteration_max=2)
        assert len(filtered) == 2
        assert filtered[0]["spiral_iter"] == "1"
        assert filtered[1]["spiral_iter"] == "2"

    def test_filter_by_story_status(self) -> None:
        """Test filter_results with story_status."""
        results = [
            {"status": "pass", "phase": "I"},
            {"status": "fail", "phase": "I"},
            {"status": "pass", "phase": "I"},
        ]
        filtered = filter_results(results, story_status="pass")
        assert len(filtered) == 2
        assert filtered[0]["status"] == "pass"
        assert filtered[1]["status"] == "pass"

    def test_filter_combined(self) -> None:
        """Test filter_results with multiple filters."""
        results = [
            {"spiral_iter": "0", "status": "pass", "phase": "I"},
            {"spiral_iter": "1", "status": "pass", "phase": "I"},
            {"spiral_iter": "1", "status": "fail", "phase": "I"},
            {"spiral_iter": "2", "status": "pass", "phase": "I"},
        ]
        filtered = filter_results(results, iteration_min=1, iteration_max=1, story_status="pass")
        assert len(filtered) == 1
        assert filtered[0]["spiral_iter"] == "1"
        assert filtered[0]["status"] == "pass"

    def test_filter_no_filters(self) -> None:
        """Test filter_results with no filters returns all rows."""
        results = [
            {"spiral_iter": "0", "status": "pass"},
            {"spiral_iter": "1", "status": "fail"},
        ]
        filtered = filter_results(results)
        assert len(filtered) == 2


class TestComputePhaseBottlenecks:
    """Tests for compute_phase_bottlenecks function."""

    def test_compute_empty_results(self) -> None:
        """Test compute_phase_bottlenecks with empty results."""
        result = compute_phase_bottlenecks([])
        assert result == []

    def test_compute_single_phase(self) -> None:
        """Test compute_phase_bottlenecks with single phase."""
        results = [
            {"phase": "I", "duration_sec": "100"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "300"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        assert len(bottlenecks) == 1
        assert bottlenecks[0]["name"] == "Phase I"
        assert bottlenecks[0]["totalTime"] == 600.0
        assert bottlenecks[0]["avgPerStory"] == 200.0
        assert bottlenecks[0]["percentOfIteration"] == 100.0

    def test_compute_multi_phase(self) -> None:
        """Test compute_phase_bottlenecks with multiple phases."""
        results = [
            {"phase": "R", "duration_sec": "100"},
            {"phase": "R", "duration_sec": "100"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        assert len(bottlenecks) == 2
        # Should be sorted by phase name
        phases = {b["name"]: b for b in bottlenecks}
        assert phases["Phase I"]["totalTime"] == 400.0
        assert phases["Phase R"]["totalTime"] == 200.0
        assert phases["Phase I"]["percentOfIteration"] == 66.7
        assert phases["Phase R"]["percentOfIteration"] == 33.3

    def test_compute_missing_duration(self) -> None:
        """Test compute_phase_bottlenecks handles missing duration gracefully."""
        results = [
            {"phase": "I", "duration_sec": "100"},
            {"phase": "I"},  # Missing duration
            {"phase": "I", "duration_sec": "200"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        assert len(bottlenecks) == 1
        assert bottlenecks[0]["totalTime"] == 300.0
        assert bottlenecks[0]["avgPerStory"] == 100.0

    def test_compute_invalid_duration(self) -> None:
        """Test compute_phase_bottlenecks handles invalid duration gracefully."""
        results = [
            {"phase": "I", "duration_sec": "100"},
            {"phase": "I", "duration_sec": "invalid"},
            {"phase": "I", "duration_sec": "200"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        assert len(bottlenecks) == 1
        assert bottlenecks[0]["totalTime"] == 300.0

    def test_compute_missing_phase(self) -> None:
        """Test compute_phase_bottlenecks treats missing phase as UNKNOWN."""
        results = [
            {"phase": "I", "duration_sec": "100"},
            {"duration_sec": "50"},
            {"phase": "I", "duration_sec": "100"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phases = {b["name"]: b for b in bottlenecks}
        assert "Phase UNKNOWN" in phases
        assert "Phase I" in phases
        assert phases["Phase UNKNOWN"]["totalTime"] == 50.0

    def test_recommendation_high_percentage(self) -> None:
        """Test recommendation for phase exceeding 50% of iteration time."""
        results = [
            # Phase I with many short stories totaling 1000s
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "50"},
            {"phase": "I", "duration_sec": "500"},
            # Phase R: 100 seconds
            {"phase": "R", "duration_sec": "100"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phase_i = next(b for b in bottlenecks if b["name"] == "Phase I")
        # Phase I: 1000 / (1000 + 100) = 90.9% > 50, avg=90.9 < 300
        assert "parallelize" in phase_i["recommendation"]

    def test_recommendation_medium_percentage(self) -> None:
        """Test recommendation for phase between 30-50% of iteration time."""
        results = [
            # Phase I with 5 stories, 120s each = 600s total
            {"phase": "I", "duration_sec": "120"},
            {"phase": "I", "duration_sec": "120"},
            {"phase": "I", "duration_sec": "120"},
            {"phase": "I", "duration_sec": "120"},
            {"phase": "I", "duration_sec": "120"},
            # Phase R: 500 seconds
            {"phase": "R", "duration_sec": "500"},
            # Phase S: 200 seconds
            {"phase": "S", "duration_sec": "200"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phase_i = next(b for b in bottlenecks if b["name"] == "Phase I")
        # Phase I: 600 / (600 + 500 + 200) = 46.1%, avg=120 < 300
        assert "increase workers" in phase_i["recommendation"]

    def test_recommendation_high_avg_per_story(self) -> None:
        """Test recommendation for phase with high average time per story."""
        results = [
            # Single story in phase R that takes 3600 seconds
            {"phase": "R", "duration_sec": "3600"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phase_r = next(b for b in bottlenecks if b["name"] == "Phase R")
        # avg = 3600 > 300
        assert "reduce scope" in phase_r["recommendation"]

    def test_recommendation_high_total_time(self) -> None:
        """Test recommendation for phase with high total time."""
        results = [
            # Phase I with 10 stories, 200s each = 2000s total
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            {"phase": "I", "duration_sec": "200"},
            # Phase R: 100 seconds
            {"phase": "R", "duration_sec": "100"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phase_i = next(b for b in bottlenecks if b["name"] == "Phase I")
        # Phase I: 2000 total > 1800, but avg=200 < 300, percent=95% > 50
        # With new ordering: avg check fails, total_time check passes
        assert "optimize" in phase_i["recommendation"]

    def test_recommendation_normal_phase(self) -> None:
        """Test recommendation for normal phase parameters."""
        results = [
            # Phase S: 50 seconds with 1 story
            {"phase": "S", "duration_sec": "50"},
            # Phase M: 100 seconds
            {"phase": "M", "duration_sec": "100"},
            # Phase I: 300 seconds (large)
            {"phase": "I", "duration_sec": "100"},
            {"phase": "I", "duration_sec": "100"},
            {"phase": "I", "duration_sec": "100"},
        ]
        bottlenecks = compute_phase_bottlenecks(results)
        phase_s = next(b for b in bottlenecks if b["name"] == "Phase S")
        # Phase S: avg=50 < 300, total=50 < 1800, percent=50/(50+100+300)=11.1% < 30%
        assert "monitor" in phase_s["recommendation"]


class TestPhaseBottleneckIntegration:
    """Integration tests for complete bottleneck analysis."""

    def test_identify_max_time_phase(self, tmp_path: Path) -> None:
        """Test that endpoint identifies phase with max totalTime across iterations."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text(
            "spiral_iter\tphase\tduration_sec\n0\tR\t100\n0\tI\t500\n0\tV\t50\n1\tR\t150\n1\tI\t800\n1\tV\t75\n"
        )

        rows = load_results(tsv_file)
        filtered = filter_results(rows)
        bottlenecks = compute_phase_bottlenecks(filtered)

        # Phase I should have max totalTime: 500 + 800 = 1300
        phase_i = next(b for b in bottlenecks if b["name"] == "Phase I")
        assert phase_i["totalTime"] == 1300.0

        # All phases should have recommendations
        for bottleneck in bottlenecks:
            assert "recommendation" in bottleneck
            assert len(bottleneck["recommendation"]) > 0

    def test_actionable_recommendations(self, tmp_path: Path) -> None:
        """Test that all recommendations contain actionable text."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text("phase\tduration_sec\nR\t100\nI\t2000\nV\t50\n")

        rows = load_results(tsv_file)
        bottlenecks = compute_phase_bottlenecks(rows)

        actionable_keywords = {"parallelize", "increase", "reduce", "optimize", "monitor"}
        for bottleneck in bottlenecks:
            recommendation = bottleneck["recommendation"]
            assert any(keyword in recommendation for keyword in actionable_keywords), (
                f"Recommendation '{recommendation}' missing actionable keyword"
            )

    def test_filter_and_compute_integration(self, tmp_path: Path) -> None:
        """Test complete flow: load, filter, and compute."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text(
            "spiral_iter\tstatus\tphase\tduration_sec\n"
            "0\tpass\tR\t100\n"
            "0\tpass\tI\t500\n"
            "1\tpass\tR\t150\n"
            "1\tfail\tI\t800\n"
            "2\tpass\tI\t600\n"
        )

        rows = load_results(tsv_file)
        # Filter to iteration 0-1, only pass status
        filtered = filter_results(rows, iteration_min=0, iteration_max=1, story_status="pass")
        bottlenecks = compute_phase_bottlenecks(filtered)

        # Should have R: 100+150=250, I: 500
        phase_r = next(b for b in bottlenecks if b["name"] == "Phase R")
        phase_i = next(b for b in bottlenecks if b["name"] == "Phase I")

        assert phase_r["totalTime"] == 250.0
        assert phase_i["totalTime"] == 500.0
        assert phase_i["percentOfIteration"] == 66.7
