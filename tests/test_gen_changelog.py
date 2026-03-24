"""tests/test_gen_changelog.py — Integration tests for lib/gen_changelog.py."""

from __future__ import annotations

from pathlib import Path

from lib.gen_changelog import (
    _extract_shas_from_changelog,
    append_iteration_section,
    extract_github_refs,
    find_orphan_commits,
    format_github_links,
    write_orphan_warnings,
)


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


class TestExtractGithubRefs:
    """Integration tests for extract_github_refs() with mixed issue/PR commit messages."""

    def test_bare_hash_reference(self) -> None:
        """Sample 1: Bare #NNN reference is extracted."""
        refs = extract_github_refs("feat: US-1001 add login page, refs #123")
        assert refs == [123]

    def test_closes_pattern(self) -> None:
        """Sample 2: 'closes #NNN' keyword pattern is extracted."""
        refs = extract_github_refs("fix: closes #456 handle null pointer")
        assert refs == [456]

    def test_fixes_pattern(self) -> None:
        """Sample 3: 'fixes #NNN' keyword pattern is extracted."""
        refs = extract_github_refs("fix: US-1002 fixes #789")
        assert refs == [789]

    def test_resolves_pattern(self) -> None:
        """Sample 4: 'resolves #NNN' keyword pattern is extracted."""
        refs = extract_github_refs("chore: resolves #321")
        assert refs == [321]

    def test_multiple_refs_in_one_commit(self) -> None:
        """Sample 5: Multiple #NNN refs in one commit message are all extracted."""
        refs = extract_github_refs("feat: US-1003 closes #111, fixes #222 and #333")
        assert refs == [111, 222, 333]

    def test_no_refs_returns_empty(self) -> None:
        """Sample 6: Commit with no GitHub refs returns empty list."""
        refs = extract_github_refs("docs: update readme")
        assert refs == []

    def test_duplicate_refs_deduplicated(self) -> None:
        """Sample 7: Same ref appearing twice is returned only once."""
        refs = extract_github_refs("fix: closes #100, also fixes #100")
        assert refs == [100]

    def test_mixed_keyword_and_bare_refs(self) -> None:
        """Sample 8: Mix of closes/fixes and bare #NNN refs all extracted."""
        refs = extract_github_refs("fix: closes #50 and #60, resolves #70")
        assert refs == [50, 60, 70]


class TestFormatGithubLinks:
    """Tests for format_github_links() — CHANGELOG entry link injection."""

    REPO = "https://github.com/org/repo"

    def test_bare_ref_becomes_link(self) -> None:
        """Bare #NNN is replaced with a markdown link."""
        result = format_github_links("feat: fixes #123 in login page", self.REPO)
        assert "[#123](https://github.com/org/repo/issues/123)" in result

    def test_already_formatted_not_double_replaced(self) -> None:
        """Already-formatted [#NNN](...) links are left untouched."""
        msg = "feat: [#123](https://github.com/org/repo/issues/123)"
        result = format_github_links(msg, self.REPO)
        assert result == msg

    def test_multiple_refs_formatted(self) -> None:
        """All bare #NNN refs in a message get markdown links."""
        result = format_github_links("feat: closes #10 and #20", self.REPO)
        assert "[#10](https://github.com/org/repo/issues/10)" in result
        assert "[#20](https://github.com/org/repo/issues/20)" in result


class TestAppendChangelog:
    """Integration tests for append_iteration_section() and _extract_shas_from_changelog()."""

    _COMMITS_1: list[dict[str, str]] = [
        {"commit": "abc1234", "message": "feat: US-1001 add login"},
        {"commit": "def5678", "message": "fix: US-1002 fix null pointer"},
    ]
    _COMMITS_2: list[dict[str, str]] = [
        {"commit": "ghi9012", "message": "feat: US-1003 add dashboard"},
    ]

    def test_first_run_creates_section(self, tmp_path: Path) -> None:
        """First append on a missing file creates the iteration header and commits."""
        changelog = tmp_path / "CHANGELOG.md"
        append_iteration_section(self._COMMITS_1, iteration=1, changelog_path=changelog)

        content = changelog.read_text(encoding="utf-8")
        assert "## [Iteration 1]" in content
        assert "abc1234" in content
        assert "def5678" in content

    def test_second_run_appends_new_iteration_header(self, tmp_path: Path) -> None:
        """Two runs with different commits produce two separate iteration sections."""
        changelog = tmp_path / "CHANGELOG.md"
        append_iteration_section(self._COMMITS_1, iteration=1, changelog_path=changelog)
        append_iteration_section(self._COMMITS_2, iteration=2, changelog_path=changelog)

        content = changelog.read_text(encoding="utf-8")
        assert "## [Iteration 1]" in content
        assert "## [Iteration 2]" in content
        # Both commit sets present
        assert "abc1234" in content
        assert "ghi9012" in content

    def test_sha_deduplication_prevents_redundant_entries(self, tmp_path: Path) -> None:
        """Re-running with the same commits does not duplicate entries."""
        changelog = tmp_path / "CHANGELOG.md"
        append_iteration_section(self._COMMITS_1, iteration=1, changelog_path=changelog)
        append_iteration_section(self._COMMITS_1, iteration=2, changelog_path=changelog)

        content = changelog.read_text(encoding="utf-8")
        # abc1234 appears exactly once — duplicates suppressed
        assert content.count("abc1234") == 1
        # Only one iteration header because second call added nothing new
        assert "## [Iteration 2]" not in content

    def test_extract_shas_from_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """_extract_shas_from_changelog returns empty set for nonexistent file."""
        result = _extract_shas_from_changelog(tmp_path / "CHANGELOG.md")
        assert result == set()

    def test_extract_shas_finds_written_shas(self, tmp_path: Path) -> None:
        """_extract_shas_from_changelog finds all SHAs written by append_iteration_section."""
        changelog = tmp_path / "CHANGELOG.md"
        append_iteration_section(self._COMMITS_1, iteration=1, changelog_path=changelog)
        shas = _extract_shas_from_changelog(changelog)
        assert "abc1234" in shas
        assert "def5678" in shas
