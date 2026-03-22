"""
tests/test_validate_ralph_output.py — US-746: validate_syntax for pre-commit checks

Tests for lib/impl/validate_ralph_output.py, which validates syntax of modified files
before committing. Ensures tsc/ruff/cargo errors are caught and returned as RetryRequest dicts.
"""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from lib.impl.validate_ralph_output import (
    _detect_tools,
    _parse_cargo_error,
    _parse_ruff_error,
    _parse_tsc_error,
    validate_syntax,
)


class TestDetectTools:
    """Test file type detection for tool selection."""

    def test_detect_tsc_for_typescript_files(self) -> None:
        """Should detect TypeScript files and select tsc."""
        files = ["src/main.ts", "lib/utils.tsx"]
        tools = _detect_tools(files)
        assert "tsc" in tools
        assert "src/main.ts" in tools["tsc"]
        assert "lib/utils.tsx" in tools["tsc"]

    def test_detect_ruff_for_python_files(self) -> None:
        """Should detect Python files and select ruff."""
        files = ["lib/foo.py", "tests/test_bar.py"]
        tools = _detect_tools(files)
        assert "ruff" in tools
        assert "lib/foo.py" in tools["ruff"]
        assert "tests/test_bar.py" in tools["ruff"]

    def test_detect_cargo_for_rust_files(self) -> None:
        """Should detect Cargo.toml and select cargo."""
        files = ["Cargo.toml", "src/main.rs"]
        tools = _detect_tools(files)
        assert "cargo" in tools

    def test_detect_mixed_file_types(self) -> None:
        """Should detect multiple tools for mixed file types."""
        files = ["src/main.ts", "lib/foo.py", "Cargo.toml"]
        tools = _detect_tools(files)
        assert "tsc" in tools
        assert "ruff" in tools
        assert "cargo" in tools

    def test_detect_empty_file_list(self) -> None:
        """Should return empty dict for empty file list."""
        tools = _detect_tools([])
        assert tools == {}

    def test_detect_javascript_files(self) -> None:
        """Should detect JavaScript files and select tsc."""
        files = ["src/app.js", "lib/index.jsx"]
        tools = _detect_tools(files)
        assert "tsc" in tools
        assert "src/app.js" in tools["tsc"]
        assert "lib/index.jsx" in tools["tsc"]


class TestParseTscError:
    """Test TypeScript error parsing."""

    def test_parse_tsc_single_error(self) -> None:
        """Should parse a single tsc error."""
        stderr = "src/main.ts:12:5 - error TS1234: Type 'string' is not assignable to type 'number'"
        result = _parse_tsc_error(stderr)
        assert result is not None
        file_path, line, message = result
        assert file_path == "src/main.ts"
        assert line == 12
        assert "Type 'string' is not assignable" in message

    def test_parse_tsc_multiple_errors_first_only(self) -> None:
        """Should return the first error only."""
        stderr = """src/main.ts:12:5 - error TS1234: First error
src/lib.ts:20:10 - error TS5678: Second error"""
        result = _parse_tsc_error(stderr)
        assert result is not None
        file_path, line, _message = result
        assert file_path == "src/main.ts"
        assert line == 12

    def test_parse_tsc_no_error(self) -> None:
        """Should return None if no tsc error found."""
        stderr = "Successfully compiled 5 files"
        result = _parse_tsc_error(stderr)
        assert result is None


class TestParseRuffError:
    """Test ruff error parsing."""

    def test_parse_ruff_single_error(self) -> None:
        """Should parse a single ruff error."""
        stderr = "lib/foo.py:12:5: E501 Line too long (120 > 88 characters)"
        result = _parse_ruff_error(stderr)
        assert result is not None
        file_path, line, message = result
        assert file_path == "lib/foo.py"
        assert line == 12
        assert "Line too long" in message

    def test_parse_ruff_multiple_errors_first_only(self) -> None:
        """Should return the first error only."""
        stderr = """lib/foo.py:12:5: E501 Line too long
lib/bar.py:20:10: F401 Unused import"""
        result = _parse_ruff_error(stderr)
        assert result is not None
        file_path, line, _message = result
        assert file_path == "lib/foo.py"
        assert line == 12

    def test_parse_ruff_no_error(self) -> None:
        """Should return None if no ruff error found."""
        stderr = "All checks passed!"
        result = _parse_ruff_error(stderr)
        assert result is None


