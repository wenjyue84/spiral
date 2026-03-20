"""tests/test_phase_m_federated_order.py — Integration tests for US-617.

Tests order_federated_stories_by_dependency() and validate-federated-order CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib" / "impl"))

from phase_m_federated_order import order_federated_stories_by_dependency  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_story(sid: str, description: str = "", dependencies: list[str] | None = None) -> dict:
    return {
        "id": sid,
        "title": f"Story {sid}",
        "description": description,
        "dependencies": dependencies or [],
    }


# ── Unit tests ────────────────────────────────────────────────────────────────


def test_empty_list_returns_empty() -> None:
    assert order_federated_stories_by_dependency([]) == []


def test_single_story_no_deps() -> None:
    stories = [_make_story("US-A1")]
    result = order_federated_stories_by_dependency(stories)
    assert len(result) == 1
    assert result[0]["id"] == "US-A1"


def test_independent_stories_returned() -> None:
    stories = [_make_story("US-A1"), _make_story("US-B1"), _make_story("US-C1")]
    result = order_federated_stories_by_dependency(stories)
    assert {s["id"] for s in result} == {"US-A1", "US-B1", "US-C1"}


def test_merge_order_respects_dependencies() -> None:
    """AC2: US-A1 depends on US-B1; US-B1 must appear before US-A1."""
    us_a1 = _make_story("US-A1", description="This story depends on US-B1 being complete first.")
    us_b1 = _make_story("US-B1")
    stories = [us_a1, us_b1]

    result = order_federated_stories_by_dependency(stories)
    ids = [s["id"] for s in result]

    assert ids.index("US-B1") < ids.index("US-A1"), (
        f"US-B1 should appear before US-A1, got order: {ids}"
    )


def test_explicit_dependencies_field_respected() -> None:
    """Dependencies listed in the 'dependencies' field are respected."""
    us_a1 = _make_story("US-A1", dependencies=["US-B1"])
    us_b1 = _make_story("US-B1")
    stories = [us_a1, us_b1]

    result = order_federated_stories_by_dependency(stories)
    ids = [s["id"] for s in result]
    assert ids.index("US-B1") < ids.index("US-A1")


def test_chain_ordering() -> None:
    """A -> B -> C: C must come first, then B, then A."""
    us_a = _make_story("US-A1", description="Requires US-B1 to be done.")
    us_b = _make_story("US-B1", description="Requires US-C1 to be done.")
    us_c = _make_story("US-C1")
    stories = [us_a, us_b, us_c]

    result = order_federated_stories_by_dependency(stories)
    ids = [s["id"] for s in result]
    assert ids.index("US-C1") < ids.index("US-B1")
    assert ids.index("US-B1") < ids.index("US-A1")


def test_cycle_detection_raises_error() -> None:
    """AC2: Cycle detection raises ValueError with correct message format."""
    us_a1 = _make_story("US-A1", description="Depends on US-B1.")
    us_b1 = _make_story("US-B1", description="Depends on US-A1.")
    stories = [us_a1, us_b1]

    with pytest.raises(ValueError, match="circular dependency"):
        order_federated_stories_by_dependency(stories)


def test_cycle_error_message_format() -> None:
    """Cycle error message uses arrow notation as specified in AC2."""
    us_a1 = _make_story("US-A1", description="This needs US-B1.")
    us_b1 = _make_story("US-B1", description="This requires US-A1.")
    stories = [us_a1, us_b1]

    with pytest.raises(ValueError) as exc_info:
        order_federated_stories_by_dependency(stories)

    msg = str(exc_info.value)
    assert "circular dependency" in msg
    # Message should contain story IDs
    assert "US-A1" in msg or "US-B1" in msg


def test_unknown_dependency_references_ignored() -> None:
    """References to unknown story IDs in descriptions are ignored safely."""
    us_a1 = _make_story("US-A1", description="Depends on US-UNKNOWN which is external.")
    stories = [us_a1]
    result = order_federated_stories_by_dependency(stories)
    assert len(result) == 1


def test_stories_without_ids_handled() -> None:
    """Stories without 'id' field are preserved in output."""
    stories = [
        {"title": "No ID story", "description": ""},
        _make_story("US-A1"),
    ]
    result = order_federated_stories_by_dependency(stories)
    assert len(result) == 2


# ── Integration test (AC2) ────────────────────────────────────────────────────


def test_ac2_integration_merge_order_and_cycle() -> None:
    """AC2 integration: dependency order correct, cycle raises error with specified format."""
    # Part 1: US-A1 depends on US-B1; US-B1 must appear first
    stories = [
        _make_story("US-A1", description="depends on US-B1"),
        _make_story("US-B1"),
    ]
    result = order_federated_stories_by_dependency(stories)
    ids = [s["id"] for s in result]
    assert ids.index("US-B1") < ids.index("US-A1")

    # Part 2: cycle raises ValueError matching spec format "circular dependency: US-A1→US-B1→US-A1"
    cyclic_stories = [
        _make_story("US-A1", description="depends on US-B1"),
        _make_story("US-B1", description="depends on US-A1"),
    ]
    with pytest.raises(ValueError, match=r"circular dependency: US-\w+→US-\w+"):
        order_federated_stories_by_dependency(cyclic_stories)


# ── CLI integration tests (AC3) ──────────────────────────────────────────────


def test_cli_validate_federated_order_json(tmp_path: Path) -> None:
    """CLI: validate-federated-order outputs JSON with merge_order and violations."""
    prd = {
        "userStories": [
            {"id": "US-A1", "title": "A", "description": "depends on US-B1", "dependencies": []},
            {"id": "US-B1", "title": "B", "description": "", "dependencies": []},
        ]
    }
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "main.py"),
            "validate-federated-order",
            str(prd_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    data = json.loads(result.stdout)
    assert "merge_order" in data
    assert "violations" in data
    order_ids = [s["id"] for s in data["merge_order"]]
    assert order_ids.index("US-B1") < order_ids.index("US-A1")
    assert data["violations"] == []


def test_cli_validate_federated_order_reports_cycle(tmp_path: Path) -> None:
    """CLI: validate-federated-order exits non-zero and reports cycle violations."""
    prd = {
        "userStories": [
            {"id": "US-A1", "title": "A", "description": "depends on US-B1", "dependencies": []},
            {"id": "US-B1", "title": "B", "description": "depends on US-A1", "dependencies": []},
        ]
    }
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(prd), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent.parent / "main.py"),
            "validate-federated-order",
            str(prd_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, "CLI should exit non-zero for cycle"
    data = json.loads(result.stdout)
    assert len(data["violations"]) > 0
    assert "circular" in data["violations"][0].lower()
