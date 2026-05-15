"""Coverage analyzer: parse coverage.json and generate file-level heatmap data."""

from __future__ import annotations

from typing import Any, TypedDict


class CoverageFile(TypedDict):
    """File coverage entry for heatmap."""

    path: str
    coverage_percent: float
    status: str  # 'red' | 'yellow' | 'green'
    covered_lines: int
    uncovered_lines: int


class CoverageSummary(TypedDict):
    """Summary statistics for coverage."""

    total_files: int
    covered_files: int
    avg_coverage: float
    overall_status: str


class CoverageMatrix(TypedDict):
    """Complete coverage heatmap data."""

    files: list[CoverageFile]
    summary: CoverageSummary


def generate_coverage_matrix(coverage_data: dict[str, Any]) -> CoverageMatrix:
    """Parse coverage.json and generate file-level heatmap data.

    Args:
        coverage_data: dict from coverage.json with structure:
            {
              "totals": {"percent_covered": 75.5},
              "files": {
                "path/to/file.py": {
                  "summary": {
                    "percent_covered": 80.0,
                    "num_statements": 50,
                    "missing_lines": 10
                  }
                }
              }
            }

    Returns:
        CoverageMatrix with files list and summary statistics.
    """
    files: list[CoverageFile] = []

    if not coverage_data or "files" not in coverage_data:
        empty_summary: CoverageSummary = {
            "total_files": 0,
            "covered_files": 0,
            "avg_coverage": 0.0,
            "overall_status": "green",
        }
        return {"files": [], "summary": empty_summary}

    for file_path, file_info in coverage_data["files"].items():
        if not isinstance(file_info, dict) or "summary" not in file_info:
            continue

        summary = file_info["summary"]
        coverage_percent = float(summary.get("percent_covered", 0.0))
        num_statements = int(summary.get("num_statements", 0))
        missing_lines = int(summary.get("missing_lines", 0))
        covered_lines = num_statements - missing_lines

        # Determine status color based on coverage percentage
        if coverage_percent < 50:
            status = "red"
        elif coverage_percent < 80:
            status = "yellow"
        else:
            status = "green"

        files.append(
            {
                "path": file_path,
                "coverage_percent": coverage_percent,
                "status": status,
                "covered_lines": max(0, covered_lines),
                "uncovered_lines": max(0, missing_lines),
            }
        )

    # Sort by coverage percentage (ascending) to put worst first
    files.sort(key=lambda f: f["coverage_percent"])

    # Compute summary statistics
    total_files = len(files)
    covered_files = sum(1 for f in files if f["status"] == "green")
    avg_coverage = sum(f["coverage_percent"] for f in files) / total_files if total_files > 0 else 0.0

    # Overall status: green if avg >= 80%, yellow if >= 50%, red otherwise
    if avg_coverage >= 80:
        overall_status = "green"
    elif avg_coverage >= 50:
        overall_status = "yellow"
    else:
        overall_status = "red"

    return {
        "files": files,
        "summary": {
            "total_files": total_files,
            "covered_files": covered_files,
            "avg_coverage": round(avg_coverage, 1),
            "overall_status": overall_status,
        },
    }
