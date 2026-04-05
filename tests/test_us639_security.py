"""tests/test_us639_security.py — Security tests for `spiral lint-prd` CLI (US-534, US-639).

Verifies that the `uv run python main.py lint-prd` CLI command:
  1. Exits non-zero on malformed input without emitting Python tracebacks
  2. Never leaks environment variable values (API keys, tokens) in error output
  3. Handles missing files gracefully with user-readable error messages
  4. Returns valid JSON on both success and failure (not raw exception output)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cli_lint_prd(prd_path: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke `python main.py lint-prd` as a subprocess.

    Args:
        prd_path: Optional path to prd.json. If None, omits the argument.

    Returns:
        CompletedProcess with stdout/stderr captured.
    """
    cmd = [sys.executable, "main.py", "lint-prd"]
    if prd_path is not None:
        cmd.append(str(prd_path))

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).parent.parent),
    )


def test_us639_cli_malformed_json_exits_nonzero_no_traceback() -> None:
    """Malformed prd.json causes exit code 1 with no Python traceback.

    Creates a prd.json with invalid JSON syntax (missing comma, etc).
    Asserts:
      - returncode == 1
      - output contains no "Traceback (most recent call last)"
      - output is valid JSON
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = Path(tmpdir) / "malformed.json"
        # Write intentionally malformed JSON
        prd_path.write_text('{"productName": "Test" "branchName": "main"}', encoding="utf-8")

        result = _run_cli_lint_prd(prd_path)

        # Must exit non-zero
        assert result.returncode != 0, f"Expected non-zero exit, got {result.returncode}"

        # Combined output must not contain Python traceback marker
        combined = result.stdout + result.stderr
        assert "Traceback (most recent call last)" not in combined, (
            f"lint-prd emitted Python traceback on malformed JSON:\n{combined}"
        )

        # stdout must be valid JSON (not a raw exception)
        report = json.loads(result.stdout)
        assert isinstance(report, dict)
        assert "valid" in report
        assert report["valid"] is False
        assert isinstance(report.get("errors"), list)


def test_us639_cli_no_env_var_leakage() -> None:
    """Environment variable values must not appear in error output.

    Sets an env var, includes a credential-like string in prd.json,
    triggers validation error, and asserts the env var value is not echoed.
    """
    test_api_key = "sk-test-secret-value-12345-xyzabc"
    test_env_var_name = "TEST_SPIRAL_FAKE_API_KEY"

    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = Path(tmpdir) / "with_creds.json"
        # Create PRD with credential pattern
        prd_data = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Test Story",
                    # Include credential-like string that matches env var patterns
                    "description": f"api_key={test_api_key} database_url=postgresql://user:pass@host",
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                    # Intentionally omit 'passes' and 'priority' to trigger validation error
                }
            ],
        }
        prd_path.write_text(json.dumps(prd_data), encoding="utf-8")

        # Set env var with a different value (to verify we're checking env vars, not just the file content)
        env = os.environ.copy()
        env[test_env_var_name] = "env-var-secret-value-67890"

        result = subprocess.run(
            [sys.executable, "main.py", "lint-prd", str(prd_path)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).parent.parent),
            env=env,
        )

        combined = result.stdout + result.stderr

        # Output must not contain the API key string
        assert test_api_key not in combined, f"lint-prd leaked credential value in output:\n{combined}"

        # Output must not contain the env var value
        assert "env-var-secret-value-67890" not in combined, (
            f"lint-prd leaked environment variable value in output:\n{combined}"
        )

        # Should still output valid JSON with validation errors
        report = json.loads(result.stdout)
        assert report.get("valid") is False
        assert isinstance(report.get("errors"), list)


def test_us639_cli_missing_file_user_readable_error() -> None:
    """Missing file argument produces user-readable error, not raw FileNotFoundError.

    Invokes lint-prd with a non-existent file path.
    Asserts:
      - returncode != 0
      - output contains "File not found" or similar user-friendly message
      - output is valid JSON (not FileNotFoundError traceback)
    """
    missing_path = "/path/to/nonexistent/prd.json"

    result = _run_cli_lint_prd(missing_path)

    # Must exit non-zero
    assert result.returncode != 0, f"Expected non-zero exit for missing file, got {result.returncode}"

    combined = result.stdout + result.stderr

    # Must not contain raw Python exception traceback
    assert "Traceback (most recent call last)" not in combined, (
        f"lint-prd emitted Python traceback for missing file:\n{combined}"
    )
    assert "FileNotFoundError" not in combined, f"lint-prd emitted raw FileNotFoundError in output:\n{combined}"

    # Output must be valid JSON with user-friendly error message
    report = json.loads(result.stdout)
    assert report.get("valid") is False
    errors = report.get("errors", [])
    assert len(errors) > 0, "Expected at least one error in report"

    # At least one error message should indicate file not found (case-insensitive)
    error_messages = " ".join(str(e.get("message", "")) for e in errors)
    assert "not found" in error_messages.lower() or "cannot find" in error_messages.lower(), (
        f"Error message is not user-friendly:\n{error_messages}"
    )


def test_us639_cli_valid_prd_exits_zero() -> None:
    """Valid prd.json exits with code 0 and returns valid JSON.

    Sanity check that the CLI works correctly for valid input.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        prd_path = Path(tmpdir) / "valid.json"
        prd_data = {
            "productName": "Test Product",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Test Story",
                    "description": "A simple test story",
                    "acceptanceCriteria": ["AC1: System works"],
                    "dependencies": [],
                    "passes": False,
                    "priority": "high",
                }
            ],
        }
        prd_path.write_text(json.dumps(prd_data), encoding="utf-8")

        result = _run_cli_lint_prd(prd_path)

        # Must exit zero for valid input
        assert result.returncode == 0, f"Expected exit 0 for valid PRD, got {result.returncode}"

        # Must return valid JSON
        report = json.loads(result.stdout)
        assert report.get("valid") is True, f"Valid PRD marked as invalid:\n{report}"
        assert isinstance(report.get("errors"), list)
        assert len(report.get("errors", [])) == 0, f"Valid PRD has errors:\n{report}"
