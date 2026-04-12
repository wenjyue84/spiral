"""Regression tests for US-1102: incremental Phase V test execution.

Guards against breakage of:
  - git diff --name-only based changed-file detection
  - naming-convention source→test mapping (foo.py → tests/test_foo.py)
  - map_changed_to_tests output contract (by_convention / by_import / all)

Run: uv run pytest tests/ -k us_1102 -v
"""

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "util"))
from changed_files_to_tests import (
    detect_changed_files,
    get_test_file_by_convention,
    map_changed_to_tests,
)


@pytest.mark.us_1102
def test_us1102_detect_changed_files_calls_git_diff() -> None:
    """detect_changed_files must invoke git diff --name-only and parse output."""
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout="lib/foo.py\nlib/bar.py\n")
        result = detect_changed_files("HEAD~1", ".")
        args = mock_run.call_args[0][0]
        assert "git" in args
        assert "diff" in args
        assert "--name-only" in args
    assert result == ["lib/foo.py", "lib/bar.py"]


@pytest.mark.us_1102
def test_us1102_detect_changed_files_git_error_returns_empty() -> None:
    """git failure (non-zero returncode) must return [] without raising."""
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=128, stdout="")
        assert detect_changed_files("HEAD~1", ".") == []


@pytest.mark.us_1102
def test_us1102_detect_changed_files_timeout_returns_empty() -> None:
    """Subprocess timeout must return [] without propagating the exception."""
    with mock.patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)
        assert detect_changed_files("HEAD~1", ".") == []


@pytest.mark.us_1102
def test_us1102_convention_maps_source_to_test() -> None:
    """Source files must map to tests/test_<basename>.py by convention."""
    assert get_test_file_by_convention("lib/foo.py") == "tests/test_foo.py"
    assert get_test_file_by_convention("src/nested/bar.py") == "tests/test_bar.py"


@pytest.mark.us_1102
def test_us1102_map_output_has_required_keys() -> None:
    """map_changed_to_tests must return dict with by_convention, by_import, all."""
    result = map_changed_to_tests([], ".")
    assert isinstance(result, dict)
    assert "by_convention" in result
    assert "by_import" in result
    assert "all" in result
    assert isinstance(result["by_convention"], list)
    assert isinstance(result["by_import"], list)
    assert isinstance(result["all"], list)
