"""Tests for lib/merge_conflict_detector.py

Covers:
- build_conflict_matrix: detects shared files across stories
- write_conflict_report: writes .spiral/_merge_conflicts.json with correct schema
- run(): returns exit code 1 when _merge_conflicts.json is non-empty
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from merge_conflict_detector import (
    build_conflict_matrix,
    extract_story_files,
    run,
    write_conflict_report,
)


def _make_story(story_id: str, notes: list[str]) -> dict:
    return {
        "id": story_id,
        "title": f"Story {story_id}",
        "description": "desc",
        "priority": "medium",
        "acceptanceCriteria": ["AC1"],
        "passes": False,
        "dependencies": [],
        "technicalNotes": notes,
    }


US_456 = _make_story(
    "US-456",
    [
        "File to edit: lib/shared.py — add helper function",
        "File to edit: lib/utils.py — minor update",
    ],
)

US_457 = _make_story(
    "US-457",
    [
        "File to edit: lib/shared.py — refactor class",
        "File to edit: lib/other.py — new module",
    ],
)

US_458 = _make_story(
    "US-458",
    [
        "File to edit: lib/only_mine.py — isolated change",
    ],
)


# ---------------------------------------------------------------------------
# test_build_conflict_matrix
# ---------------------------------------------------------------------------


@pytest.mark.us_584
def test_build_conflict_matrix() -> None:
    """build_conflict_matrix shows lib/shared.py owned by both US-456 and US-457."""
    matrix = build_conflict_matrix([US_456, US_457])

    assert "lib/shared.py" in matrix, "lib/shared.py should appear in matrix"
    owners = matrix["lib/shared.py"]
    assert "US-456" in owners, "US-456 should claim lib/shared.py"
    assert "US-457" in owners, "US-457 should claim lib/shared.py"


@pytest.mark.us_584
def test_build_conflict_matrix_no_conflict() -> None:
    """Stories with no shared files produce a matrix with no multi-owner entries."""
    matrix = build_conflict_matrix([US_456, US_458])
    conflicts = {f: owners for f, owners in matrix.items() if len(owners) >= 2}
    assert not conflicts, "No conflict expected between US-456 and US-458"


@pytest.mark.us_584
def test_extract_story_files_parses_technical_notes() -> None:
    files = extract_story_files(US_456)
    assert "lib/shared.py" in files
    assert "lib/utils.py" in files


@pytest.mark.us_584
def test_extract_story_files_falls_back_to_filesTouch() -> None:
    story = {
        "id": "US-999",
        "title": "no notes",
        "filesTouch": ["src/foo.ts", "src/bar.ts"],
    }
    files = extract_story_files(story)
    assert "src/foo.ts" in files
    assert "src/bar.ts" in files


# ---------------------------------------------------------------------------
# test_conflict_report_written
# ---------------------------------------------------------------------------


@pytest.mark.us_584
def test_conflict_report_written(tmp_path: pytest.TempPathFactory) -> None:
    """Conflict report written to .spiral/_merge_conflicts.json with correct schema."""
    out = str(tmp_path / "_merge_conflicts.json")
    matrix = build_conflict_matrix([US_456, US_457])
    write_conflict_report(matrix, out)

    assert os.path.isfile(out), "Report file should be created"

    with open(out, encoding="utf-8") as fh:
        report = json.load(fh)

    assert isinstance(report, list), "Report should be a JSON array"
    assert len(report) >= 1, "At least one conflict entry expected"

    # Find US-456 entry
    us456_entry = next((r for r in report if r["story_id"] == "US-456"), None)
    assert us456_entry is not None, "US-456 should appear in conflict report"

    # Schema check
    assert "story_id" in us456_entry
    assert "conflicting_story_ids" in us456_entry
    assert "conflicting_files" in us456_entry

    assert "US-457" in us456_entry["conflicting_story_ids"]
    assert "lib/shared.py" in us456_entry["conflicting_files"]


@pytest.mark.us_584
def test_conflict_report_written_empty_when_no_conflicts(tmp_path: pytest.TempPathFactory) -> None:
    """No-conflict scenarios produce an empty list in the report."""
    out = str(tmp_path / "_merge_conflicts.json")
    matrix = build_conflict_matrix([US_456, US_458])
    write_conflict_report(matrix, out)

    with open(out, encoding="utf-8") as fh:
        report = json.load(fh)

    assert report == [], "Report should be empty list when no conflicts"


# ---------------------------------------------------------------------------
# test_phase_m_exits_1_on_conflict
# ---------------------------------------------------------------------------


@pytest.mark.us_584
def test_phase_m_exits_1_on_conflict(tmp_path: pytest.TempPathFactory) -> None:
    """run() returns exit code 1 when _merge_conflicts.json is non-empty."""
    out = str(tmp_path / "_merge_conflicts.json")
    exit_code = run([US_456, US_457], out_path=out)
    assert exit_code == 1, "Should return 1 when conflicts exist"


@pytest.mark.us_584
def test_phase_m_exits_0_on_no_conflict(tmp_path: pytest.TempPathFactory) -> None:
    """run() returns exit code 0 when there are no file conflicts."""
    out = str(tmp_path / "_merge_conflicts.json")
    exit_code = run([US_456, US_458], out_path=out)
    assert exit_code == 0, "Should return 0 when no conflicts"
