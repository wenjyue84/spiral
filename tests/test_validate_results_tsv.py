#!/usr/bin/env python3
"""Test validate_results_tsv — duplicate detection and token range validation."""

import os
import tempfile
from collections.abc import Generator

import pytest

from lib.spiral.validate_results_tsv import validate


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """Temp directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_validate_duplicates(temp_dir: str) -> None:
    """Test validator detects duplicate story_id rows."""
    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write("story_id\tcache_read_tokens\n")
        f.write("US-001\t1000\n")
        f.write("US-001\t2000\n")  # Duplicate story_id

    result = validate(tsv_path)

    assert isinstance(result["errors"], list)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["check_counts"], dict)
    assert "rows" in result["check_counts"]
    assert "checks_run" in result["check_counts"]
    assert any("Duplicate" in e for e in result["errors"])


def test_validate_token_range(temp_dir: str) -> None:
    """Test validator detects token counts out of range."""
    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write("story_id\tcache_read_tokens\n")
        f.write("US-001\t-100\n")  # Negative
        f.write("US-002\t2000000\n")  # > 1000000

    result = validate(tsv_path)

    assert any("range" in e for e in result["errors"]), f"Expected range error. Got: {result['errors']}"


def test_validate_missing_story_id(temp_dir: str) -> None:
    """Test validator handles missing story_id gracefully."""
    tsv_path = os.path.join(temp_dir, "results.tsv")
    with open(tsv_path, "w") as f:
        f.write("story_id\tcache_read_tokens\n")
        f.write("\t1000\n")  # Empty story_id
        f.write("US-001\t2000\n")

    result = validate(tsv_path)

    # Should not crash, has valid structure
    assert "errors" in result
    assert "warnings" in result
    assert "check_counts" in result
