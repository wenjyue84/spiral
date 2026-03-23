"""tests/test_merge_dry_run.py

Tests for lib/merge_dry_run.py file-collision and dependency-order detection.

Story: US-1045
"""

import json
import pytest
from lib.merge_dry_run import run_dry_run


@pytest.fixture
def temp_json_files(tmp_path):
    """Create temporary directories and helper to write JSON files."""

    def write_validated(stories_data):
        validated_path = tmp_path / "_validated_stories.json"
        with open(validated_path, "w", encoding="utf-8") as f:
            json.dump({"stories": stories_data}, f)
        return str(validated_path)

    def write_prd(stories_data):
        prd_path = tmp_path / "prd.json"
        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump({"userStories": stories_data}, f)
        return str(prd_path)

    return {
        "tmp_path": tmp_path,
        "write_validated": write_validated,
        "write_prd": write_prd,
    }


def test_return_structure(temp_json_files):
    """Test that run_dry_run returns correct dict structure."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        write_prd([])
        validated_path = write_validated([])

        result = run_dry_run(validated_path)
        assert set(result.keys()) == {"conflict_detected", "file_collisions", "ordering_violations"}
        assert isinstance(result["conflict_detected"], bool)
        assert isinstance(result["file_collisions"], list)
        assert isinstance(result["ordering_violations"], list)
    finally:
        os.chdir(old_cwd)


def test_no_collisions_no_violations(temp_json_files):
    """Test that no collisions/violations returns conflict_detected=false."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))

        prd_stories = [
            {"id": "US-100", "title": "Story 1"},
            {"id": "US-101", "title": "Story 2"},
        ]
        write_prd(prd_stories)

        validated_stories = [
            {
                "id": "US-100",
                "title": "Story 1",
                "technicalNotes": ["File to edit: lib/file1.py"],
                "dependencies": [],
            },
            {
                "id": "US-101",
                "title": "Story 2",
                "technicalNotes": ["File to edit: lib/file2.py"],
                "dependencies": ["US-100"],
            },
        ]
        validated_path = write_validated(validated_stories)

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is False
        assert result["file_collisions"] == []
        assert result["ordering_violations"] == []
    finally:
        os.chdir(old_cwd)


def test_file_collision_detection(temp_json_files):
    """Test that two stories touching same file are detected."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        write_prd([])

        validated_stories = [
            {
                "id": "US-100",
                "title": "Story 1",
                "technicalNotes": ["File to edit: lib/spiral_helpers.sh"],
                "dependencies": [],
            },
            {
                "id": "US-101",
                "title": "Story 2",
                "technicalNotes": ["File to edit: lib/spiral_helpers.sh"],
                "dependencies": [],
            },
        ]
        validated_path = write_validated(validated_stories)

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is True
        assert "lib/spiral_helpers.sh" in result["file_collisions"]
        assert result["ordering_violations"] == []
    finally:
        os.chdir(old_cwd)


def test_ordering_violation_detection(temp_json_files):
    """Test that missing dependencies are detected."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))

        prd_stories = [{"id": "US-100", "title": "Story 1"}]
        write_prd(prd_stories)

        validated_stories = [
            {
                "id": "US-200",
                "title": "Story 2",
                "technicalNotes": [],
                "dependencies": ["US-100", "US-300"],
            }
        ]
        validated_path = write_validated(validated_stories)

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is True
        assert result["file_collisions"] == []
        assert "US-300" in result["ordering_violations"]
    finally:
        os.chdir(old_cwd)


def test_multiple_collisions_and_violations(temp_json_files):
    """Test detection of multiple collisions and violations together."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))

        prd_stories = [{"id": "US-100", "title": "Story 1"}]
        write_prd(prd_stories)

        validated_stories = [
            {
                "id": "US-100",
                "title": "Story 1",
                "technicalNotes": [
                    "File to edit: lib/file_a.py",
                    "File to create: lib/file_b.py",
                ],
                "dependencies": [],
            },
            {
                "id": "US-101",
                "title": "Story 2",
                "technicalNotes": [
                    "File to edit: lib/file_a.py",
                    "File to edit: lib/file_c.py",
                ],
                "dependencies": ["US-999"],
            },
        ]
        validated_path = write_validated(validated_stories)

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is True
        assert "lib/file_a.py" in result["file_collisions"]
        assert "US-999" in result["ordering_violations"]
    finally:
        os.chdir(old_cwd)


def test_no_technical_notes(temp_json_files):
    """Test handling of stories with missing technicalNotes."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        write_prd([])

        validated_stories = [
            {
                "id": "US-100",
                "title": "Story 1",
                "dependencies": [],
            }
        ]
        validated_path = write_validated(validated_stories)

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is False
        assert result["file_collisions"] == []
    finally:
        os.chdir(old_cwd)


def test_empty_validated_stories(temp_json_files):
    """Test handling of empty validated stories list."""
    tmp_path = temp_json_files["tmp_path"]
    write_validated = temp_json_files["write_validated"]
    write_prd = temp_json_files["write_prd"]

    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        write_prd([])
        validated_path = write_validated([])

        result = run_dry_run(validated_path)
        assert result["conflict_detected"] is False
        assert result["file_collisions"] == []
        assert result["ordering_violations"] == []
    finally:
        os.chdir(old_cwd)
