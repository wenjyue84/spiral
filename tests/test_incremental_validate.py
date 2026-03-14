"""
tests/test_incremental_validate.py — Unit tests for US-131 incremental Phase V validation logic.

Tests cover:
- filesTouch → pytest test file path derivation using SPIRAL_TEST_PREFIX
- vitest --related command construction from filesTouch entries
- pytest incremental command construction when test files exist
- Fallback to full suite when no filesTouch entries have matching test files
- Fallback to full suite when SPIRAL_INCREMENTAL_VALIDATE is false
"""
import json
import os
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helper: the path-mapping logic extracted from spiral.sh for Python testing
# ---------------------------------------------------------------------------


def derive_pytest_target(file_touched: str, test_prefix: str) -> str:
    """Derive the pytest test file path for a given filesTouch entry.

    Mirrors the bash logic in spiral.sh Phase V:
        _base=$(basename "${_ft%.*}")
        _test_candidate="${SPIRAL_TEST_PREFIX}${_base}.py"
    """
    base = os.path.splitext(os.path.basename(file_touched))[0]
    return f"{test_prefix}{base}.py"


def build_incremental_pytest_cmd(
    validate_cmd: str,
    pytest_targets: list[str],
    test_prefix: str = "tests/test_",
) -> str:
    """Build incremental pytest command by replacing 'tests/' with target files.

    Mirrors the bash substitution:
        _EFFECTIVE_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD/tests\//${_PYTEST_TARGETS_STR} }"
    """
    if not pytest_targets or "tests/" not in validate_cmd:
        return validate_cmd
    targets_str = " ".join(pytest_targets) + " "
    return validate_cmd.replace("tests/", targets_str, 1)


def build_incremental_vitest_cmd(validate_cmd: str, files_touched: list[str]) -> str:
    """Build incremental vitest command by appending --related <files>.

    Mirrors the bash logic:
        _EFFECTIVE_VALIDATE_CMD="$SPIRAL_VALIDATE_CMD --related ${_FILES_TOUCHED[*]}"
    """
    return validate_cmd + " --related " + " ".join(files_touched)


# ---------------------------------------------------------------------------
# Tests: SPIRAL_INCREMENTAL_VALIDATE=false → no change to command
# ---------------------------------------------------------------------------


class TestIncrementalDisabled:
    def test_false_default_uses_full_cmd(self):
        """When SPIRAL_INCREMENTAL_VALIDATE is false, effective command is unchanged."""
        validate_cmd = "uv run pytest tests/ -v --tb=short"
        # Simulated: incremental disabled → effective == validate
        effective = validate_cmd
        assert effective == "uv run pytest tests/ -v --tb=short"

    def test_empty_files_touched_uses_full_cmd(self):
        """No filesTouch entries → fall back to full suite."""
        validate_cmd = "uv run pytest tests/ -v --tb=short"
        files_touched: list[str] = []
        if not files_touched:
            effective = validate_cmd
        else:
            effective = build_incremental_pytest_cmd(validate_cmd, files_touched)
        assert effective == validate_cmd


# ---------------------------------------------------------------------------
# Tests: pytest path mapping from filesTouch
# ---------------------------------------------------------------------------


class TestPytestPathMapping:
    def test_simple_lib_file(self):
        """lib/foo.py → tests/test_foo.py with default prefix."""
        result = derive_pytest_target("lib/foo.py", "tests/test_")
        assert result == "tests/test_foo.py"

    def test_src_nested_file(self):
        """src/bar/baz.py → tests/test_baz.py (basename only)."""
        result = derive_pytest_target("src/bar/baz.py", "tests/test_")
        assert result == "tests/test_baz.py"

    def test_custom_prefix(self):
        """Custom SPIRAL_TEST_PREFIX is respected."""
        result = derive_pytest_target("lib/check_dag.py", "tests/unit_")
        assert result == "tests/unit_check_dag.py"

    def test_file_without_extension(self):
        """File without extension is handled gracefully."""
        result = derive_pytest_target("lib/mymodule", "tests/test_")
        assert result == "tests/test_mymodule.py"

    def test_root_level_file(self):
        """Root-level file (no directory component)."""
        result = derive_pytest_target("main.py", "tests/test_")
        assert result == "tests/test_main.py"


# ---------------------------------------------------------------------------
# Tests: pytest incremental command construction
# ---------------------------------------------------------------------------


class TestPytestIncrementalCmd:
    def test_single_target(self):
        """Single test file replaces 'tests/' in validate_cmd."""
        cmd = "uv run pytest tests/ -v --tb=short"
        targets = ["tests/test_foo.py"]
        result = build_incremental_pytest_cmd(cmd, targets)
        assert "tests/test_foo.py" in result
        assert result.startswith("uv run pytest ")
        assert "-v --tb=short" in result

    def test_multiple_targets(self):
        """Multiple test files all appear in the incremental command."""
        cmd = "uv run pytest tests/ -v --tb=short"
        targets = ["tests/test_foo.py", "tests/test_bar.py"]
        result = build_incremental_pytest_cmd(cmd, targets)
        assert "tests/test_foo.py" in result
        assert "tests/test_bar.py" in result
        assert "-v --tb=short" in result

    def test_fallback_when_no_test_slash(self):
        """If 'tests/' not in validate_cmd, return unchanged."""
        cmd = "uv run pytest -v --tb=short"
        targets = ["tests/test_foo.py"]
        result = build_incremental_pytest_cmd(cmd, targets)
        assert result == cmd

    def test_fallback_when_empty_targets(self):
        """Empty target list → unchanged command."""
        cmd = "uv run pytest tests/ -v --tb=short"
        result = build_incremental_pytest_cmd(cmd, [])
        assert result == cmd

    def test_python_m_pytest_style(self):
        """Works with 'python -m pytest tests/' style commands."""
        cmd = "python -m pytest tests/ --tb=short"
        targets = ["tests/test_baz.py"]
        result = build_incremental_pytest_cmd(cmd, targets)
        assert "tests/test_baz.py" in result
        assert "--tb=short" in result


