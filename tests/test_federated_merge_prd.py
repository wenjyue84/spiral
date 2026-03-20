"""test_federated_merge_prd.py — Tests for federated-merge-prd CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from lib.federated_merge_prd import merge_prds, run_federated_merge


def _write_prd(path: Path, stories: list[dict[str, object]]) -> None:
    """Helper to write a prd.json file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"userStories": stories}, f)


def test_merge_three_projects(tmp_path: Path) -> None:
    """AC3: Merge auth(US-1,US-2), api(US-3), payments(US-4) and verify sub_project + priority."""
    _write_prd(
        tmp_path / "auth" / "prd.json",
        [
            {"id": "US-1", "title": "Auth Login", "priority": "high", "passes": False},
            {"id": "US-2", "title": "Auth Signup", "priority": "medium", "passes": False},
        ],
    )
    _write_prd(
        tmp_path / "api" / "prd.json",
        [{"id": "US-3", "title": "API Endpoints", "priority": "high", "passes": True}],
    )
    _write_prd(
        tmp_path / "payments" / "prd.json",
        [{"id": "US-4", "title": "Payment Flow", "priority": "low", "passes": False}],
    )

    project_dirs = {
        "auth": tmp_path / "auth",
        "api": tmp_path / "api",
        "payments": tmp_path / "payments",
    }
    merged, errors = merge_prds(project_dirs)

    assert errors == []
    stories = merged["userStories"]
    assert len(stories) == 4

    by_id = {s["id"]: s for s in stories}
    assert by_id["US-1"]["sub_project"] == "auth"
    assert by_id["US-2"]["sub_project"] == "auth"
    assert by_id["US-3"]["sub_project"] == "api"
    assert by_id["US-4"]["sub_project"] == "payments"

    # Priority preserved
    assert by_id["US-1"]["priority"] == "high"
    assert by_id["US-2"]["priority"] == "medium"
    assert by_id["US-3"]["priority"] == "high"
    assert by_id["US-4"]["priority"] == "low"


def test_duplicate_story_ids_detected(tmp_path: Path) -> None:
    """AC2: Duplicate IDs across projects returns errors."""
    _write_prd(
        tmp_path / "auth" / "prd.json",
        [{"id": "US-1", "title": "Auth Login", "passes": False}],
    )
    _write_prd(
        tmp_path / "api" / "prd.json",
        [{"id": "US-1", "title": "API Login duplicate", "passes": False}],
    )

    project_dirs = {
        "auth": tmp_path / "auth",
        "api": tmp_path / "api",
    }
    merged, errors = merge_prds(project_dirs)

    assert len(errors) == 1
    assert "US-1" in errors[0]
    assert "auth" in errors[0]
    assert "api" in errors[0]
    assert merged == {}


def test_run_federated_merge_writes_output(tmp_path: Path) -> None:
    """AC1: CLI merges 3 PRDs and writes merged JSON."""
    _write_prd(
        tmp_path / "auth" / "prd.json",
        [
            {"id": "US-1", "title": "Auth Login", "priority": "high", "passes": False},
            {"id": "US-2", "title": "Auth Signup", "priority": "medium", "passes": False},
        ],
    )
    _write_prd(
        tmp_path / "api" / "prd.json",
        [{"id": "US-3", "title": "API Endpoints", "priority": "high", "passes": True}],
    )
    _write_prd(
        tmp_path / "payments" / "prd.json",
        [{"id": "US-4", "title": "Payment Flow", "priority": "low", "passes": False}],
    )

    output = tmp_path / "merged-prd.json"
    exit_code = run_federated_merge(
        ["auth", "api", "payments"], output, base_dir=tmp_path
    )

    assert exit_code == 0
    assert output.exists()

    with open(output, encoding="utf-8") as f:
        data = json.load(f)

    stories = data["userStories"]
    assert len(stories) == 4
    assert all("sub_project" in s for s in stories)


def test_run_federated_merge_duplicate_exits_1(tmp_path: Path) -> None:
    """AC2: Exit code 1 on duplicate IDs, no output file written."""
    _write_prd(
        tmp_path / "auth" / "prd.json",
        [{"id": "US-1", "title": "Auth", "passes": False}],
    )
    _write_prd(
        tmp_path / "api" / "prd.json",
        [{"id": "US-1", "title": "API duplicate", "passes": False}],
    )

    output = tmp_path / "merged.json"
    exit_code = run_federated_merge(["auth", "api"], output, base_dir=tmp_path)

    assert exit_code == 1
    assert not output.exists()


def test_run_federated_merge_missing_dir_exits_1(tmp_path: Path) -> None:
    """Exit code 1 when a sub-project directory doesn't exist."""
    exit_code = run_federated_merge(
        ["nonexistent"], tmp_path / "out.json", base_dir=tmp_path
    )
    assert exit_code == 1


def test_run_federated_merge_missing_prd_exits_1(tmp_path: Path) -> None:
    """Exit code 1 when a sub-project directory exists but has no prd.json."""
    (tmp_path / "empty_project").mkdir()
    exit_code = run_federated_merge(
        ["empty_project"], tmp_path / "out.json", base_dir=tmp_path
    )
    assert exit_code == 1
