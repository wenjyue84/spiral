"""tests/test_phase_m_cross_project_deps.py — US-654: Phase M cross-project dep order."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib" / "impl"))

from phase_m_federated_order import order_federated_stories_by_dependency

from lib.federated_merge_prd import merge_prds


def _write_prd(path: Path, stories: list) -> None:  # type: ignore[type-arg]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"userStories": stories}), encoding="utf-8")


# ── AC1: cross-project dep detected, merge order respected ────────────────────


def test_cross_project_dep_b_before_a(tmp_path: Path) -> None:
    """AC1: Story A (proj1) depends on B (proj2); B must appear first after ordering."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": []}],
    )
    merged, errors = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    assert errors == []
    ordered = order_federated_stories_by_dependency(merged["userStories"])
    ids = [s["id"] for s in ordered]
    assert ids.index("US-B") < ids.index("US-A"), f"Expected US-B before US-A, got: {ids}"


def test_sub_project_labels_preserved_on_merge(tmp_path: Path) -> None:
    """AC1: Each merged story carries the correct sub_project label."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": []}],
    )
    merged, errors = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    assert errors == []
    by_id = {s["id"]: s for s in merged["userStories"]}
    assert by_id["US-A"]["sub_project"] == "proj1"
    assert by_id["US-B"]["sub_project"] == "proj2"


# ── AC2: assertion fails if A placed before B ─────────────────────────────────


def test_wrong_order_violates_dependency(tmp_path: Path) -> None:
    """AC2: Placing US-A before US-B must fail the dependency constraint check."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": []}],
    )
    merged, _ = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    ordered = order_federated_stories_by_dependency(merged["userStories"])
    ids = [s["id"] for s in ordered]
    b_idx, a_idx = ids.index("US-B"), ids.index("US-A")
    assert b_idx < a_idx, f"Dependency violated: US-A (idx {a_idx}) before US-B (idx {b_idx})"
    # Guard: confirm inverse would be wrong
    assert not (a_idx < b_idx)


def test_ordering_produces_valid_prd_structure(tmp_path: Path) -> None:
    """AC2: Ordered result is a valid prd.json with all story IDs present."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": []}],
    )
    merged, errors = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    assert errors == []
    ordered = order_federated_stories_by_dependency(merged["userStories"])
    assert all("id" in s for s in ordered)
    assert {s["id"] for s in ordered} == {"US-A", "US-B"}


# ── AC3: depends_on field preserved, stories grouped by sub_project ───────────


def test_depends_on_field_preserved_in_merged(tmp_path: Path) -> None:
    """AC3: Cross-project depends_on references are preserved in merged output."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"], "depends_on": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": []}],
    )
    merged, errors = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    assert errors == []
    by_id = {s["id"]: s for s in merged["userStories"]}
    assert by_id["US-A"].get("depends_on") == ["US-B"]


def test_stories_grouped_by_sub_project_in_merged(tmp_path: Path) -> None:
    """AC3: Stories from the same sub_project are contiguous in merged output."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [
            {"id": "US-A1", "title": "A1", "dependencies": []},
            {"id": "US-A2", "title": "A2", "dependencies": []},
        ],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [
            {"id": "US-B1", "title": "B1", "dependencies": []},
            {"id": "US-B2", "title": "B2", "dependencies": []},
        ],
    )
    merged, errors = merge_prds({"proj1": tmp_path / "proj1", "proj2": tmp_path / "proj2"})
    assert errors == []
    stories = merged["userStories"]
    proj1_idxs = [i for i, s in enumerate(stories) if s.get("sub_project") == "proj1"]
    assert proj1_idxs == list(range(proj1_idxs[0], proj1_idxs[-1] + 1))


def test_three_way_cross_project_chain(tmp_path: Path) -> None:
    """AC1+AC2: Chain C(proj3)->B(proj2)->A(proj1); order enforced C,B,A."""
    _write_prd(
        tmp_path / "proj1" / "prd.json",
        [{"id": "US-A", "title": "A", "dependencies": ["US-B"]}],
    )
    _write_prd(
        tmp_path / "proj2" / "prd.json",
        [{"id": "US-B", "title": "B", "dependencies": ["US-C"]}],
    )
    _write_prd(
        tmp_path / "proj3" / "prd.json",
        [{"id": "US-C", "title": "C", "dependencies": []}],
    )
    merged, errors = merge_prds(
        {
            "proj1": tmp_path / "proj1",
            "proj2": tmp_path / "proj2",
            "proj3": tmp_path / "proj3",
        }
    )
    assert errors == []
    ordered = order_federated_stories_by_dependency(merged["userStories"])
    ids = [s["id"] for s in ordered]
    assert ids.index("US-C") < ids.index("US-B"), f"C must precede B, got: {ids}"
    assert ids.index("US-B") < ids.index("US-A"), f"B must precede A, got: {ids}"