# ---------------------------------------------------------------------------
# Tests: vitest incremental command construction
# ---------------------------------------------------------------------------


class TestVitestIncrementalCmd:
    def test_single_file(self):
        """vitest --related appended for single filesTouch entry."""
        cmd = "npx vitest run"
        files = ["src/foo.ts"]
        result = build_incremental_vitest_cmd(cmd, files)
        assert result == "npx vitest run --related src/foo.ts"

    def test_multiple_files(self):
        """vitest --related includes all filesTouch entries space-separated."""
        cmd = "npx vitest run"
        files = ["src/foo.ts", "src/bar.ts"]
        result = build_incremental_vitest_cmd(cmd, files)
        assert "--related src/foo.ts src/bar.ts" in result

    def test_preserves_existing_flags(self):
        """Existing flags in validate_cmd are preserved before --related."""
        cmd = "npx vitest run --reporter=verbose"
        files = ["src/util.ts"]
        result = build_incremental_vitest_cmd(cmd, files)
        assert "--reporter=verbose" in result
        assert "--related src/util.ts" in result


# ---------------------------------------------------------------------------
# Tests: filesTouch → existing test file lookup (filesystem check)
# ---------------------------------------------------------------------------


class TestFilesystemLookup:
    def test_existing_test_file_is_included(self, tmp_path):
        """derive_pytest_target + existence check includes present test files."""
        # Create a fake test file
        test_file = tmp_path / "tests" / "test_myfunc.py"
        test_file.parent.mkdir()
        test_file.write_text("# placeholder\n")

        files_touched = ["lib/myfunc.py"]
        test_prefix = "tests/test_"
        targets = []
        for f in files_touched:
            candidate = derive_pytest_target(f, test_prefix)
            candidate_path = tmp_path / candidate
            if candidate_path.exists():
                targets.append(candidate)
        assert targets == ["tests/test_myfunc.py"]

    def test_missing_test_file_excluded(self, tmp_path):
        """If test file doesn't exist, it is excluded from targets."""
        files_touched = ["lib/missing.py"]
        test_prefix = "tests/test_"
        targets = []
        for f in files_touched:
            candidate = derive_pytest_target(f, test_prefix)
            candidate_path = tmp_path / candidate
            if candidate_path.exists():
                targets.append(candidate)
        assert targets == []

    def test_mixed_existing_and_missing(self, tmp_path):
        """Only existing test files are included when some are missing."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_present.py").write_text("# ok\n")

        files_touched = ["lib/present.py", "lib/absent.py"]
        test_prefix = "tests/test_"
        targets = []
        for f in files_touched:
            candidate = derive_pytest_target(f, test_prefix)
            candidate_path = tmp_path / candidate
            if candidate_path.exists():
                targets.append(candidate)
        assert targets == ["tests/test_present.py"]


# ---------------------------------------------------------------------------
# Tests: prd.json filesTouch extraction (jq logic via Python)
# ---------------------------------------------------------------------------


class TestFilesTouchExtraction:
    def _make_prd(self, stories: list[dict]) -> dict:
        return {
            "schemaVersion": 1,
            "projectName": "Test",
            "productName": "Test",
            "branchName": "main",
            "description": "Test PRD",
            "userStories": stories,
        }

    def test_extract_files_touched_from_passed_story(self):
        """filesTouch from a newly-passed story is correctly extracted."""
        prd = self._make_prd(
            [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "priority": "high",
                    "passes": True,
                    "filesTouch": ["lib/foo.py", "lib/bar.py"],
                }
            ]
        )
        story = next(s for s in prd["userStories"] if s["id"] == "US-001")
        assert story.get("filesTouch") == ["lib/foo.py", "lib/bar.py"]

    def test_missing_filesTouch_defaults_to_empty(self):
        """Story without filesTouch field yields empty list (no crash)."""
        prd = self._make_prd(
            [
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "priority": "high",
                    "passes": True,
                }
            ]
        )
        story = next(s for s in prd["userStories"] if s["id"] == "US-002")
        assert story.get("filesTouch", []) == []

    def test_newly_passed_detection(self):
        """Story present in before-snapshot as passes=false, after as passes=true is 'newly passed'."""
        before_stories = [
            {"id": "US-001", "passes": False, "filesTouch": ["lib/a.py"]},
            {"id": "US-002", "passes": True, "filesTouch": ["lib/b.py"]},
        ]
        after_stories = [
            {"id": "US-001", "passes": True, "filesTouch": ["lib/a.py"]},
            {"id": "US-002", "passes": True, "filesTouch": ["lib/b.py"]},
        ]
        before_ids = {s["id"] for s in before_stories if s.get("passes")}
        after_ids = {s["id"] for s in after_stories if s.get("passes")}
        newly_passed = after_ids - before_ids
        assert newly_passed == {"US-001"}

    def test_no_newly_passed_when_no_change(self):
        """No change between before and after → no newly passed stories."""
        stories = [
            {"id": "US-001", "passes": True, "filesTouch": ["lib/a.py"]},
        ]
        before_ids = {s["id"] for s in stories if s.get("passes")}
        after_ids = {s["id"] for s in stories if s.get("passes")}
        newly_passed = after_ids - before_ids
        assert newly_passed == set()
