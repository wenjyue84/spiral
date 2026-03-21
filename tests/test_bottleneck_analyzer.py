"""tests/test_bottleneck_analyzer.py — Tests for lib/dashboard/bottleneck_analyzer.py (US-670)."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from lib.dashboard.bottleneck_analyzer import BottleneckAnalyzer


class TestBottleneckAnalyzerBasics:
    """Test basic initialization and data loading."""

    def test_init_with_default_path(self) -> None:
        """BottleneckAnalyzer initializes with default path."""
        analyzer = BottleneckAnalyzer()
        assert analyzer.results_path == Path(".spiral/results.tsv")

    def test_init_with_custom_path(self) -> None:
        """BottleneckAnalyzer accepts custom path."""
        custom_path = Path("/tmp/custom.tsv")
        analyzer = BottleneckAnalyzer(custom_path)
        assert analyzer.results_path == custom_path

    def test_missing_file_returns_empty_list(self) -> None:
        """analyze() returns empty list when file doesn't exist."""
        analyzer = BottleneckAnalyzer(Path("/nonexistent/path.tsv"))
        result = analyzer.analyze()
        assert result == []


class TestBottleneckAnalyzerCalculations:
    """Test variance and duration calculations."""

    def test_single_phase_single_story(self) -> None:
        """Single phase with single story has zero variance."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
            assert result[0]["avg_duration_ms"] == 10000.0
            assert result[0]["variance"] == 0.0
            assert result[0]["story_count"] == 1
        finally:
            path.unlink()

    def test_multiple_stories_same_phase(self) -> None:
        """Multiple stories in same phase calculates variance."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            # Three stories with durations: 10, 20, 30 seconds
            # Mean = 20, StdDev ≈ 10, CV = 0.5
            for i, dur in enumerate([10, 20, 30], 1):
                writer.writerow(
                    {
                        "spiral_iter": "1",
                        "story_id": f"US-{i:03d}",
                        "phase": "I",
                        "duration_sec": str(dur),
                        "status": "passed",
                    }
                )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
            assert abs(result[0]["avg_duration_ms"] - 20000.0) < 1  # 20 sec = 20000 ms
            assert result[0]["story_count"] == 3
            # Coefficient of variance: stdev / mean = 10 / 20 = 0.5
            assert abs(result[0]["variance"] - 0.5) < 0.01
        finally:
            path.unlink()

    def test_multiple_phases_sorted_by_duration(self) -> None:
        """Multiple phases sorted by avg_duration_ms descending."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            # Phase I: 30 sec average
            # Phase R: 10 sec average
            # Phase M: 20 sec average
            phases = [("I", "30"), ("R", "10"), ("M", "20")]
            for phase, dur in phases:
                writer.writerow(
                    {
                        "spiral_iter": "1",
                        "story_id": f"US-{phase}",
                        "phase": phase,
                        "duration_sec": dur,
                        "status": "passed",
                    }
                )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 3
            # Should be sorted by avg_duration_ms descending: I (30000), M (20000), R (10000)
            assert result[0]["phase"] == "I"
            assert result[0]["avg_duration_ms"] == 30000.0
            assert result[1]["phase"] == "M"
            assert result[1]["avg_duration_ms"] == 20000.0
            assert result[2]["phase"] == "R"
            assert result[2]["avg_duration_ms"] == 10000.0
        finally:
            path.unlink()


class TestBottleneckAnalyzerFiltering:
    """Test filtering of zero-duration and empty phases."""

    def test_skips_zero_duration(self) -> None:
        """Rows with zero duration_sec are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "duration_sec": "0",
                    "status": "passed",
                }
            )
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-002",
                    "phase": "I",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
            assert result[0]["story_count"] == 1  # Only one non-zero story
        finally:
            path.unlink()

    def test_only_includes_phases_with_stories(self) -> None:
        """Phases with all zero durations are excluded."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            # Phase I: has data
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            # Phase R: all zeros, should be excluded
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-002",
                    "phase": "R",
                    "duration_sec": "0",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
        finally:
            path.unlink()

    def test_invalid_duration_skipped(self) -> None:
        """Rows with non-numeric duration are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "duration_sec": "invalid",
                    "status": "passed",
                }
            )
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-002",
                    "phase": "I",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["story_count"] == 1
        finally:
            path.unlink()

    def test_missing_duration_treated_as_zero(self) -> None:
        """Missing duration_sec column is treated as zero."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "status", "duration_sec"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "status": "passed",
                    "duration_sec": "",
                }
            )
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-002",
                    "phase": "I",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["story_count"] == 1
        finally:
            path.unlink()


class TestBottleneckAnalyzerPhaseHandling:
    """Test phase name normalization and handling."""

    def test_phase_uppercase_normalization(self) -> None:
        """Phase names are normalized to uppercase."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "i",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
        finally:
            path.unlink()

    def test_missing_phase_defaults_to_unknown(self) -> None:
        """Missing phase defaults to UNKNOWN."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "UNKNOWN"
        finally:
            path.unlink()

    def test_whitespace_stripped_from_phase(self) -> None:
        """Whitespace around phase names is stripped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "  I  ",
                    "duration_sec": "10",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            assert result[0]["phase"] == "I"
        finally:
            path.unlink()


