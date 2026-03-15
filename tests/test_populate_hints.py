"""Unit tests for populate_hints.py (keyword extraction and filesTouch mutation)."""
import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import populate_hints


def _make_story(sid, title="Story title", passes=False, **extra):
    """Create a minimal valid story dict."""
    s = {
        "id": sid,
        "title": title,
        "passes": passes,
        "priority": "medium",
        "description": f"Description for {sid}",
        "acceptanceCriteria": ["AC1"],
        "dependencies": [],
    }
    s.update(extra)
    return s


def _make_prd(stories, name="TestProduct", branch="main"):
    return {
        "productName": name,
        "branchName": branch,
        "userStories": stories,
    }


class TestExtractKeywords:
    """Tests for the extract_keywords pure function."""

    def test_stop_words_excluded(self):
        """Stop words like 'add', 'implement', 'for', etc. are filtered out."""
        keywords = populate_hints.extract_keywords("Add unit tests for validation module")
        # 'add', 'for' are stop words; 'unit', 'test' are also stop words
        assert "add" not in keywords
        assert "for" not in keywords
        assert "test" not in keywords
        # 'validation' and 'module' should survive
        assert "validation" in keywords
        assert "module" in keywords

    def test_short_words_excluded(self):
        """Words with 2 or fewer characters are excluded."""
        keywords = populate_hints.extract_keywords("Go to DB on a VM")
        # 'go', 'to', 'db', 'on', 'a', 'vm' — all <=2 chars or stop words
        assert len(keywords) == 0

    def test_story_prefix_stripped(self):
        """Story prefix like 'US-001 -' is removed before extraction."""
        keywords = populate_hints.extract_keywords("US-042 - Dashboard velocity chart")
        assert "042" not in keywords
        # 'dashboard', 'velocity', 'chart' should remain
        assert "dashboard" in keywords
        assert "velocity" in keywords
        assert "chart" in keywords

    def test_mixed_case_normalised(self):
        """Keywords are lowercased."""
        keywords = populate_hints.extract_keywords("Validate PRD Schema")
        assert "validate" in keywords
        assert "prd" in keywords
        assert "schema" in keywords


class TestBuildKeywordFileMapping:
    """Tests for build_keyword_file_mapping."""

    def test_only_passed_stories_contribute(self):
        """Stories with passes=false are not included in the mapping."""
        stories = [
            _make_story("US-001", title="dashboard widget", passes=True),
            _make_story("US-002", title="dashboard config", passes=False),
        ]
        story_files = {
            "US-001": ["lib/dashboard.py"],
            "US-002": ["lib/config.py"],
        }
        mapping = populate_hints.build_keyword_file_mapping(stories, story_files)
        # 'dashboard' only maps to US-001's files (passed), not US-002's
        assert "lib/dashboard.py" in mapping.get("dashboard", set())
        assert "lib/config.py" not in mapping.get("dashboard", set())

    def test_keywords_map_to_correct_files(self):
        """Title keywords are mapped to the files from matching completed stories."""
        stories = [
            _make_story("US-001", title="spiral worker partition", passes=True),
        ]
        story_files = {
            "US-001": ["lib/partition.py", "lib/worker.py"],
        }
        mapping = populate_hints.build_keyword_file_mapping(stories, story_files)
        assert "lib/partition.py" in mapping.get("partition", set())
        assert "lib/worker.py" in mapping.get("worker", set())


