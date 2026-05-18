#!/usr/bin/env python3
"""
tests/test_story_renamer.py — Tests for story_renamer module
"""

import json
from pathlib import Path

import pytest

from lib.story_renamer import (
    rename_story,
    update_dependencies,
    update_results_tsv,
    validate_rename,
)


@pytest.fixture
def sample_prd() -> dict[str, object]:
    """Sample PRD with multiple stories and dependencies."""
    return {
        "productName": "Test Product",
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "US-001",
                "title": "Story 1",
                "description": "First story",
                "acceptanceCriteria": ["AC 1"],
                "dependencies": [],
                "passes": False,
            },
            {
                "id": "US-002",
                "title": "Story 2",
                "description": "Second story",
                "acceptanceCriteria": ["AC 2"],
                "dependencies": ["US-001"],
                "passes": False,
            },
            {
                "id": "US-003",
                "title": "Story 3",
                "description": "Third story",
                "acceptanceCriteria": ["AC 3"],
                "dependencies": ["US-001", "US-002"],
                "passes": False,
            },
        ],
    }


@pytest.fixture
def sample_results_tsv() -> str:
    """Sample results.tsv with multiple story_id entries."""
    return (
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\n"
        "2026-03-20T04:00:40Z\t3\t2\tUS-001\tStory 1\tpass\n"
        "2026-03-20T04:47:20Z\t5\t1\tUS-002\tStory 2\treject\n"
        "2026-03-21T06:09:14Z\t5\t2\tUS-001\tStory 1\tpass\n"
    )


def test_validate_rename_success(tmp_path: Path) -> None:
    """Validate should return True when rename is safe."""
    prd_path = tmp_path / "prd.json"
    prd = {
        "userStories": [
            {"id": "US-001", "dependencies": []},
        ]
    }
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f)

    is_valid, msg = validate_rename("US-001", "US-999", str(prd_path))
    assert is_valid and msg == ""


def test_validate_rename_new_id_exists(tmp_path: Path) -> None:
    """Validate should reject if new_id already exists."""
    prd_path = tmp_path / "prd.json"
    prd = {
        "userStories": [
            {"id": "US-001", "dependencies": []},
            {"id": "US-999", "dependencies": []},
        ]
    }
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f)

    is_valid, msg = validate_rename("US-001", "US-999", str(prd_path))
    assert not is_valid and "already exists" in msg


def test_validate_rename_old_id_not_found(tmp_path: Path) -> None:
    """Validate should reject if old_id doesn't exist."""
    prd_path = tmp_path / "prd.json"
    prd = {
        "userStories": [
            {"id": "US-001", "dependencies": []},
        ]
    }
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f)

    is_valid, msg = validate_rename("US-999", "US-000", str(prd_path))
    assert not is_valid and "not found" in msg


def test_validate_rename_missing_file(tmp_path: Path) -> None:
    """Validate should reject if PRD file doesn't exist."""
    prd_path = tmp_path / "nonexistent.json"
    is_valid, msg = validate_rename("US-001", "US-999", str(prd_path))
    assert not is_valid and "not found" in msg


def test_update_dependencies() -> None:
    """Update dependencies should replace all old_id refs with new_id."""
    stories = [
        {
            "id": "US-001",
            "dependencies": [],
        },
        {
            "id": "US-002",
            "dependencies": ["US-001"],
        },
        {
            "id": "US-003",
            "dependencies": ["US-001", "US-002", "US-001"],
        },
    ]

    update_dependencies(stories, "US-001", "US-999")

    assert stories[0]["dependencies"] == []
    assert stories[1]["dependencies"] == ["US-999"]
    assert stories[2]["dependencies"] == ["US-999", "US-002", "US-999"]


def test_update_dependencies_no_matches() -> None:
    """Update dependencies with no matches should not change anything."""
    stories = [
        {
            "id": "US-001",
            "dependencies": ["US-002"],
        },
    ]
    original = json.loads(json.dumps(stories))

    update_dependencies(stories, "US-999", "US-000")

    assert stories == original


