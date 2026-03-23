"""tests/test_gen_changelog.py — Integration tests for lib/gen_changelog.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from lib.gen_changelog import find_orphan_commits, write_orphan_warnings


class TestFindOrphanCommits:
    """Test find_orphan_commits() with mocked git subprocess calls."""

    def test_commits_with_story_ids_not_orphans(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Happy path: Commits with US-NNN or UT-NNN story IDs are not marked as orphans."""
        # Mock git log to return commits with story IDs in subject + body
        def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0

            # First call: git log --format=%H %s (list commits)
            if "--format=%H %s" in cmd:
                result.stdout = "abc1234 feat: US-1001 add feature\ndef5678 fix: US-1002 fix bug\n"
            # Subsequent calls: git log -1 --format=%B (get full message with story ID)
            elif "--format=%B" in cmd:
                result.stdout = "feat: US-1001 add feature\n\nFull body with US-1001 reference"

            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        orphans = find_orphan_commits("/fake/repo")

        # Should have no orphans
        assert orphans == []

    def test_commits_without_story_ids_are_orphans(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Edge case: Commits without US-NNN or UT-NNN story IDs are marked as orphans."""
        def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0

            # First call: git log --format=%H %s
            if "--format=%H %s" in cmd:
                result.stdout = "abc1234 docs: update readme\ndef5678 chore: cleanup\n"
            # Subsequent calls: git log -1 --format=%B (get full message without story ID)
            elif "--format=%B" in cmd:
                result.stdout = "docs: update readme\n\nNo story ID in body either"

            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        orphans = find_orphan_commits("/fake/repo")

        # Should have 2 orphans
        assert len(orphans) == 2
        assert orphans[0]["hash"] == "abc1234"
        assert orphans[0]["subject"] == "docs: update readme"
        assert orphans[1]["hash"] == "def5678"
        assert orphans[1]["subject"] == "chore: cleanup"

    def test_mixed_commits_with_and_without_story_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Edge case: Some commits have story IDs, some don't."""
        call_count = [0]

        def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0

            if "--format=%H %s" in cmd:
                # One with story ID, one without
                result.stdout = "abc1234 feat: US-999 with ID\ndef5678 docs: no ID here\n"
            elif "--format=%B" in cmd:
                call_count[0] += 1
                # First commit (abc1234): has US-999
                if call_count[0] == 1:
                    result.stdout = "feat: US-999 with ID\n\nBody text"
                # Second commit (def5678): no story ID
                else:
                    result.stdout = "docs: no ID here\n\nBody text without story reference"

            return result

        monkeypatch.setattr(subprocess, "run", mock_run)

        orphans = find_orphan_commits("/fake/repo")

        # Should have 1 orphan (the one without story ID)
        assert len(orphans) == 1
        assert orphans[0]["hash"] == "def5678"
        assert orphans[0]["subject"] == "docs: no ID here"


class TestWriteOrphanWarnings:
    """Test write_orphan_warnings() writes to file."""

    def test_write_orphan_warnings_creates_file(self, tmp_path: Path) -> None:
        """Happy path: Orphan warnings are written to the specified file."""
        warnings_file = tmp_path / ".spiral" / "phase_g_warnings.log"
        orphans = [
            {"hash": "abc1234", "subject": "docs: update readme"},
            {"hash": "def5678", "subject": "chore: cleanup"},
        ]

        write_orphan_warnings(orphans, str(warnings_file))

        # File should exist and contain both orphans
        assert warnings_file.exists()
        content = warnings_file.read_text(encoding="utf-8")
        assert "abc1234 docs: update readme" in content
        assert "def5678 chore: cleanup" in content

    def test_write_empty_orphans_creates_empty_file(self, tmp_path: Path) -> None:
        """Edge case: Empty orphans list creates an empty file."""
        warnings_file = tmp_path / ".spiral" / "phase_g_warnings.log"

        write_orphan_warnings([], str(warnings_file))

        # File should exist but be empty
        assert warnings_file.exists()
        assert warnings_file.read_text(encoding="utf-8") == ""