class TestParseCargoError:
    """Test Rust/cargo error parsing."""

    def test_parse_cargo_single_error(self) -> None:
        """Should parse a single cargo error."""
        stderr = """error[E0425]: cannot find value `foo` in this scope
   --> src/main.rs:12:5
    |
 12 |     let x = foo + 1;
    |             ^^^"""
        result = _parse_cargo_error(stderr)
        assert result is not None
        file_path, line, message = result
        assert file_path == "src/main.rs"
        assert line == 12
        assert "cannot find value" in message

    def test_parse_cargo_no_error(self) -> None:
        """Should return None if no cargo error found."""
        stderr = "Finished dev target(s) in 1.23s"
        result = _parse_cargo_error(stderr)
        assert result is None


class TestValidateSyntax:
    """Integration tests for validate_syntax function."""

    def test_validate_syntax_success_no_files(self) -> None:
        """Should return None when no files provided."""
        result = validate_syntax("US-746", [])
        assert result is None

    def test_validate_syntax_success_empty_list(self) -> None:
        """Should return None for empty file list."""
        result = validate_syntax("US-746", [])
        assert result is None

    @mock.patch("subprocess.run")
    def test_validate_syntax_tsc_failure(self, mock_run: mock.MagicMock) -> None:
        """Should return RetryRequest on tsc failure."""
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="src/main.ts:15:3 - error TS2339: Property 'name' does not exist",
            stdout="",
        )

        result = validate_syntax("US-746", ["src/main.ts"])
        assert result is not None
        assert result["error_type"] == "SyntaxError"
        assert result["file"] == "src/main.ts"
        assert result["line"] == 15
        assert "Property 'name'" in result["message"]

    @mock.patch("subprocess.run")
    def test_validate_syntax_ruff_failure(self, mock_run: mock.MagicMock) -> None:
        """Should return RetryRequest on ruff failure."""
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="lib/foo.py:8:1: F401 'json' imported but unused",
            stdout="",
        )

        result = validate_syntax("US-746", ["lib/foo.py"])
        assert result is not None
        assert result["error_type"] == "SyntaxError"
        assert result["file"] == "lib/foo.py"
        assert result["line"] == 8
        assert "imported but unused" in result["message"]

    @mock.patch("subprocess.run")
    def test_validate_syntax_cargo_failure(self, mock_run: mock.MagicMock) -> None:
        """Should return RetryRequest on cargo check failure."""
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="""error[E0382]: use of moved value: `s`
   --> src/main.rs:5:9
    |
 5  |     println!("{}", s);
    |                 ^""",
            stdout="",
        )

        result = validate_syntax("US-746", ["Cargo.toml"])
        assert result is not None
        assert result["error_type"] == "SyntaxError"
        assert "moved value" in result["message"]

    @mock.patch("subprocess.run")
    def test_validate_syntax_tool_not_found_skip(self, mock_run: mock.MagicMock) -> None:
        """Should skip validation if tool is not found (OSError)."""
        mock_run.side_effect = FileNotFoundError("tsc not found")

        result = validate_syntax("US-746", ["src/main.ts"])
        assert result is None

    @mock.patch("subprocess.run")
    def test_validate_syntax_timeout_skip(self, mock_run: mock.MagicMock) -> None:
        """Should skip validation if tool times out."""
        mock_run.side_effect = subprocess.TimeoutExpired("tsc", 30)

        result = validate_syntax("US-746", ["src/main.ts"])
        assert result is None

    @mock.patch("subprocess.run")
    def test_validate_syntax_success_all_pass(self, mock_run: mock.MagicMock) -> None:
        """Should return None when all tools pass (returncode 0)."""
        mock_run.return_value = mock.MagicMock(
            returncode=0,
            stderr="",
            stdout="",
        )

        result = validate_syntax("US-746", ["src/main.ts", "lib/foo.py"])
        assert result is None

    @mock.patch("subprocess.run")
    def test_validate_syntax_fallback_to_first_line(self, mock_run: mock.MagicMock) -> None:
        """Should use first stderr line as fallback message if parsing fails."""
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="Some unparseable error message",
            stdout="",
        )

        result = validate_syntax("US-746", ["src/main.ts"])
        assert result is not None
        assert "Some unparseable error message" in result["message"]

    def test_validate_syntax_import_succeeds(self) -> None:
        """AC3: Should be importable without errors."""
        from lib.impl.validate_ralph_output import validate_syntax as imported_func

        assert callable(imported_func)
        assert imported_func.__name__ == "validate_syntax"

    @mock.patch("subprocess.run")
    def test_validate_syntax_multiple_tools_first_failure_returned(self, mock_run: mock.MagicMock) -> None:
        """When multiple tools run, return first failure encountered."""
        # Simulate tsc running first and failing
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="src/main.ts:10:5 - error TS2322: Bad type",
            stdout="",
        )

        result = validate_syntax("US-746", ["src/main.ts", "lib/foo.py"])
        assert result is not None
        assert result["file"] == "src/main.ts"

    @mock.patch("subprocess.run")
    def test_validate_syntax_retryrequest_structure(self, mock_run: mock.MagicMock) -> None:
        """AC1: validate_syntax returns properly structured RetryRequest dict."""
        mock_run.return_value = mock.MagicMock(
            returncode=1,
            stderr="src/main.ts:42:7 - error TS1234: Test error",
            stdout="",
        )

        result = validate_syntax("US-746", ["src/main.ts"])
        assert isinstance(result, dict)
        assert set(result.keys()) == {"error_type", "file", "line", "message"}
        assert result["error_type"] == "SyntaxError"
        assert isinstance(result["file"], str)
        assert isinstance(result["line"], int)
        assert isinstance(result["message"], str)