class TestPopulateHints:
    """Tests for the populate_hints function (filesTouch mutation)."""

    @patch.object(populate_hints, "get_completed_story_files")
    def test_stories_with_existing_filesTouch_not_overwritten(self, mock_git):
        """Stories that already have filesTouch are left unchanged."""
        mock_git.return_value = {
            "US-001": ["lib/dashboard.py"],
        }
        stories = [
            _make_story("US-001", title="dashboard widget", passes=True),
            _make_story("US-002", title="dashboard config", passes=False,
                        filesTouch=["lib/existing.py"]),
        ]
        prd = _make_prd(stories)
        updated = populate_hints.populate_hints(prd, "/fake/repo")
        us002 = prd["userStories"][1]
        assert us002["filesTouch"] == ["lib/existing.py"]
        assert updated == 0  # nothing changed

    @patch.object(populate_hints, "get_completed_story_files")
    def test_pending_story_gets_hints_from_keyword_match(self, mock_git):
        """A pending story without filesTouch gets hints when keywords match."""
        mock_git.return_value = {
            "US-001": ["lib/dashboard.py", "lib/chart.py"],
        }
        stories = [
            _make_story("US-001", title="dashboard velocity chart", passes=True),
            _make_story("US-002", title="dashboard progress widget", passes=False),
        ]
        prd = _make_prd(stories)
        updated = populate_hints.populate_hints(prd, "/fake/repo")
        us002 = prd["userStories"][1]
        assert updated >= 1
        # 'dashboard' keyword matches, so US-001's files should appear
        assert "lib/dashboard.py" in us002["filesTouch"]

    @patch.object(populate_hints, "get_completed_story_files")
    def test_empty_git_log_produces_no_hints_no_crash(self, mock_git):
        """An empty git log (no story commits) produces 0 updates and no crash."""
        mock_git.return_value = {}
        stories = [
            _make_story("US-001", title="some feature", passes=False),
        ]
        prd = _make_prd(stories)
        updated = populate_hints.populate_hints(prd, "/fake/repo")
        assert updated == 0
        assert "filesTouch" not in prd["userStories"][0]

    @patch.object(populate_hints, "get_completed_story_files")
    def test_passed_stories_skipped_for_hint_population(self, mock_git):
        """Stories with passes=true are never given filesTouch hints."""
        mock_git.return_value = {
            "US-001": ["lib/module.py"],
        }
        stories = [
            _make_story("US-001", title="module feature", passes=True),
            _make_story("US-002", title="module extension", passes=True),
        ]
        prd = _make_prd(stories)
        updated = populate_hints.populate_hints(prd, "/fake/repo")
        assert updated == 0


class TestDeriveModuleTags:
    """Tests for derive_module_tags pure function."""

    def test_single_file_in_lib(self):
        """A file directly in lib/ produces module:lib."""
        tags = populate_hints.derive_module_tags(["lib/merge_stories.py"])
        assert tags == ["module:lib"]

    def test_nested_file_uses_depth1_prefix(self):
        """A deeply nested file still uses only the top-level directory."""
        tags = populate_hints.derive_module_tags(["lib/phases/phase_r.sh"])
        assert tags == ["module:lib"]

    def test_multiple_files_same_dir_deduplicated(self):
        """Files from the same directory produce a single module tag."""
        tags = populate_hints.derive_module_tags([
            "lib/phases/phase_r.sh",
            "lib/merge_stories.py",
        ])
        assert tags == ["module:lib"]

    def test_multiple_dirs_produce_multiple_tags(self):
        """Files from different top-level dirs produce one tag each."""
        tags = populate_hints.derive_module_tags([
            "lib/merge_stories.py",
            "ralph/ralph.sh",
        ])
        assert tags == ["module:lib", "module:ralph"]

    def test_root_level_file_excluded(self):
        """A file with no directory component (e.g. 'spiral.sh') produces no tag."""
        tags = populate_hints.derive_module_tags(["spiral.sh"])
        assert tags == []

    def test_empty_list(self):
        """Empty filesTouch returns empty list."""
        tags = populate_hints.derive_module_tags([])
        assert tags == []

    def test_acceptance_criteria_example(self):
        """Exact example from US-286 AC: lib/phases/phase_r.sh + lib/merge_stories.py -> module:lib."""
        tags = populate_hints.derive_module_tags([
            "lib/phases/phase_r.sh",
            "lib/merge_stories.py",
        ])
        assert tags == ["module:lib"]


