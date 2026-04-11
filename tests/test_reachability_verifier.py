"""Regression test for lib/reachability_verifier.py (US-1007).

Covers core observable behavior of the Functional Reachability Verifier:
- Non-Phase stories are skipped (returns "not_a_phase_story")
- Phase stories with new Python files trigger reachability check
- Call sites are found when modules are imported in spiral.sh or main.py
- Reachability status is correct (all modules reachable = True)
- Edge cases: no new files, files not in lib/, etc.

This test guards against future breakage where the reachability verifier:
- Fails to detect when Phase stories' modules are NOT called
- Incorrectly skips non-Phase stories
- Misses call sites
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from reachability_verifier import find_calls, get_new_python_files, verify_reachability


@pytest.mark.us_1194
class TestReachabilityVerifier:
    """Tests for reachability_verifier.py (US-1007)."""

    def test_skip_non_phase_stories(self) -> None:
        """Non-Phase stories should return not_a_phase_story."""
        result = verify_reachability("Some random story")
        assert result["reachable"] is True
        assert result["reason"] == "not_a_phase_story"

    def test_skip_phase_prefix_only_requires_phase_prefix(self) -> None:
        """Story title starting with 'Phase' triggers check."""
        # Just needs to start with "Phase", could be "Phase X:", "Phase I:", etc.
        result = verify_reachability("Phase V: Some feature")
        # Result depends on git diff, but should not skip due to title
        assert "reason" not in result or result["reason"] != "not_a_phase_story"

    def test_no_new_python_files(self) -> None:
        """Phase story with no new .py files should skip."""
        with patch("reachability_verifier.get_new_python_files") as mock_get:
            mock_get.return_value = []
            result = verify_reachability("Phase V: Some feature")
            assert result["reachable"] is True
            assert result["reason"] == "no_new_python_files"

    def test_new_files_not_in_lib(self) -> None:
        """New .py files outside lib/ dir should skip."""
        with patch("reachability_verifier.get_new_python_files") as mock_get:
            mock_get.return_value = ["tests/new_test.py", "scripts/tool.py"]
            result = verify_reachability("Phase V: Some feature")
            assert result["reachable"] is True
            assert result["reason"] == "new_files_not_in_lib"

    def test_find_calls_with_import_statement(self) -> None:
        """find_calls should locate 'import module_name' pattern."""
        # Create a temp file with import statement
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            temp_path = f.name
            f.write("#!/bin/bash\nimport my_module\necho 'done'\n")
        try:
            calls = find_calls(temp_path, "my_module")
            assert len(calls) > 0
            assert "import my_module" in calls[0]
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_find_calls_with_from_import(self) -> None:
        """find_calls should locate 'from module_name' pattern."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            temp_path = f.name
            f.write("from my_module import func\ndef test():\n    pass\n")
        try:
            calls = find_calls(temp_path, "my_module")
            assert len(calls) > 0
            assert "from my_module" in calls[0]
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_find_calls_with_lib_path_pattern(self) -> None:
        """find_calls should locate 'lib/module_name.py' pattern."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            temp_path = f.name
            f.write("#!/bin/bash\npython lib/my_module.py --flag\n")
        try:
            calls = find_calls(temp_path, "my_module")
            assert len(calls) > 0
            assert "lib/my_module.py" in calls[0]
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_find_calls_with_lib_dot_pattern(self) -> None:
        """find_calls should locate 'lib.module_name' pattern."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            temp_path = f.name
            f.write("from lib.my_module import func\nresult = func()\n")
        try:
            calls = find_calls(temp_path, "my_module")
            assert len(calls) > 0
            assert "lib.my_module" in calls[0]
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_find_calls_returns_empty_for_nonexistent_file(self) -> None:
        """find_calls should return [] for missing file."""
        calls = find_calls("/nonexistent/path/to/file.txt", "module")
        assert calls == []

    def test_find_calls_returns_context_around_match(self) -> None:
        """find_calls should return context (±40 chars) around match."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            temp_path = f.name
            f.write("prefix_text_here from my_module import X suffix_text_here\n")
        try:
            calls = find_calls(temp_path, "my_module")
            assert len(calls) > 0
            # Should include context
            assert "from my_module" in calls[0]
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_reachability_all_modules_found(self) -> None:
        """Phase story where all modules are reachable should pass."""
        with patch("reachability_verifier.get_new_python_files") as mock_get, \
             patch("reachability_verifier.find_calls") as mock_calls:
            mock_get.return_value = ["lib/new_module.py"]
            # Simulate finding the call
            mock_calls.return_value = ["some context from new_module import"]

            result = verify_reachability("Phase V: Test feature")
            assert result["reachable"] is True
            assert "new_module" in result.get("modules_checked", [])

    def test_reachability_module_not_found(self) -> None:
        """Phase story where module is NOT reachable should fail."""
        with patch("reachability_verifier.get_new_python_files") as mock_get, \
             patch("reachability_verifier.find_calls") as mock_calls:
            mock_get.return_value = ["lib/unreachable_module.py"]
            # Simulate NOT finding the call
            mock_calls.return_value = []

            result = verify_reachability("Phase V: Test feature")
            assert result["reachable"] is False
            assert result["call_sites"]["unreachable_module"] is None

    def test_reachability_multiple_modules_mixed(self) -> None:
        """Phase story with multiple modules, some reachable and some not."""
        with patch("reachability_verifier.get_new_python_files") as mock_get, \
             patch("reachability_verifier.find_calls") as mock_calls:
            mock_get.return_value = ["lib/module_a.py", "lib/module_b.py"]

            def find_calls_side_effect(entry_point: str, module: str) -> list[str]:
                if module == "module_a":
                    return ["import module_a found here"]
                return []  # module_b not found

            mock_calls.side_effect = find_calls_side_effect

            result = verify_reachability("Phase V: Test feature")
            assert result["reachable"] is False
            assert result["call_sites"]["module_a"] is not None
            assert result["call_sites"]["module_b"] is None

    def test_reachability_checks_both_entry_points(self) -> None:
        """Reachability check should search both spiral.sh and main.py."""
        with patch("reachability_verifier.get_new_python_files") as mock_get, \
             patch("reachability_verifier.find_calls") as mock_calls:
            mock_get.return_value = ["lib/test_module.py"]

            call_count = 0

            def find_calls_side_effect(entry_point: str, module: str) -> list[str]:
                nonlocal call_count
                call_count += 1
                if entry_point == "main.py" and module == "test_module":
                    return ["from test_module import X"]
                return []

            mock_calls.side_effect = find_calls_side_effect

            result = verify_reachability("Phase V: Test feature")
            # Should call find_calls twice (spiral.sh and main.py)
            assert call_count >= 2
            assert result["reachable"] is True


@pytest.mark.us_1194
class TestGetNewPythonFiles:
    """Tests for get_new_python_files() helper."""

    def test_empty_result_when_no_added_files(self) -> None:
        """get_new_python_files should return [] when git diff has no new files."""
        with patch("reachability_verifier.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            result = get_new_python_files("HEAD")
            assert result == []

    def test_filters_non_python_files(self) -> None:
        """get_new_python_files should only return .py files."""
        with patch("reachability_verifier.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="lib/new.py\nlib/data.json\ndocs/readme.md\nlib/another.py",
                returncode=0,
            )
            result = get_new_python_files("HEAD")
            assert result == ["lib/new.py", "lib/another.py"]

    def test_handles_git_error_gracefully(self) -> None:
        """get_new_python_files should return [] on git error."""
        with patch("reachability_verifier.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("git not found")
            result = get_new_python_files("HEAD")
            assert result == []
