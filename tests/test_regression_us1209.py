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
