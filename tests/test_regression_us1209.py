"""Regression tests for spiral trace-dependencies CLI command (US-1209).

These tests guard against breakage of the trace-dependencies feature (US-675)
which resolves and visualizes full dependency chains across projects, detects
circular dependencies, and shows sub-project boundaries.

Test invocation:
  uv run pytest tests/test_regression_us1209.py -v
  uv run pytest tests/ -k us_1209 -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.us_1209
def test_trace_dependencies_resolves_chain() -> None:
    """Test that trace-dependencies resolves a dependency chain correctly.

    Acceptance criteria:
    - uv run pytest tests/test_regression_us1209.py::test_trace_dependencies_resolves_chain -v exits 0
    """
    fixture_prd = Path(__file__).parent / "fixtures" / "trace_deps_fixture.json"
    assert fixture_prd.exists(), f"Fixture PRD not found at {fixture_prd}"

    # Invoke CLI: spiral trace-dependencies US-101 --prd <fixture> --json
    result = subprocess.run(
        [sys.executable, "main.py", "trace-dependencies", "US-101", "--prd", str(fixture_prd), "--json"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0, f"Command failed with return code {result.returncode}: {result.stderr}"

    output = json.loads(result.stdout)

    # Verify output structure: story_id, dependencies, has_cycle
    assert output["story_id"] == "US-101"
    assert "dependencies" in output
    assert "has_cycle" in output
    assert isinstance(output["dependencies"], list)
    assert isinstance(output["has_cycle"], bool)

    # Verify chain is resolved: US-101 -> US-102 -> US-103
    dep_ids = [d["story_id"] for d in output["dependencies"]]
    assert "US-102" in dep_ids, f"US-102 not in resolved dependencies: {dep_ids}"
    assert "US-103" in dep_ids, f"US-103 not in resolved dependencies: {dep_ids}"

    # Verify each dependency has required fields: story_id, sub_project, depth, files
    for dep in output["dependencies"]:
        assert "story_id" in dep
        assert "sub_project" in dep
        assert "depth" in dep
        assert "files" in dep

    # Verify no cycle for this chain
    assert output["has_cycle"] is False

    # Verify depth increases for transitive dependencies
    us102 = next((d for d in output["dependencies"] if d["story_id"] == "US-102"), None)
    us103 = next((d for d in output["dependencies"] if d["story_id"] == "US-103"), None)
    assert us102 is not None
    assert us103 is not None
    assert us102["depth"] == 1
    assert us103["depth"] == 2

    # Verify files are preserved in dependencies
    assert us102["files"] == ["middle.py"]
    assert us103["files"] == ["leaf.py"]


@pytest.mark.us_1209
def test_trace_dependencies_detects_circular() -> None:
    """Test that trace-dependencies detects circular dependencies.

    Acceptance criteria:
    - uv run pytest tests/test_regression_us1209.py::test_trace_dependencies_detects_circular -v exits 0
    """
    fixture_prd = Path(__file__).parent / "fixtures" / "trace_deps_fixture.json"
    assert fixture_prd.exists(), f"Fixture PRD not found at {fixture_prd}"

    # Invoke CLI: spiral trace-dependencies US-201 --prd <fixture> --json
    result = subprocess.run(
        [sys.executable, "main.py", "trace-dependencies", "US-201", "--prd", str(fixture_prd), "--json"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0, f"Command failed with return code {result.returncode}: {result.stderr}"

    output = json.loads(result.stdout)

    # Verify output structure
    assert output["story_id"] == "US-201"
    assert "dependencies" in output
    assert "has_cycle" in output

    # Verify cycle is detected
    assert output["has_cycle"] is True, "Cycle should be detected for US-201 -> US-202 -> US-201"

    # Verify cycle_path is included when has_cycle is True
    assert "cycle_path" in output, "cycle_path should be included when has_cycle is True"
    assert isinstance(output["cycle_path"], list)
    assert len(output["cycle_path"]) >= 2, "cycle_path should contain at least 2 story IDs"

    # Verify both stories in the cycle are mentioned
    cycle_ids = set(output["cycle_path"])
    assert "US-201" in cycle_ids or any("US-201" in str(d) for d in output["dependencies"])
    assert "US-202" in cycle_ids or any("US-202" in str(d) for d in output["dependencies"])


@pytest.mark.us_1209
def test_trace_dependencies_plain_text_output() -> None:
    """Test that trace-dependencies outputs plain text tree with all story IDs.

    Acceptance criteria (US-1303):
    - Test invokes CLI with fixture prd.json and captures stdout
    - Assert all expected story IDs appear in output
    - uv run pytest tests/ -k us_1209 -v exits 0
    """
    fixture_prd = Path(__file__).parent / "fixtures" / "trace_deps_fixture.json"
    assert fixture_prd.exists(), f"Fixture PRD not found at {fixture_prd}"

    # Invoke CLI without --json to get plain text output
    result = subprocess.run(
        [sys.executable, "main.py", "trace-dependencies", "US-101", "--prd", str(fixture_prd)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    assert result.returncode == 0, f"Command failed with return code {result.returncode}: {result.stderr}"

    stdout = result.stdout

    # Verify all expected story IDs appear in the output
    assert "US-101" in stdout, "Root story ID US-101 should appear in plain text output"
    assert "US-102" in stdout, "Dependency story ID US-102 should appear in plain text output"
    assert "US-103" in stdout, "Transitive dependency story ID US-103 should appear in plain text output"

    # Verify file paths appear in the output
    assert "root.py" in stdout, "File path root.py should appear in output"
    assert "middle.py" in stdout, "File path middle.py should appear in output"
    assert "leaf.py" in stdout, "File path leaf.py should appear in output"


@pytest.mark.us_1209
def test_trace_dependencies_circular_exit_code() -> None:
    """Test that circular dependency detection triggers non-zero exit code.

    Acceptance criteria (US-1303):
    - Test asserts circular-dependency detection triggers non-zero exit code
    - When a cycle is present, the CLI should exit with code 2 (not 0)
    - uv run pytest tests/ -k us_1209 -v exits 0
    """
    fixture_prd = Path(__file__).parent / "fixtures" / "trace_deps_fixture.json"
    assert fixture_prd.exists(), f"Fixture PRD not found at {fixture_prd}"

    # Invoke CLI for circular dependency without --json
    result = subprocess.run(
        [sys.executable, "main.py", "trace-dependencies", "US-201", "--prd", str(fixture_prd)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    # Verify non-zero exit code (code 2 for circular dependency)
    assert result.returncode != 0, (
        f"Command should exit with non-zero code for circular dependency, got {result.returncode}"
    )
    assert result.returncode == 2, f"Expected exit code 2 for circular dependency, got {result.returncode}"

    # Verify error message appears in stderr
    assert "Circular dependency detected" in result.stderr, (
        "Error message should contain 'Circular dependency detected'"
    )

    # Verify cycle markers appear in stdout tree
    assert "*** CYCLE ***" in result.stdout, "Cycle markers should appear in the output tree"

    # Verify story IDs involved in the cycle appear in output
    assert "US-201" in result.stdout, "Story ID US-201 should appear in cycle output"
    assert "US-202" in result.stdout, "Story ID US-202 should appear in cycle output"
