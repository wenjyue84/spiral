"""
Tests for .claude/hooks/verify_story_acceptance.py agent hook.

Tests verify that the Stop agent hook correctly:
1. Reads hook input and story context
2. Checks file existence and modification status
3. Runs targeted pytest on story-related tests
4. Prevents infinite re-entry via stop_hook_active flag
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

# Import the verify_story_acceptance module
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
import verify_story_acceptance as vsa


class TestReadHookInput:
    """Tests for read_hook_input()."""

    def test_read_valid_json_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should parse valid JSON from stdin."""
        input_data = {"stop_hook_active": False, "some_field": "value"}
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value=json.dumps(input_data))))

        result = vsa.read_hook_input()
        assert result == input_data

    def test_read_empty_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return empty dict on invalid JSON."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="invalid json")))

        result = vsa.read_hook_input()
        assert result == {}

    def test_read_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should handle empty string input."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="")))

        result = vsa.read_hook_input()
        assert result == {}


class TestGetCurrentStory:
    """Tests for get_current_story()."""

    def test_find_story_by_id(self, tmp_path: Path) -> None:
        """Should find story with matching ID."""
        prd_content: dict[str, Any] = {
            "userStories": [
                {"id": "US-380", "title": "Story A"},
                {"id": "US-381", "title": "Story B"},
            ]
        }
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd_content))

        with patch.object(vsa, "load_prd_json", return_value=prd_content):
            result = vsa.get_current_story(tmp_path, "US-380")
            assert result is not None
            assert result["title"] == "Story A"

    def test_return_none_when_story_not_found(self, tmp_path: Path) -> None:
        """Should return None if story ID not found."""
        prd_content: dict[str, Any] = {"userStories": []}
        with patch.object(vsa, "load_prd_json", return_value=prd_content):
            result = vsa.get_current_story(tmp_path, "US-999")
            assert result is None

    def test_return_none_when_prd_empty(self, tmp_path: Path) -> None:
        """Should return None if prd.json is empty."""
        with patch.object(vsa, "load_prd_json", return_value={}):
            result = vsa.get_current_story(tmp_path, "US-380")
            assert result is None


class TestCheckFilesExist:
    """Tests for check_files_exist()."""

    def test_all_files_exist(self, tmp_path: Path) -> None:
        """Should return True when all files exist."""
        (tmp_path / "file1.py").touch()
        (tmp_path / "file2.py").touch()

        ok, reason = vsa.check_files_exist(tmp_path, ["file1.py", "file2.py"])
        assert ok is True
        assert reason == ""

    def test_missing_file(self, tmp_path: Path) -> None:
        """Should return False and reason when file missing."""
        (tmp_path / "file1.py").touch()

        ok, reason = vsa.check_files_exist(tmp_path, ["file1.py", "missing.py"])
        assert ok is False
        assert "missing.py" in reason

    def test_empty_files_list(self, tmp_path: Path) -> None:
        """Should return True for empty files list."""
        ok, reason = vsa.check_files_exist(tmp_path, [])
        assert ok is True
        assert reason == ""


class TestCheckFilesModifiedInLastCommit:
    """Tests for check_files_modified_in_last_commit()."""

    def test_all_files_modified_in_last_commit(self, tmp_path: Path) -> None:
        """Should return True when all files in last commit."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="file1.py\nfile2.py\n", stderr="")

            ok, reason = vsa.check_files_modified_in_last_commit(tmp_path, ["file1.py", "file2.py"])
            assert ok is True
            assert reason == ""

    def test_file_not_in_last_commit(self, tmp_path: Path) -> None:
        """Should return False when file not in last commit."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="file1.py\n", stderr="")

            ok, reason = vsa.check_files_modified_in_last_commit(tmp_path, ["file1.py", "missing_file.py"])
            assert ok is False
            assert "missing_file.py" in reason

    def test_git_command_failure(self, tmp_path: Path) -> None:
        """Should return True (skip check) when git command fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=128, stdout="", stderr="")

            ok, reason = vsa.check_files_modified_in_last_commit(tmp_path, ["file.py"])
            assert ok is True  # Skip check on first commit

    def test_git_timeout(self, tmp_path: Path) -> None:
        """Should return False on git timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 10)

            ok, reason = vsa.check_files_modified_in_last_commit(tmp_path, ["file.py"])
            assert ok is False
            assert "timed out" in reason.lower()

    def test_empty_files_list(self, tmp_path: Path) -> None:
        """Should return True for empty files list."""
        ok, reason = vsa.check_files_modified_in_last_commit(tmp_path, [])
        assert ok is True
        assert reason == ""


class TestRunTargetedPytest:
    """Tests for run_targeted_pytest()."""

    def test_pytest_passes(self, tmp_path: Path) -> None:
        """Should return True when pytest passes."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

            ok, reason = vsa.run_targeted_pytest(tmp_path, ["tests/test_file.py"])
            assert ok is True
            assert reason == ""

    def test_pytest_fails(self, tmp_path: Path) -> None:
        """Should return False with failure reason when pytest fails."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1,
                stdout="FAILED tests/test_file.py::test_func\n",
                stderr="assert False\n",
            )

            ok, reason = vsa.run_targeted_pytest(tmp_path, ["tests/test_file.py"])
            assert ok is False
            assert "Pytest failed" in reason

    def test_pytest_timeout(self, tmp_path: Path) -> None:
        """Should return False on pytest timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 60)

            ok, reason = vsa.run_targeted_pytest(tmp_path, ["tests/test_file.py"])
            assert ok is False
            assert "timed out" in reason.lower()

    def test_no_test_files(self, tmp_path: Path) -> None:
        """Should return True when no test files in list."""
        ok, reason = vsa.run_targeted_pytest(tmp_path, ["lib/module.py"])
        assert ok is True
        assert reason == ""

    def test_empty_files_list(self, tmp_path: Path) -> None:
        """Should return True for empty files list."""
        ok, reason = vsa.run_targeted_pytest(tmp_path, [])
        assert ok is True
        assert reason == ""

    def test_pytest_not_found(self, tmp_path: Path) -> None:
        """Should return True (skip) when pytest not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            ok, reason = vsa.run_targeted_pytest(tmp_path, ["tests/test_file.py"])
            assert ok is True


