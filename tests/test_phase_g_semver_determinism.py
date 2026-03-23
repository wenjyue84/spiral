"""Tests for Phase G SemVer calculation determinism from results.tsv (US-1025).

Validates that Phase G's semver bump calculation produces identical results
across multiple calls with identical input data (mocked results.tsv).
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from semver_calculator import calculate_next_version_from_results_tsv


def _write_mock_results(path: Path, rows: list[dict[str, str]]) -> None:
    """Write mock results.tsv with story_id, retry_count, complexity columns."""
    fieldnames = ["story_id", "retry_count", "complexity"]
    with open(str(path), "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def test_deterministic_three_runs(tmp_path: Path) -> None:
    """Test: invoking semver calculation 3 times with same mocked results.tsv yields identical version strings.

    US-1025 AC1: semver calculation function called 3 times with identical
    results.tsv data produces identical version strings each time.
    """
    results_tsv = tmp_path / "results.tsv"

    # Mock results with 3 stories, 2 with retry_count >= 3
    rows = [
        {"story_id": "US-001", "retry_count": "3", "complexity": "5"},
        {"story_id": "US-002", "retry_count": "2", "complexity": "3"},
        {"story_id": "US-003", "retry_count": "4", "complexity": "8"},
    ]
    _write_mock_results(results_tsv, rows)

    # Call semver calculation 3 times with same data
    previous_version = "1.0.0"
    version1 = calculate_next_version_from_results_tsv(previous_version, str(results_tsv))
    version2 = calculate_next_version_from_results_tsv(previous_version, str(results_tsv))
    version3 = calculate_next_version_from_results_tsv(previous_version, str(results_tsv))

    # All three should be identical
    assert version1 == version2, f"Versions differ: {version1} != {version2}"
    assert version2 == version3, f"Versions differ: {version2} != {version3}"


def test_minor_vs_patch_threshold(tmp_path: Path) -> None:
    """Test: 2+ stories with retry_count>=3 produces minor bump; 0 such stories produces patch bump only.

    US-1025 AC2: semver bump tier depends on count of stories with retry_count >= 3:
    - If count >= 2: bump minor
    - Otherwise (0 or 1): bump patch
    """
    # Test case 1: 2+ stories with retry_count >= 3 → minor bump (1.0.0 → 1.1.0)
    results_tsv_minor = tmp_path / "results_minor.tsv"
    rows_minor = [
        {"story_id": "US-001", "retry_count": "3", "complexity": "5"},
        {"story_id": "US-002", "retry_count": "1", "complexity": "3"},
        {"story_id": "US-003", "retry_count": "4", "complexity": "8"},
    ]
    _write_mock_results(results_tsv_minor, rows_minor)

    version_minor = calculate_next_version_from_results_tsv("1.0.0", str(results_tsv_minor))
    assert version_minor == "1.1.0", f"Expected minor bump to 1.1.0, got {version_minor}"

    # Test case 2: 0 stories with retry_count >= 3 → patch bump (1.0.0 → 1.0.1)
    results_tsv_patch = tmp_path / "results_patch.tsv"
    rows_patch = [
        {"story_id": "US-001", "retry_count": "1", "complexity": "5"},
        {"story_id": "US-002", "retry_count": "2", "complexity": "3"},
    ]
    _write_mock_results(results_tsv_patch, rows_patch)

    version_patch = calculate_next_version_from_results_tsv("1.0.0", str(results_tsv_patch))
    assert version_patch == "1.0.1", f"Expected patch bump to 1.0.1, got {version_patch}"

    # Test case 3: 1 story with retry_count >= 3 → patch bump (1.5.2 → 1.5.3)
    results_tsv_edge = tmp_path / "results_edge.tsv"
    rows_edge = [
        {"story_id": "US-001", "retry_count": "3", "complexity": "5"},
    ]
    _write_mock_results(results_tsv_edge, rows_edge)

    version_edge = calculate_next_version_from_results_tsv("1.5.2", str(results_tsv_edge))
    assert version_edge == "1.5.3", f"Expected patch bump to 1.5.3, got {version_edge}"