class TestBottleneckAnalyzerRounding:
    """Test proper rounding of output values."""

    def test_duration_ms_rounded_to_one_decimal(self) -> None:
        """avg_duration_ms is rounded to 1 decimal place."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "spiral_iter": "1",
                    "story_id": "US-001",
                    "phase": "I",
                    "duration_sec": "3.14159",
                    "status": "passed",
                }
            )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            # 3.14159 seconds = 3141.59 ms, rounded to 3141.6
            assert result[0]["avg_duration_ms"] == 3141.6
        finally:
            path.unlink()

    def test_variance_rounded_to_three_decimals(self) -> None:
        """variance is rounded to 3 decimal places."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            # Three values: 1, 2, 3. Mean = 2, StdDev = 1, CV = 0.5
            for dur in [1, 2, 3]:
                writer.writerow(
                    {
                        "spiral_iter": "1",
                        "story_id": f"US-{dur:03d}",
                        "phase": "I",
                        "duration_sec": str(dur),
                        "status": "passed",
                    }
                )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert len(result) == 1
            # Variance should be rounded to 3 decimals
            assert isinstance(result[0]["variance"], float)
            # StdDev = sqrt(((1-2)^2 + (2-2)^2 + (3-2)^2) / 2) = sqrt(2/2) = 1
            # CV = 1 / 2 = 0.5, rounded to 0.5
            assert result[0]["variance"] == 0.5
        finally:
            path.unlink()


class TestBottleneckAnalyzerIntegration:
    """Integration tests with realistic data."""

    def test_full_analysis_workflow(self) -> None:
        """Full workflow with multiple phases and stories."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "spiral_iter",
                    "story_id",
                    "phase",
                    "duration_sec",
                    "status",
                    "model",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            # Phase I: 5 stories with varying durations (10, 20, 30, 40, 50 sec)
            # Average = 30 sec
            for i in range(5):
                writer.writerow(
                    {
                        "spiral_iter": "1",
                        "story_id": f"US-I-{i:03d}",
                        "phase": "I",
                        "duration_sec": str((i + 1) * 10),
                        "status": "passed",
                        "model": "haiku",
                    }
                )
            # Phase R: 2 stories (60, 70 sec)
            # Average = 65 sec (higher than I)
            for i in range(2):
                writer.writerow(
                    {
                        "spiral_iter": "1",
                        "story_id": f"US-R-{i:03d}",
                        "phase": "R",
                        "duration_sec": str((i + 6) * 10),
                        "status": "passed",
                        "model": "haiku",
                    }
                )
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            # Expect 2 phases
            assert len(result) == 2

            # Phase R should have highest avg duration (65 sec = 65000 ms)
            assert result[0]["phase"] == "R"
            assert result[0]["story_count"] == 2

            # Phase I should be second (30 sec = 30000 ms)
            assert result[1]["phase"] == "I"
            assert result[1]["story_count"] == 5
        finally:
            path.unlink()

    def test_empty_file_returns_empty_list(self) -> None:
        """Empty TSV file with only headers returns empty list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["spiral_iter", "story_id", "phase", "duration_sec", "status"],
                delimiter="\t",
            )
            writer.writeheader()
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            result = analyzer.analyze()

            assert result == []
        finally:
            path.unlink()

    def test_malformed_tsv_handled_gracefully(self) -> None:
        """Malformed TSV is handled gracefully without raising."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False) as f:
            f.write("Not a valid TSV file\n")
            f.write("Random\tincomplete\tdata\n")
            f.flush()
            path = Path(f.name)

        try:
            analyzer = BottleneckAnalyzer(path)
            # Should not raise, returns empty or partial results
            result = analyzer.analyze()
            assert isinstance(result, list)
        finally:
            path.unlink()