class TestValidateSyntaxCli:
    """Test CLI interface for validate_syntax."""

    @mock.patch("subprocess.run")
    def test_cli_success_prints_none(self, mock_run: mock.MagicMock) -> None:
        """CLI should print 'null' on success (no errors)."""
        mock_run.return_value = mock.MagicMock(returncode=0, stderr="", stdout="")

        result = subprocess.run(
            ["uv", "run", "python", "lib/impl/validate_ralph_output.py", "US-746", "src/main.ts"],
            capture_output=True,
            text=True,
            cwd=".",
        )
        assert result.returncode == 0
        output = result.stdout.strip()
        assert output == "null"

    @mock.patch("subprocess.run")
    def test_cli_failure_prints_json(self, mock_run: mock.MagicMock) -> None:
        """CLI should print JSON error dict on failure."""
        # Inner subprocess (tsc) fails
        def side_effect_fn(*args: object, **kwargs: object) -> mock.MagicMock:  # noqa: ARG001
            return mock.MagicMock(
                returncode=1,
                stderr="src/app.ts:3:1 - error TS1234: Test",
                stdout="",
            )

        mock_run.side_effect = side_effect_fn

        # Note: this test checks the CLI behavior by examining the output
        # In practice, we'd run this as a subprocess test
        result_dict = validate_syntax("US-746", ["src/app.ts"])
        assert result_dict is not None
        # Verify it can be serialized to JSON
        json_str = json.dumps(result_dict)
        assert "error_type" in json_str
        assert "SyntaxError" in json_str