class TestAutoTagModules:
    """Tests for auto_tag_modules function."""

    def test_story_with_files_touch_gets_tags(self):
        """Stories with filesTouch get module tags appended."""
        stories = [
            _make_story("US-001", filesTouch=["lib/foo.py", "ralph/ralph.sh"]),
        ]
        updated = populate_hints.auto_tag_modules(stories)
        assert updated == 1
        assert "module:lib" in stories[0]["tags"]
        assert "module:ralph" in stories[0]["tags"]

    def test_story_without_files_touch_unchanged(self):
        """Stories without filesTouch are not modified at all."""
        stories = [_make_story("US-001")]
        updated = populate_hints.auto_tag_modules(stories)
        assert updated == 0
        assert "tags" not in stories[0]

    def test_existing_tags_preserved(self):
        """Manually-set tags are retained alongside auto-derived module tags."""
        stories = [
            _make_story("US-001", filesTouch=["lib/foo.py"], tags=["feature", "backend"]),
        ]
        populate_hints.auto_tag_modules(stories)
        assert "feature" in stories[0]["tags"]
        assert "backend" in stories[0]["tags"]
        assert "module:lib" in stories[0]["tags"]

    def test_no_duplicate_module_tags(self):
        """If module tag already exists, it is not added again."""
        stories = [
            _make_story("US-001", filesTouch=["lib/foo.py"], tags=["module:lib"]),
        ]
        populate_hints.auto_tag_modules(stories)
        assert stories[0]["tags"].count("module:lib") == 1

    def test_returns_count_of_updated_stories(self):
        """Return value equals number of stories that received new tags."""
        stories = [
            _make_story("US-001", filesTouch=["lib/foo.py"]),
            _make_story("US-002"),  # no filesTouch
            _make_story("US-003", filesTouch=["ralph/ralph.sh"]),
        ]
        updated = populate_hints.auto_tag_modules(stories)
        assert updated == 2


class TestGetCompletedStoryFiles:
    """Tests for get_completed_story_files with mocked subprocess."""

    @patch("populate_hints.subprocess.run")
    def test_parses_git_log_and_diff_tree(self, mock_run):
        """Correctly parses git log output and diff-tree file listing."""
        # First call: git log
        log_result = MagicMock()
        log_result.returncode = 0
        log_result.stdout = "abc123 feat: US-001 - Wire preflight\ndef456 feat: US-002 - Add tests\n"

        # Second call: diff-tree for US-001
        diff1 = MagicMock()
        diff1.returncode = 0
        diff1.stdout = "lib/validate.py\nspiral.sh\n"

        # Third call: diff-tree for US-002
        diff2 = MagicMock()
        diff2.returncode = 0
        diff2.stdout = "tests/test_schema.py\n"

        mock_run.side_effect = [log_result, diff1, diff2]

        result = populate_hints.get_completed_story_files("/fake/repo")
        assert "US-001" in result
        assert "lib/validate.py" in result["US-001"]
        assert "spiral.sh" in result["US-001"]
        assert "US-002" in result
        assert "tests/test_schema.py" in result["US-002"]

    @patch("populate_hints.subprocess.run")
    def test_empty_git_log_returns_empty_dict(self, mock_run):
        """Empty git log output returns an empty dict without crashing."""
        log_result = MagicMock()
        log_result.returncode = 0
        log_result.stdout = ""
        mock_run.return_value = log_result

        result = populate_hints.get_completed_story_files("/fake/repo")
        assert result == {}

    @patch("populate_hints.subprocess.run")
    def test_include_dirs_filtering(self, mock_run):
        """INCLUDE_DIRS env var filters files to only matching directories."""
        log_result = MagicMock()
        log_result.returncode = 0
        log_result.stdout = "abc123 feat: US-001 - Something\n"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = "lib/module.py\ntests/test_mod.py\nREADME.md\n"

        mock_run.side_effect = [log_result, diff_result]

        # Temporarily set INCLUDE_DIRS to only include lib/
        original = populate_hints.INCLUDE_DIRS
        populate_hints.INCLUDE_DIRS = {"lib/"}
        try:
            result = populate_hints.get_completed_story_files("/fake/repo")
            assert "lib/module.py" in result["US-001"]
            assert "tests/test_mod.py" not in result["US-001"]
            assert "README.md" not in result["US-001"]
        finally:
            populate_hints.INCLUDE_DIRS = original
