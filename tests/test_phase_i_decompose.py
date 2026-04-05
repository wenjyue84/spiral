"""Integration tests for Phase I auto-decompose on triple failure (US-569).

Tests verify that the auto-decompose feature correctly creates sub-stories in
prd.json when called after 3 Phase I failures on an oversized story.

The tests call lib/workers/decompose_story.py directly with a mocked Claude
subprocess, simulating the behaviour triggered after 3 Ralph failures.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# conftest.py already inserts lib/ and project root; be explicit for clarity
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

# ---------------------------------------------------------------------------
# Mock Claude response: 4 ordered sub-stories
# ---------------------------------------------------------------------------

_MOCK_DECOMPOSE_RESPONSE = json.dumps(
    {
        "ordered": True,
        "stories": [
            {
                "title": "Sub-story 1: First part",
                "description": "Implement the first component",
                "acceptanceCriteria": ["AC 1 is satisfied"],
                "technicalNotes": [],
                "estimatedComplexity": "small",
            },
            {
                "title": "Sub-story 2: Second part",
                "description": "Implement the second component",
                "acceptanceCriteria": ["AC 2 is satisfied"],
                "technicalNotes": [],
                "estimatedComplexity": "small",
            },
            {
                "title": "Sub-story 3: Third part",
                "description": "Implement the third component",
                "acceptanceCriteria": ["AC 3 is satisfied"],
                "technicalNotes": [],
                "estimatedComplexity": "small",
            },
            {
                "title": "Sub-story 4: Fourth part",
                "description": "Implement the fourth component",
                "acceptanceCriteria": ["AC 4 is satisfied"],
                "technicalNotes": [],
                "estimatedComplexity": "small",
            },
        ],
    }
)


def _make_oversized_prd() -> dict:
    """Create a minimal prd.json with one large story (US-100)."""
    return {
        "schemaVersion": 1,
        "productName": "TestProduct",
        "branchName": "main",
        "overview": "Test PRD for auto-decompose integration tests",
        "goals": [],
        "userStories": [
            {
                "id": "US-100",
                "title": "Oversized Story That Must Be Decomposed",
                "passes": False,
                "priority": "medium",
                "description": "This story is too large to implement in one agent turn",
                "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
                "dependencies": [],
                "estimatedComplexity": "large",
            }
        ],
    }


@pytest.fixture
def decompose_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up tmp_path with prd.json, retry-counts.json, and progress.txt.

    US-100 is the only story (so decompose assigns children US-101..US-104).
    retry-counts.json is set to {"US-100": 2} simulating two prior failures;
    the third would trigger auto-decompose in the full Phase I loop.
    Here we call decompose_story directly to test the decompose logic itself.

    Returns the Path to the prd.json file.
    """
    monkeypatch.chdir(tmp_path)

    # Write oversized story prd.json
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(_make_oversized_prd()), encoding="utf-8")

    # Write retry-counts.json: US-100 has been tried twice; third try triggers decompose
    retry_path = tmp_path / "retry-counts.json"
    retry_path.write_text(json.dumps({"US-100": 2}), encoding="utf-8")

    # Write empty progress.txt (required by decompose_story for failure context)
    (tmp_path / "progress.txt").write_text("", encoding="utf-8")

    return prd_path


def _run_decompose(prd_path: Path) -> int:
    """Call decompose_story.main() with a mocked Claude response.

    Patches call_claude to avoid real API calls.
    Returns the exit code from main().
    """
    from lib.workers import decompose_story

    old_argv = sys.argv
    sys.argv = [
        "decompose_story.py",
        "--story-id",
        "US-100",
        "--prd",
        str(prd_path),
        "--progress",
        str(prd_path.parent / "progress.txt"),
    ]
    try:
        with patch.object(decompose_story, "call_claude", return_value=_MOCK_DECOMPOSE_RESPONSE):
            return decompose_story.main()
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_decompose_creates_dependency_chain(decompose_setup: Path) -> None:
    """Verify decompose produces 4 sub-stories with a sequential dependency chain.

    With ordered=True in Claude's response, each sub-story (except the first)
    must declare a dependency on the previous one:
        child-2 → child-1, child-3 → child-2, child-4 → child-3
    """
    prd_path = decompose_setup
    ret = _run_decompose(prd_path)
    assert ret == 0, f"decompose_story.main() returned non-zero exit code {ret}"

    prd = json.loads(prd_path.read_text(encoding="utf-8"))
    sub_stories = [s for s in prd["userStories"] if s.get("_decomposedFrom") == "US-100"]

    assert len(sub_stories) == 4, (
        f"Expected 4 sub-stories decomposed from US-100, got {len(sub_stories)}: {[s['id'] for s in sub_stories]}"
    )

    child_ids = [s["id"] for s in sub_stories]

    # First child has no dependency on siblings
    assert child_ids[0] not in sub_stories[0].get("dependencies", []), (
        f"First child {child_ids[0]} should not depend on itself"
    )

    # Each subsequent child must depend on the previous one
    for i in range(1, 4):
        deps = sub_stories[i].get("dependencies", [])
        assert child_ids[i - 1] in deps, f"{child_ids[i]} must depend on {child_ids[i - 1]}, but dependencies={deps}"


