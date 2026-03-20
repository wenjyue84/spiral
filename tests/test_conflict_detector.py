"""Tests for lib/conflict_detector.py — Phase M file conflict detection."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import conflict_detector as cd

# ── Fixtures ───────────────────────────────────────────────────────────────────


def _story(
    sid: str,
    priority: str = "medium",
    files: list[str] | None = None,
    passes: bool = False,
) -> dict:
    s: dict = {"id": sid, "priority": priority, "title": f"Story {sid}", "passes": passes}
    if files is not None:
        s["filesTouch"] = files
    return s


def _prd(tmp_path: Path, stories: list[dict]) -> Path:
    prd = {"productName": "Test", "branchName": "main", "userStories": stories}
    p = tmp_path / "prd.json"
    p.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return p


# ── detect_conflicts ──────────────────────────────────────────────────────────


class TestDetectConflicts:
    def test_no_overlap(self) -> None:
        stories = [
            _story("US-501", files=["src/auth.ts"]),
            _story("US-502", files=["src/db.ts"]),
        ]
        assert cd.detect_conflicts(stories) == []

    def test_overlap_detected(self) -> None:
        stories = [
            _story("US-501", files=["src/auth.ts", "src/utils.ts"]),
            _story("US-502", files=["src/auth.ts", "src/db.ts"]),
        ]
        conflicts = cd.detect_conflicts(stories)
        assert len(conflicts) == 1
        assert conflicts[0]["storyA"] == "US-501"
        assert conflicts[0]["storyB"] == "US-502"
        assert conflicts[0]["conflict_files"] == "src/auth.ts"

    def test_multiple_overlapping_files(self) -> None:
        stories = [
            _story("US-501", files=["src/auth.ts", "src/utils.ts"]),
            _story("US-502", files=["src/auth.ts", "src/utils.ts"]),
        ]
        conflicts = cd.detect_conflicts(stories)
        assert len(conflicts) == 1
        assert conflicts[0]["conflict_files"] == "src/auth.ts|src/utils.ts"

    def test_passed_stories_excluded(self) -> None:
        stories = [
            _story("US-501", files=["src/auth.ts"], passes=True),
            _story("US-502", files=["src/auth.ts"]),
        ]
        assert cd.detect_conflicts(stories) == []

    def test_empty_files_to_touch(self) -> None:
        stories = [
            _story("US-501", files=[]),
            _story("US-502", files=["src/auth.ts"]),
        ]
        assert cd.detect_conflicts(stories) == []

    def test_no_files_to_touch(self) -> None:
        stories = [
            _story("US-501"),
            _story("US-502", files=["src/auth.ts"]),
        ]
        assert cd.detect_conflicts(stories) == []

    def test_three_way_conflict(self) -> None:
        stories = [
            _story("US-501", files=["src/auth.ts"]),
            _story("US-502", files=["src/auth.ts"]),
            _story("US-503", files=["src/auth.ts"]),
        ]
        conflicts = cd.detect_conflicts(stories)
        assert len(conflicts) == 3  # 501-502, 501-503, 502-503

    def test_decomposed_stories_excluded(self) -> None:
        s = _story("US-501", files=["src/auth.ts"])
        s["_decomposed"] = True
        stories = [s, _story("US-502", files=["src/auth.ts"])]
        assert cd.detect_conflicts(stories) == []


# ── Integration test: US-501 + US-502 scenario ───────────────────────────────


class TestIntegration:
    def test_merge_conflict_us501_us502(self, tmp_path: Path) -> None:
        """Integration test: US-501 and US-502 both modify src/auth.ts."""
        stories = [
            _story("US-501", files=["src/auth.ts", "src/middleware.ts"]),
            _story("US-502", files=["src/auth.ts", "src/routes.ts"]),
            _story("US-503", files=["src/db.ts"]),
        ]
        prd_path = _prd(tmp_path, stories)

        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)

        conflicts = cd.detect_conflicts(prd["userStories"])
        assert len(conflicts) == 1
        assert conflicts[0]["storyA"] == "US-501"
        assert conflicts[0]["storyB"] == "US-502"
        assert "src/auth.ts" in conflicts[0]["conflict_files"]

    def test_conflict_logged_to_file(self, tmp_path: Path) -> None:
        """Verify conflicts are appended to JSONL log file."""
        stories = [
            _story("US-501", files=["src/auth.ts"]),
            _story("US-502", files=["src/auth.ts"]),
        ]
        conflicts = cd.detect_conflicts(stories)
        log_file = str(tmp_path / "conflict_report.jsonl")
        cd.log_conflicts(conflicts, log_file)

        with open(log_file, encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "file_conflict_detected"
        assert entry["storyA"] == "US-501"
        assert entry["storyB"] == "US-502"
        assert entry["conflict_files"] == "src/auth.ts"
