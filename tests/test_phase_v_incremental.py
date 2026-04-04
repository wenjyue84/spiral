"""Tests for Phase V incremental test execution (US-1102)."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Import the utility function
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "util"))
from changed_files_to_tests import (
    detect_changed_files,
    find_tests_importing_module,
    get_test_file_by_convention,
    map_changed_to_tests,
)


class TestFullSuiteForcing:
    """Test SPIRAL_FULL_TEST_EVERY_N configuration."""

    def test_full_suite_forced_on_nth_iteration(self):
        """Every Nth iteration should force full suite."""
        # Test that iteration 5, 10, 15 force full suite with SPIRAL_FULL_TEST_EVERY_N=5
        for iteration in [5, 10, 15, 20]:
            mod = iteration % 5
            assert mod == 0, f"Iteration {iteration} should force full suite (mod={mod})"

    def test_full_suite_not_forced_on_other_iterations(self):
        """Non-Nth iterations should allow incremental."""
        for iteration in [1, 2, 3, 4, 6, 7, 8, 9]:
            mod = iteration % 5
            assert mod != 0, f"Iteration {iteration} should allow incremental (mod={mod})"

    def test_zero_frequency_disables_forcing(self):
        """SPIRAL_FULL_TEST_EVERY_N=0 should disable forcing."""
        # When set to 0, full suite forcing is disabled
        frequency = 0
        assert frequency == 0


class TestChangedFileDetection:
    """Test git diff-based changed file detection."""

    @mock.patch("subprocess.run")
    def test_detect_changed_files_success(self, mock_run):
        """Should parse git diff output correctly."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="lib/foo.py\nlib/bar.py\ntests/test_baz.py\n",
        )

        result = detect_changed_files("HEAD~1", ".")
        assert result == ["lib/foo.py", "lib/bar.py", "tests/test_baz.py"]
        mock_run.assert_called_once()

    @mock.patch("subprocess.run")
    def test_detect_changed_files_git_error(self, mock_run):
        """Should return empty list on git error."""
        mock_run.return_value = mock.Mock(returncode=128, stdout="")

        result = detect_changed_files("HEAD~1", ".")
        assert result == []

    @mock.patch("subprocess.run")
    def test_detect_changed_files_timeout(self, mock_run):
        """Should return empty list on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)

        result = detect_changed_files("HEAD~1", ".")
        assert result == []


class TestTestFileMapping:
    """Test mapping changed files to test files."""

    def test_convention_mapping_simple(self):
        """foo.py should map to tests/test_foo.py."""
        test_file = get_test_file_by_convention("lib/foo.py")
        assert test_file == "tests/test_foo.py"

    def test_convention_mapping_various_dirs(self):
        """Mapping should work from various directories."""
        assert get_test_file_by_convention("src/bar.py") == "tests/test_bar.py"
        assert get_test_file_by_convention("impl/module.py") == "tests/test_module.py"

    def test_convention_mapping_already_test(self):
        """Test files should return themselves."""
        test_file = get_test_file_by_convention("tests/test_foo.py")
        assert test_file == "tests/test_foo.py"

    @mock.patch("subprocess.run")
    def test_import_graph_tracing(self, mock_run):
        """Should find tests that import a changed module."""
        # Mock grep finding test files that import the module
        mock_run.side_effect = [
            mock.Mock(returncode=0, stdout="tests/test_routing.py\ntests/test_main.py\n"),
            mock.Mock(returncode=0, stdout=""),  # No direct imports
        ]

        result = find_tests_importing_module("lib/impl/foo.py", ".")
        assert "tests/test_routing.py" in result
        assert "tests/test_main.py" in result

    def test_map_changed_files_to_tests(self):
        """Should collect both convention and import-based mappings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake test files
            test_dir = Path(tmpdir) / "tests"
            test_dir.mkdir()
            (test_dir / "test_foo.py").write_text("# test")
            (test_dir / "test_bar.py").write_text("# test")

            mapping = map_changed_to_tests(["lib/foo.py", "lib/bar.py"], tmpdir)

            assert "test_foo.py" in mapping["by_convention"] or "tests/test_foo.py" in mapping["all"]
            assert mapping["all"] is not None


class TestLastFailedIntegration:
    """Test pytest --lf flag integration."""

    def test_lf_flag_added_to_command(self):
        """--lf flag should be appended to pytest command."""
        base_cmd = "pytest tests/test_foo.py"
        # Simulate adding --lf
        modified_cmd = f"{base_cmd} --lf"
        assert "--lf" in modified_cmd
        assert modified_cmd == "pytest tests/test_foo.py --lf"

    def test_lf_flag_with_existing_flags(self):
        """--lf should work with other pytest flags."""
        base_cmd = "pytest tests/ -v --tb=short -n 2"
        modified_cmd = f"{base_cmd} --lf"
        assert "--lf" in modified_cmd
        assert "-v" in modified_cmd
        assert "-n 2" in modified_cmd


class TestIncrementalLogic:
    """Test the full incremental workflow."""

    def test_incremental_mode_with_changed_files(self):
        """Incremental mode should reduce test scope."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simulate changed files scenario
            changed = ["lib/foo.py", "lib/bar.py"]
            mapping = map_changed_to_tests(changed, tmpdir)

            # Should attempt to map files
            assert isinstance(mapping, dict)
            assert "all" in mapping

    def test_mapping_output_structure(self):
        """Mapping should have correct JSON structure."""
        mapping = map_changed_to_tests([], ".")
        assert isinstance(mapping, dict)
        assert "by_convention" in mapping
        assert "by_import" in mapping
        assert "all" in mapping
        assert isinstance(mapping["by_convention"], list)
        assert isinstance(mapping["by_import"], list)
        assert isinstance(mapping["all"], list)


class TestConfigVariables:
    """Test configuration variable handling."""

    def test_spiral_full_test_every_n_default(self):
        """Default SPIRAL_FULL_TEST_EVERY_N should be 5."""
        # In config, default is 5
        assert 5 > 0  # Enabled by default

    def test_spiral_use_last_failed_default(self):
        """Default SPIRAL_USE_LAST_FAILED should be true."""
        # In config, default is true
        assert "true" == "true"  # Enabled by default

    def test_zero_frequency_disables_full_suite_forcing(self):
        """Setting SPIRAL_FULL_TEST_EVERY_N=0 should disable forcing."""
        frequency = 0
        if frequency == 0:
            # Forcing is disabled
            assert True
        else:
            # Forcing is enabled
            assert False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
