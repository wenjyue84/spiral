"""tests/test_gen_changelog.py — Integration tests for lib/gen_changelog.py."""

from __future__ import annotations

from pathlib import Path

from lib.gen_changelog import find_orphan_commits, write_orphan_warnings


class TestFindOrphanCommits:
    """Test find_orphan_commits() with list of commit dicts."""

    def test_find_orphan_commits_returns_untagged(self) -> None:
        """Happy path: Mock git log with 3 US-/UT-tagged and 2 untagged commits returns exactly 2 orphans."""
        commits = [
            {"commit": "abc1234", "message": "feat: US-1001 add feature", "date": "2026-01-01"},
            {"commit": "def5678", "message": "fix: UT-500 fix bug", "date": "2026-01-02"},
            {"commit": "ghi9012", "message": "docs: update readme", "date": "2026-01-03"},
            {"commit": "jkl3456", "message": "feat: US-1002 new feature", "date": "2026-01-04"},
            {"commit": "mno7890", "message": "chore: cleanup code", "date": "2026-01-05"},
        ]

        orphans = find_orphan_commits(commits)

        # Should have exactly 2 orphans (the ones without story IDs)
        assert len(orphans) == 2
        assert orphans[0]["commit"] == "ghi9012"
        assert orphans[0]["message"] == "docs: update readme"
        assert orphans[0]["reason"] == "no-story-id"
        assert orphans[1]["commit"] == "mno7890"
        assert orphans[1]["message"] == "chore: cleanup code"
        assert orphans[1]["reason"] == "no-story-id"

    def test_find_orphan_commits_empty_input(self) -> None:
        """Edge case: Empty input list returns empty output."""
        result = find_orphan_commits([])
        assert result == []

    def test_find_orphan_commits_all_tagged(self) -> None:
        """Edge case: All commits tagged with story IDs returns empty list."""
        commits = [
            {"commit": "abc1234", "message": "feat: US-1001 add feature", "date": "2026-01-01"},
            {"commit": "def5678", "message": "fix: UT-500 fix bug", "date": "2026-01-02"},
        ]

        orphans = find_orphan_commits(commits)

        assert orphans == []

    def test_find_orphan_commits_case_insensitive(self) -> None:
        """Edge case: Story IDs are matched case-insensitively."""
        commits = [
            {"commit": "abc1234", "message": "feat: us-1001 lowercase story id", "date": "2026-01-01"},
            {"commit": "def5678", "message": "fix: UT-500 uppercase", "date": "2026-01-02"},
            {"commit": "ghi9012", "message": "docs: no id here", "date": "2026-01-03"},
        ]

        orphans = find_orphan_commits(commits)

        # Should have 1 orphan (the one without any story ID)
        assert len(orphans) == 1
        assert orphans[0]["commit"] == "ghi9012"

    def test_find_orphan_commits_story_id_in_body(self) -> None:
        """Edge case: Story IDs in commit body are detected."""
        commits = [
            {"commit": "abc1234", "message": "docs: update\n\nUS-1001 referenced in body", "date": "2026-01-01"},
            {"commit": "def5678", "message": "chore: cleanup", "date": "2026-01-02"},
        ]

        orphans = find_orphan_commits(commits)

        # Should have 1 orphan (def5678 has no story ID)
        assert len(orphans) == 1
        assert orphans[0]["commit"] == "def5678"


class TestWriteOrphanWarnings:
    """Test write_orphan_warnings() writes to file."""

    def test_write_orphan_warnings_creates_file(self, tmp_path: Path) -> None:
        """Happy path: Orphan warnings are written to the specified file."""
        warnings_file = tmp_path / ".spiral" / "phase_g_warnings.log"
        orphans = [
            {"commit": "abc1234", "message": "docs: update readme", "date": "2026-01-01", "reason": "no-story-id"},
            {"commit": "def5678", "message": "chore: cleanup", "date": "2026-01-02", "reason": "no-story-id"},
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