def test_update_results_tsv_replaces_old_id(tmp_path: Path, sample_results_tsv: str) -> None:
    """Update results.tsv should replace story_id column values."""
    tsv_path = tmp_path / "results.tsv"
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write(sample_results_tsv)

    update_results_tsv(str(tsv_path), "US-001", "US-999")

    with open(tsv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Check header is unchanged
    assert "story_id" in lines[0]

    # Check US-001 was replaced with US-999
    assert lines[1].startswith("2026-03-20T04:00:40Z\t3\t2\tUS-999")
    assert lines[3].startswith("2026-03-21T06:09:14Z\t5\t2\tUS-999")

    # Check US-002 was not changed
    assert lines[2].startswith("2026-03-20T04:47:20Z\t5\t1\tUS-002")


def test_update_results_tsv_missing_file(tmp_path: Path) -> None:
    """Update results.tsv should handle missing file gracefully."""
    tsv_path = tmp_path / "nonexistent.tsv"
    # Should not raise an exception
    update_results_tsv(str(tsv_path), "US-001", "US-999")


def test_update_results_tsv_no_story_id_column(tmp_path: Path) -> None:
    """Update results.tsv should handle files with no story_id column."""
    tsv_path = tmp_path / "results.tsv"
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("timestamp\tother_field\n2026-03-20T04:00:40Z\tvalue\n")

    update_results_tsv(str(tsv_path), "US-001", "US-999")

    # File should be unchanged
    with open(tsv_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "US-001" not in content
    assert "timestamp" in content


def test_rename_preserves_history(tmp_path: Path, sample_prd: dict[str, object], sample_results_tsv: str) -> None:
    """Rename should preserve execution telemetry in results.tsv."""
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(sample_prd, f)

    with open(results_path, "w", encoding="utf-8") as f:
        f.write(sample_results_tsv)

    rename_story("US-001", "US-999", str(prd_path), str(results_path))

    # Check prd.json
    with open(prd_path, "r", encoding="utf-8") as f:
        updated_prd = json.load(f)

    stories = updated_prd["userStories"]
    assert stories[0]["id"] == "US-999"
    assert stories[1]["dependencies"] == ["US-999"]
    assert stories[2]["dependencies"] == ["US-999", "US-002"]

    # Check results.tsv
    with open(results_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert lines[1].split("\t")[3] == "US-999"
    assert lines[3].split("\t")[3] == "US-999"


def test_rename_aborts_on_collision(tmp_path: Path, sample_prd: dict[str, object]) -> None:
    """Rename should abort if new_id already exists."""
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(sample_prd, f)

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("timestamp\tstory_id\n")

    with pytest.raises(ValueError, match="already exists"):
        rename_story("US-001", "US-002", str(prd_path), str(results_path))


def test_rename_aborts_on_missing_old_id(tmp_path: Path, sample_prd: dict[str, object]) -> None:
    """Rename should abort if old_id doesn't exist."""
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(sample_prd, f)

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("timestamp\tstory_id\n")

    with pytest.raises(ValueError, match="not found"):
        rename_story("US-999", "US-000", str(prd_path), str(results_path))


def test_rename_update_multiple_deps(
    tmp_path: Path,
) -> None:
    """Rename should update all dependency refs across multiple stories."""
    prd = {
        "userStories": [
            {"id": "US-A", "dependencies": []},
            {"id": "US-B", "dependencies": ["US-A"]},
            {"id": "US-C", "dependencies": ["US-A", "US-B"]},
            {"id": "US-D", "dependencies": ["US-A", "US-A"]},
        ]
    }
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f)

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("timestamp\tstory_id\n")

    rename_story("US-A", "US-X", str(prd_path), str(results_path))

    with open(prd_path, "r", encoding="utf-8") as f:
        updated = json.load(f)

    stories = updated["userStories"]
    assert stories[0]["id"] == "US-X"
    assert stories[1]["dependencies"] == ["US-X"]
    assert stories[2]["dependencies"] == ["US-X", "US-B"]
    assert stories[3]["dependencies"] == ["US-X", "US-X"]


def test_rename_atomic_write_safety(tmp_path: Path) -> None:
    """Rename should use atomic write to avoid partial corruption."""
    prd = {"userStories": [{"id": "US-001", "dependencies": []}]}
    prd_path = tmp_path / "prd.json"
    results_path = tmp_path / "results.tsv"

    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd, f)

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("timestamp\tstory_id\n")

    rename_story("US-001", "US-999", str(prd_path), str(results_path))

    # Verify file was written (not left as .tmp)
    assert prd_path.exists()
    with open(prd_path, "r", encoding="utf-8") as f:
        updated = json.load(f)
    assert updated["userStories"][0]["id"] == "US-999"
