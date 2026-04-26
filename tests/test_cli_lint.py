"""Tests for spiral lint command (US-1270)"""

import io
import json
import sys
from pathlib import Path


def test_lint_valid_prd() -> None:
    """Test that lint exits 0 with no output for valid prd.json and config"""
    from lib.cli_lint import lint

    # Capture stderr
    original_stderr = sys.stderr
    captured_stderr = io.StringIO()
    sys.stderr = captured_stderr

    try:
        exit_code = lint("prd.json", "spiral.config.sh")
        assert exit_code == 0, f"Expected exit 0, got {exit_code}"

        # Should have no output to stderr
        assert captured_stderr.getvalue() == "", f"Expected no stderr, got: {captured_stderr.getvalue()}"
    finally:
        sys.stderr = original_stderr


def test_lint_invalid_prd(tmp_path: Path) -> None:
    """Test that lint exits 1 with error messages for invalid prd.json"""
    from lib.cli_lint import lint

    # Create a bad prd.json (missing required 'userStories' field)
    bad_prd = {"productName": "Test", "branchName": "main"}
    bad_prd_path = tmp_path / "bad_prd.json"
    with open(bad_prd_path, "w", encoding="utf-8") as f:
        json.dump(bad_prd, f)

    # Copy the valid schema to tmp_path
    schema_src = Path(__file__).parent.parent / "prd.schema.json"
    schema_dst = tmp_path / "prd.schema.json"
    with open(schema_src, encoding="utf-8") as f:
        schema_dst.write_text(f.read(), encoding="utf-8")

    # Create a minimal valid config.sh in tmp_path
    config_dst = tmp_path / "spiral.config.sh"
    config_dst.write_text("# Valid config\n", encoding="utf-8")

    # Capture stderr
    original_stderr = sys.stderr
    captured_stderr = io.StringIO()
    sys.stderr = captured_stderr

    try:
        # Run lint directly
        exit_code = lint(str(bad_prd_path), str(config_dst))

        # Should exit 1
        assert exit_code == 1, f"Expected exit 1, got {exit_code}"

        # Should have error messages in stderr
        stderr_output = captured_stderr.getvalue()
        assert "ERROR:" in stderr_output, f"Expected error message in stderr, got: {stderr_output}"
        assert "prd.json" in stderr_output, f"Expected 'prd.json' in error message, got: {stderr_output}"
    finally:
        sys.stderr = original_stderr


def test_lint_undefined_variable() -> None:
    """Test that lint detects undefined variables in spiral.config.sh"""
    import tempfile

    from lib.cli_lint import check_config_sh

    # Create a config with undefined variable
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write("# A config with undefined variable\n")
        f.write("VALUE=$UNDEFINED_VAR\n")
        config_path = f.name

    try:
        errors = check_config_sh(config_path)
        assert len(errors) > 0, f"Expected error for undefined variable, got: {errors}"
        assert "UNDEFINED_VAR" in str(errors), f"Expected variable name in error, got: {errors}"
    finally:
        Path(config_path).unlink()


def test_lint_variable_with_default() -> None:
    """Test that lint allows variables with default values"""
    import tempfile

    from lib.cli_lint import check_config_sh

    # Create a config with variable having a default
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write("# A config with variable that has default\n")
        f.write("VALUE=${OPTIONAL_VAR:-default_value}\n")
        config_path = f.name

    try:
        errors = check_config_sh(config_path)
        assert len(errors) == 0, f"Expected no errors for variable with default, got: {errors}"
    finally:
        Path(config_path).unlink()