def test_decompose_marks_parent_status(decompose_setup: Path) -> None:
    """Verify decompose marks the parent story as decomposed in prd.json.

    After decomposition US-100 must have:
      - _decomposed = True  (skipped by ralph workers going forward)
      - _decomposedInto = [child_id_1, child_id_2, child_id_3, child_id_4]
    """
    prd_path = decompose_setup
    ret = _run_decompose(prd_path)
    assert ret == 0, f"decompose_story.main() returned non-zero exit code {ret}"

    prd = json.loads(prd_path.read_text(encoding="utf-8"))
    parent = next((s for s in prd["userStories"] if s["id"] == "US-100"), None)

    assert parent is not None, "Parent story US-100 not found in updated prd.json"
    assert parent.get("_decomposed") is True, (
        f"Parent US-100 must have _decomposed=True, got: {parent.get('_decomposed')}"
    )
    assert "_decomposedInto" in parent, "Parent US-100 must have _decomposedInto field listing child IDs"

    child_ids = parent["_decomposedInto"]
    assert len(child_ids) == 4, f"Expected 4 entries in _decomposedInto, got {len(child_ids)}: {child_ids}"

    # Each listed child must actually exist in prd.json
    all_ids = {s["id"] for s in prd["userStories"]}
    for cid in child_ids:
        assert cid in all_ids, f"Child ID {cid} listed in _decomposedInto but not found in prd.json"


def test_decompose_children_state(decompose_setup: Path) -> None:
    """Verify all 4 decomposed sub-stories have correct initial state in prd.json.

    Each sub-story must have:
      - _decomposedFrom = "US-100"  (back-pointer to parent)
      - passes = False              (not yet implemented)
      - estimatedComplexity = "small"  (decompose enforces smaller scope)
    """
    prd_path = decompose_setup
    ret = _run_decompose(prd_path)
    assert ret == 0, f"decompose_story.main() returned non-zero exit code {ret}"

    prd = json.loads(prd_path.read_text(encoding="utf-8"))
    sub_stories = [s for s in prd["userStories"] if s.get("_decomposedFrom") == "US-100"]

    assert len(sub_stories) == 4, f"Expected 4 sub-stories with _decomposedFrom='US-100', got {len(sub_stories)}"

    for story in sub_stories:
        sid = story["id"]

        assert story["_decomposedFrom"] == "US-100", (
            f"{sid}: _decomposedFrom should be 'US-100', got {story['_decomposedFrom']!r}"
        )
        assert story["passes"] is False, f"{sid}: passes should be False (story not yet implemented)"
        assert story["estimatedComplexity"] == "small", (
            f"{sid}: estimatedComplexity should be 'small', got {story['estimatedComplexity']!r}"
        )


# ---------------------------------------------------------------------------
# Plan Gate Tests (US-1153)
# ---------------------------------------------------------------------------


def test_plan_gate_triggers_decompose() -> None:
    """Verify that a plan exceeding SPIRAL_PLAN_FILE_LIMIT triggers decomposition.

    When validate_plan() receives a plan with 10 files total and
    SPIRAL_PLAN_FILE_LIMIT=8, it should reject the plan.
    """
    import subprocess

    # Oversized plan: 10 files total (exceeds limit of 8)
    # Using a simpler inline approach with heredoc
    result = subprocess.run(
        [
            "bash",
            "-c",
            r"""
            . lib/impl/decompose.sh

            # Inline plan JSON with 10 files
            plan_json='{"files_to_create":["new1.py","new2.py"],"files_to_modify":["lib/a.py","lib/b.py","lib/c.py","lib/d.py","lib/e.py","lib/f.py","lib/g.py","lib/h.py"],"functions_to_add":["validate_plan","decompose"],"estimated_loc":150}'

            export SPIRAL_PLAN_FILE_LIMIT=8
            export SPIRAL_HOME=.
            validate_plan "$plan_json" 'US-999'
            """,
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    # Plan should be rejected (non-zero exit code)
    assert result.returncode == 1, (
        f"Expected non-zero exit code for oversized plan, got {result.returncode}. "
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check that rejection message is in output
    combined_output = (result.stdout + result.stderr).lower()
    assert "plan_rejected" in combined_output or "touch" in combined_output, (
        f"Expected plan rejection message, got:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_plan_within_limit_proceeds() -> None:
    """Verify that a plan within SPIRAL_PLAN_FILE_LIMIT passes validation.

    When validate_plan() receives a plan with 5 total files and SPIRAL_PLAN_FILE_LIMIT=8,
    it should accept the plan and return 0.
    """
    import subprocess

    # Compliant plan: 5 files total (within limit of 8)
    result = subprocess.run(
        [
            "bash",
            "-c",
            r"""
            . lib/impl/decompose.sh

            # Inline plan JSON with 5 files
            plan_json='{"files_to_create":["new1.py","new2.py"],"files_to_modify":["lib/a.py","lib/b.py","lib/c.py"],"functions_to_add":["validate_plan"],"estimated_loc":80}'

            export SPIRAL_PLAN_FILE_LIMIT=8
            export SPIRAL_HOME=.
            validate_plan "$plan_json" 'US-888'
            """,
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    # Plan should be accepted (zero exit code)
    assert result.returncode == 0, (
        f"Expected zero exit code for compliant plan, got {result.returncode}. "
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check that acceptance message is in output
    combined_output = (result.stdout + result.stderr).lower()
    assert "accepted" in combined_output, (
        f"Expected plan acceptance message, got:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
