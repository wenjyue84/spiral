"""Tests for lib/prd/hot_file_registry.py — hot file tracking for conflict prevention."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.prd.hot_file_registry import (
    apply_decay,
    get_hot_files,
    load_registry,
    save_registry,
    scan_conflict_events,
    update_registry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """Create a scratch dir for registry and events files."""
    return tmp_path


def _write_events(path: Path, events: list[dict]) -> str:
    """Write JSONL events to a file."""
    fpath = str(path / "spiral_events.jsonl")
    with open(fpath, "w", encoding="utf-8") as f:
        for evt in events:
            f.write(json.dumps(evt) + "\n")
    return fpath


# ---------------------------------------------------------------------------
# load_registry / save_registry
# ---------------------------------------------------------------------------


class TestLoadSaveRegistry:
    def test_missing_file_returns_empty(self, scratch: Path) -> None:
        reg = load_registry(str(scratch / "nonexistent.json"))
        assert reg == {"files": {}, "last_iteration": 0}

    def test_round_trip(self, scratch: Path) -> None:
        path = str(scratch / "hot_files.json")
        reg = {
            "files": {"lib/foo.py": {"count": 3, "weight": 3.0, "last_seen_iteration": 5}},
            "last_iteration": 5,
        }
        save_registry(reg, path)
        loaded = load_registry(path)
        assert loaded["files"]["lib/foo.py"]["count"] == 3
        assert loaded["last_iteration"] == 5

    def test_corrupt_json_returns_empty(self, scratch: Path) -> None:
        path = scratch / "hot_files.json"
        path.write_text("not json{{{", encoding="utf-8")
        reg = load_registry(str(path))
        assert reg == {"files": {}, "last_iteration": 0}


# ---------------------------------------------------------------------------
# scan_conflict_events
# ---------------------------------------------------------------------------


class TestScanConflictEvents:
    def test_no_events_file(self, scratch: Path) -> None:
        assert scan_conflict_events(str(scratch / "missing.jsonl")) == []

    def test_extract_conflicting_files(self, scratch: Path) -> None:
        events = [
            {"event": "merge_conflict_detected", "workerId": 1, "conflictingFiles": ["lib/a.py", "lib/b.py"]},
            {"event": "other_event", "data": "ignored"},
            {"event": "merge_conflict_detected", "workerId": 2, "conflictingFiles": ["lib/c.py"]},
        ]
        path = _write_events(scratch, events)
        conflicts = scan_conflict_events(path)
        assert len(conflicts) == 2
        assert conflicts[0] == ["lib/a.py", "lib/b.py"]
        assert conflicts[1] == ["lib/c.py"]

    def test_empty_conflicting_files_ignored(self, scratch: Path) -> None:
        events = [
            {"event": "merge_conflict_detected", "workerId": 1, "conflictingFiles": []},
        ]
        path = _write_events(scratch, events)
        assert scan_conflict_events(path) == []

    def test_malformed_lines_skipped(self, scratch: Path) -> None:
        fpath = scratch / "events.jsonl"
        fpath.write_text('not json\n{"event":"merge_conflict_detected","conflictingFiles":["a.py"]}\n', encoding="utf-8")
        conflicts = scan_conflict_events(str(fpath))
        assert len(conflicts) == 1


# ---------------------------------------------------------------------------
# apply_decay
# ---------------------------------------------------------------------------


class TestApplyDecay:
    def test_no_decay_within_interval(self) -> None:
        reg = {
            "files": {"a.py": {"count": 4, "weight": 4.0, "last_seen_iteration": 8}},
            "last_iteration": 10,
        }
        result = apply_decay(reg, current_iteration=10, decay_interval=5)
        assert result["files"]["a.py"]["weight"] == 4.0

    def test_single_decay(self) -> None:
        reg = {
            "files": {"a.py": {"count": 4, "weight": 4.0, "last_seen_iteration": 3}},
            "last_iteration": 8,
        }
        result = apply_decay(reg, current_iteration=8, decay_interval=5)
        assert result["files"]["a.py"]["weight"] == 2.0

    def test_double_decay(self) -> None:
        reg = {
            "files": {"a.py": {"count": 4, "weight": 4.0, "last_seen_iteration": 1}},
            "last_iteration": 11,
        }
        result = apply_decay(reg, current_iteration=11, decay_interval=5)
        assert result["files"]["a.py"]["weight"] == 1.0

    def test_removes_below_threshold(self) -> None:
        reg = {
            "files": {"a.py": {"count": 1, "weight": 1.0, "last_seen_iteration": 0}},
            "last_iteration": 10,
        }
        result = apply_decay(reg, current_iteration=10, decay_interval=5)
        assert "a.py" not in result["files"]


# ---------------------------------------------------------------------------
# update_registry
# ---------------------------------------------------------------------------


class TestUpdateRegistry:
    def test_fresh_registry(self, scratch: Path) -> None:
        events = [
            {"event": "merge_conflict_detected", "workerId": 1, "conflictingFiles": ["lib/a.py", "lib/b.py"]},
        ]
        events_path = _write_events(scratch, events)
        registry_path = str(scratch / "hot_files.json")

        reg = update_registry(events_path, registry_path, current_iteration=1)
        assert "lib/a.py" in reg["files"]
        assert "lib/b.py" in reg["files"]
        assert reg["files"]["lib/a.py"]["count"] == 1
        assert reg["last_iteration"] == 1

    def test_increments_existing(self, scratch: Path) -> None:
        registry_path = str(scratch / "hot_files.json")
        save_registry(
            {
                "files": {"lib/a.py": {"count": 2, "weight": 2.0, "first_seen_iteration": 1, "last_seen_iteration": 3}},
                "last_iteration": 3,
            },
            registry_path,
        )
        events = [{"event": "merge_conflict_detected", "workerId": 1, "conflictingFiles": ["lib/a.py"]}]
        events_path = _write_events(scratch, events)

        reg = update_registry(events_path, registry_path, current_iteration=4)
        assert reg["files"]["lib/a.py"]["count"] == 3
        assert reg["files"]["lib/a.py"]["weight"] == 3

    def test_normalizes_backslashes(self, scratch: Path) -> None:
        events = [{"event": "merge_conflict_detected", "workerId": 1, "conflictingFiles": ["lib\\a.py"]}]
        events_path = _write_events(scratch, events)
        registry_path = str(scratch / "hot_files.json")

        reg = update_registry(events_path, registry_path, current_iteration=1)
        assert "lib/a.py" in reg["files"]


# ---------------------------------------------------------------------------
# get_hot_files
# ---------------------------------------------------------------------------


class TestGetHotFiles:
    def test_above_threshold(self, scratch: Path) -> None:
        registry_path = str(scratch / "hot_files.json")
        save_registry(
            {
                "files": {
                    "lib/hot.py": {"count": 5, "weight": 5.0},
                    "lib/cold.py": {"count": 1, "weight": 1.0},
                },
                "last_iteration": 5,
            },
            registry_path,
        )
        hot = get_hot_files(registry_path, threshold=2)
        assert hot == {"lib/hot.py"}

    def test_empty_registry(self, scratch: Path) -> None:
        hot = get_hot_files(str(scratch / "missing.json"), threshold=2)
        assert hot == set()
