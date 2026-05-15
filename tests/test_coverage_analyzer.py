"""Tests for lib/coverage_analyzer.py"""

from __future__ import annotations

from lib.coverage_analyzer import generate_coverage_matrix


class TestCoverageMatrixGeneration:
    """Tests for generate_coverage_matrix()"""

    def test_coverage_matrix_generation(self) -> None:
        """Test basic coverage matrix generation from coverage.json data."""
        coverage_data = {
            "totals": {"percent_covered": 75.5},
            "files": {
                "lib/module_a.py": {
                    "summary": {"percent_covered": 85.0, "num_statements": 100, "missing_lines": 15},
                },
                "lib/module_b.py": {
                    "summary": {"percent_covered": 40.0, "num_statements": 50, "missing_lines": 30},
                },
                "lib/module_c.py": {
                    "summary": {"percent_covered": 65.0, "num_statements": 80, "missing_lines": 28},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)

        assert len(result["files"]) == 3
        assert result["summary"]["total_files"] == 3
        assert result["summary"]["avg_coverage"] == 63.3

    def test_heatmap_red_color_under_50_percent(self) -> None:
        """Test that files with <50% coverage get 'red' status."""
        coverage_data = {
            "totals": {"percent_covered": 40.0},
            "files": {
                "lib/low_coverage.py": {
                    "summary": {"percent_covered": 30.0, "num_statements": 100, "missing_lines": 70},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)
        file_entry = result["files"][0]

        assert file_entry["coverage_percent"] == 30.0
        assert file_entry["status"] == "red"
        assert file_entry["uncovered_lines"] == 70

    def test_heatmap_yellow_color_50_to_80_percent(self) -> None:
        """Test that files with 50-80% coverage get 'yellow' status."""
        coverage_data = {
            "totals": {"percent_covered": 65.0},
            "files": {
                "lib/medium_coverage.py": {
                    "summary": {"percent_covered": 75.0, "num_statements": 100, "missing_lines": 25},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)
        file_entry = result["files"][0]

        assert file_entry["coverage_percent"] == 75.0
        assert file_entry["status"] == "yellow"

    def test_heatmap_green_color_above_80_percent(self) -> None:
        """Test that files with >80% coverage get 'green' status."""
        coverage_data = {
            "totals": {"percent_covered": 85.0},
            "files": {
                "lib/high_coverage.py": {
                    "summary": {"percent_covered": 90.0, "num_statements": 100, "missing_lines": 10},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)
        file_entry = result["files"][0]

        assert file_entry["coverage_percent"] == 90.0
        assert file_entry["status"] == "green"
        assert file_entry["covered_lines"] == 90

    def test_empty_coverage_data(self) -> None:
        """Test handling of empty coverage data."""
        result = generate_coverage_matrix({})

        assert result["files"] == []
        assert result["summary"]["total_files"] == 0
        assert result["summary"]["covered_files"] == 0
        assert result["summary"]["avg_coverage"] == 0.0

    def test_files_sorted_by_coverage(self) -> None:
        """Test that files are sorted by coverage percentage (lowest first)."""
        coverage_data = {
            "totals": {"percent_covered": 70.0},
            "files": {
                "lib/high.py": {
                    "summary": {"percent_covered": 95.0, "num_statements": 100, "missing_lines": 5},
                },
                "lib/low.py": {
                    "summary": {"percent_covered": 30.0, "num_statements": 100, "missing_lines": 70},
                },
                "lib/medium.py": {
                    "summary": {"percent_covered": 60.0, "num_statements": 100, "missing_lines": 40},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)
        files = result["files"]

        assert files[0]["coverage_percent"] == 30.0
        assert files[1]["coverage_percent"] == 60.0
        assert files[2]["coverage_percent"] == 95.0

    def test_summary_statistics_accuracy(self) -> None:
        """Test accuracy of summary statistics."""
        coverage_data = {
            "totals": {"percent_covered": 70.0},
            "files": {
                "lib/a.py": {
                    "summary": {"percent_covered": 85.0, "num_statements": 100, "missing_lines": 15},
                },
                "lib/b.py": {
                    "summary": {"percent_covered": 55.0, "num_statements": 100, "missing_lines": 45},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)
        summary = result["summary"]

        assert summary["total_files"] == 2
        assert summary["covered_files"] == 1  # Only one file with status 'green'
        assert summary["avg_coverage"] == 70.0
        assert summary["overall_status"] == "yellow"  # avg_coverage is 70%

    def test_overall_status_red_low_average(self) -> None:
        """Test that overall status is 'red' when average coverage is <50%."""
        coverage_data = {
            "totals": {"percent_covered": 40.0},
            "files": {
                "lib/a.py": {
                    "summary": {"percent_covered": 35.0, "num_statements": 100, "missing_lines": 65},
                },
                "lib/b.py": {
                    "summary": {"percent_covered": 45.0, "num_statements": 100, "missing_lines": 55},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)

        assert result["summary"]["overall_status"] == "red"

    def test_overall_status_yellow_medium_average(self) -> None:
        """Test that overall status is 'yellow' when average coverage is 50-80%."""
        coverage_data = {
            "totals": {"percent_covered": 65.0},
            "files": {
                "lib/a.py": {
                    "summary": {"percent_covered": 70.0, "num_statements": 100, "missing_lines": 30},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)

        assert result["summary"]["overall_status"] == "yellow"

    def test_overall_status_green_high_average(self) -> None:
        """Test that overall status is 'green' when average coverage is >=80%."""
        coverage_data = {
            "totals": {"percent_covered": 85.0},
            "files": {
                "lib/a.py": {
                    "summary": {"percent_covered": 88.0, "num_statements": 100, "missing_lines": 12},
                },
                "lib/b.py": {
                    "summary": {"percent_covered": 82.0, "num_statements": 100, "missing_lines": 18},
                },
            },
        }

        result = generate_coverage_matrix(coverage_data)

        assert result["summary"]["overall_status"] == "green"