class TestMainHook:
    """Tests for main() hook logic."""

    def test_prevent_infinite_loop_with_stop_hook_active(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should exit immediately if stop_hook_active is True."""
        input_data = {"stop_hook_active": True}
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value=json.dumps(input_data))))
        monkeypatch.delenv("SPIRAL_CURRENT_STORY_ID", raising=False)

        with pytest.raises(SystemExit):
            vsa.main()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True

    def test_no_story_id_in_env(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """Should allow completion when SPIRAL_CURRENT_STORY_ID not set."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.delenv("SPIRAL_CURRENT_STORY_ID", raising=False)

        with pytest.raises(SystemExit):
            vsa.main()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True

    def test_story_not_found(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Should allow completion when story not found."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.setenv("SPIRAL_CURRENT_STORY_ID", "US-999")

        with patch.object(vsa, "get_current_story", return_value=None):
            with pytest.raises(SystemExit):
                vsa.main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True

    def test_file_not_found_blocks_completion(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should block completion if filesTouch file is missing."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.setenv("SPIRAL_CURRENT_STORY_ID", "US-380")

        story: dict[str, Any] = {
            "id": "US-380",
            "acceptanceCriteria": ["File should exist"],
            "filesTouch": ["missing_file.py"],
        }

        with patch.object(vsa, "get_current_story", return_value=story):
            with patch.object(vsa, "check_files_exist", return_value=(False, "File not found: missing_file.py")):
                with pytest.raises(SystemExit):
                    vsa.main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "missing_file.py" in output.get("reason", "")

    def test_file_not_modified_blocks_completion(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should block completion if filesTouch file not modified in last commit."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.setenv("SPIRAL_CURRENT_STORY_ID", "US-380")

        story: dict[str, Any] = {
            "id": "US-380",
            "acceptanceCriteria": ["File should be modified"],
            "filesTouch": ["lib/module.py"],
        }

        with patch.object(vsa, "get_current_story", return_value=story):
            with patch.object(vsa, "check_files_exist", return_value=(True, "")):
                with patch.object(
                    vsa,
                    "check_files_modified_in_last_commit",
                    return_value=(False, "File not modified in last commit: lib/module.py"),
                ):
                    with pytest.raises(SystemExit):
                        vsa.main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "not modified" in output.get("reason", "").lower()

    def test_pytest_failure_blocks_completion(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should block completion if targeted pytest fails."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.setenv("SPIRAL_CURRENT_STORY_ID", "US-380")

        story: dict[str, Any] = {
            "id": "US-380",
            "acceptanceCriteria": ["Tests should pass"],
            "filesTouch": ["tests/test_file.py"],
        }

        with patch.object(vsa, "get_current_story", return_value=story):
            with patch.object(vsa, "check_files_exist", return_value=(True, "")):
                with patch.object(vsa, "check_files_modified_in_last_commit", return_value=(True, "")):
                    with patch.object(
                        vsa,
                        "run_targeted_pytest",
                        return_value=(False, "Pytest failed: FAILED tests/test_file.py::test_func"),
                    ):
                        with pytest.raises(SystemExit):
                            vsa.main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is False
        assert "Pytest failed" in output.get("reason", "")

    def test_all_checks_pass_allows_completion(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should allow completion when all acceptance criteria checks pass."""
        monkeypatch.setattr("sys.stdin", Mock(read=Mock(return_value="{}")))
        monkeypatch.setenv("SPIRAL_CURRENT_STORY_ID", "US-380")

        story: dict[str, Any] = {
            "id": "US-380",
            "acceptanceCriteria": ["All checks pass"],
            "filesTouch": ["lib/module.py", "tests/test_file.py"],
        }

        with patch.object(vsa, "get_current_story", return_value=story):
            with patch.object(vsa, "check_files_exist", return_value=(True, "")):
                with patch.object(vsa, "check_files_modified_in_last_commit", return_value=(True, "")):
                    with patch.object(vsa, "run_targeted_pytest", return_value=(True, "")):
                        with pytest.raises(SystemExit):
                            vsa.main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["ok"] is True


class TestIntegration:
    """Integration tests with real prd.json structure."""

    def test_with_real_prd_structure(self, tmp_path: Path) -> None:
        """Should work with realistic prd.json structure."""
        prd_content: dict[str, Any] = {
            "userStories": [
                {
                    "id": "US-380",
                    "title": "Add Stop agent-based hook",
                    "acceptanceCriteria": [
                        "Hook defined in settings.json",
                        "Agent verifies file existence",
                    ],
                    "filesTouch": ["lib/module.py"],
                    "passes": False,
                }
            ]
        }
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd_content))

        with patch.object(vsa, "load_prd_json", return_value=prd_content):
            story = vsa.get_current_story(tmp_path, "US-380")
            assert story is not None
            assert story["title"] == "Add Stop agent-based hook"
            assert len(story["acceptanceCriteria"]) == 2
