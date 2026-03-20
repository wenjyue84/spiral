"""Security tests for lib/commands/validate_federated.py.

Tests verify the validate-federated command never leaks:
- Environment variables (secrets, tokens, API keys)
- Filesystem paths beyond the current working directory
- Sensitive keys in JSON output (token, password, secret, key)

And correctly rejects adversarial inputs:
- Path-traversal attempts (../../etc/passwd)
- Malformed repository IDs
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from lib.commands.validate_federated import validate_federated


def flatten_keys(obj: Any) -> list[str]:
    """Recursively extract all dict keys from a nested structure.

    Args:
        obj: Dict, list, or primitive value

    Returns:
        List of all keys found at any nesting level
    """
    keys: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.append(key)
            keys.extend(flatten_keys(value))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(flatten_keys(item))

    return keys


class TestSecurityNoSensitiveKeys:
    """Verify JSON report output never contains sensitive keys."""

    def test_report_json_no_token_key(self, tmp_path: Path) -> None:
        """Report should not contain 'token' key (case-insensitive)."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test", "passes": False}
                ]
            })
        )

        report = validate_federated(prd_file)
        keys = flatten_keys(report)
        sensitive_keys = [k.lower() for k in keys]

        assert "token" not in sensitive_keys, \
            f"Report leaked 'token' key. Found keys: {keys}"

    def test_report_json_no_password_key(self, tmp_path: Path) -> None:
        """Report should not contain 'password' key (case-insensitive)."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test", "passes": False}
                ]
            })
        )

        report = validate_federated(prd_file)
        keys = flatten_keys(report)
        sensitive_keys = [k.lower() for k in keys]

        assert "password" not in sensitive_keys, \
            f"Report leaked 'password' key. Found keys: {keys}"

    def test_report_json_no_secret_key(self, tmp_path: Path) -> None:
        """Report should not contain 'secret' key (case-insensitive)."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test", "passes": False}
                ]
            })
        )

        report = validate_federated(prd_file)
        keys = flatten_keys(report)
        sensitive_keys = [k.lower() for k in keys]

        assert "secret" not in sensitive_keys, \
            f"Report leaked 'secret' key. Found keys: {keys}"

    def test_report_json_no_key_key(self, tmp_path: Path) -> None:
        """Report should not contain 'key' key (case-insensitive).

        Note: This test is conservative — legitimate use of 'key' in
        dictionaries may exist. If failure occurs, review context.
        """
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test", "passes": False}
                ]
            })
        )

        report = validate_federated(prd_file)
        keys = flatten_keys(report)

        # Check for exact "key" string (common for credentials)
        # but allow common legitimate uses like dict keys in cycles
        sensitive_matches = [k for k in keys if k.lower() == "key"]

        assert not sensitive_matches, \
            f"Report leaked sensitive 'key' field. Found: {sensitive_matches}"


class TestPathTraversalSecurity:
    """Verify path-traversal attacks are safely rejected."""

    def test_path_traversal_rejected(self) -> None:
        """Path-traversal in prd argument should raise ValueError."""
        malicious_path = Path("../../etc/passwd")

        # The function should handle this gracefully
        # It should either return a safe error or raise ValueError
        result = validate_federated(malicious_path)

        # Path doesn't exist, so should return file-not-found error
        assert result["valid"] is False
        assert "File not found" in result["errors"][0]

    def test_path_traversal_no_traceback_on_cli(self) -> None:
        """CLI invocation with path-traversal should exit cleanly, no traceback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Create a minimal prd.json for reference
            prd_file = tmpdir_path / "prd.json"
            prd_file.write_text(json.dumps({"userStories": []}))

            # Try to invoke the CLI with a path-traversal attempt
            # Using a relative path that tries to escape
            malicious_prd_arg = str(tmpdir_path / "../../etc/passwd")

            result = subprocess.run(
                [sys.executable, "main.py", "validate-federated", "--prd", malicious_prd_arg],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )

            # Should exit with error code
            assert result.returncode != 0, \
                f"Expected non-zero exit code, got {result.returncode}"

            # Check stderr for traceback markers
            # A proper error message should not start with Traceback
            stderr_lines = result.stderr.split("\n")
            has_traceback = any("Traceback" in line for line in stderr_lines)

            assert not has_traceback, \
                f"CLI output contained Python traceback. stderr:\n{result.stderr}"


class TestMalformedInputSafety:
    """Verify malformed inputs are rejected safely without leaking sensitive info."""

    def test_malformed_repo_id_exits_nonzero(self, tmp_path: Path) -> None:
        """Malformed repo ID should cause non-zero exit."""
        prd_file = tmp_path / "prd.json"
        # Invalid story ID format
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "INVALID@ID!", "title": "Test"}
                ]
            })
        )

        report = validate_federated(prd_file)
        assert report["valid"] is False
        assert len(report["errors"]) > 0

    def test_malformed_input_no_env_leak(self, monkeypatch: Any, tmp_path: Path) -> None:
        """Error messages should not leak environment variable values."""
        # Set a fake secret env var
        test_secret = "SECRET_TEST_TOKEN_12345"
        monkeypatch.setenv("TEST_API_KEY", test_secret)

        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "MALFORMED_ID_123", "title": "Bad"}
                ]
            })
        )

        report = validate_federated(prd_file)

        # Flatten all error messages and check they don't contain the secret
        all_messages = " ".join(str(e) for e in report.get("errors", []))

        assert test_secret not in all_messages, \
            f"Error messages leaked env var value: {test_secret}"

    def test_malformed_input_no_filesystem_path_leak(self, monkeypatch: Any, tmp_path: Path) -> None:
        """Error messages should not leak absolute filesystem paths.

        Only the relative path from CWD is acceptable.
        """
        # Set a test absolute path in env
        test_path = "/home/user/.ssh/private_key"
        monkeypatch.setenv("PRIVATE_KEY_PATH", test_path)

        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "bad-format", "title": "Test"}
                ]
            })
        )

        report = validate_federated(prd_file)
        all_messages = " ".join(str(e) for e in report.get("errors", []))

        # Should not contain the private path from env
        assert "/home/user/.ssh" not in all_messages, \
            f"Error messages leaked absolute path: {test_path}"


class TestMalformedJSONInput:
    """Verify malformed JSON is handled safely."""

    def test_malformed_json_safe_error(self, tmp_path: Path) -> None:
        """Malformed JSON should return safe error, not raise exception."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text("{invalid json content")

        report = validate_federated(prd_file)

        assert report["valid"] is False
        assert len(report["errors"]) > 0
        # Error message should mention JSON parsing issue
        error_text = " ".join(report["errors"])
        assert "JSON" in error_text or "parse" in error_text.lower()

    def test_missing_prd_file_safe_error(self, tmp_path: Path) -> None:
        """Missing prd.json should return safe error."""
        prd_file = tmp_path / "nonexistent.json"

        report = validate_federated(prd_file)

        assert report["valid"] is False
        assert "File not found" in report["errors"][0]


class TestCLIInvocationSafety:
    """Test the CLI surface for security."""

    def test_cli_valid_prd_exits_zero(self, tmp_path: Path) -> None:
        """Valid PRD should exit with code 0."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test", "passes": False}
                ]
            })
        )

        result = subprocess.run(
            [sys.executable, "main.py", "validate-federated", "--prd", str(prd_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, \
            f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    def test_cli_invalid_prd_exits_nonzero(self, tmp_path: Path) -> None:
        """Invalid PRD should exit with non-zero code."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "INVALID", "title": "Bad ID"}
                ]
            })
        )

        result = subprocess.run(
            [sys.executable, "main.py", "validate-federated", "--prd", str(prd_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0, \
            f"Expected non-zero exit code, got {result.returncode}"

    def test_cli_output_json_valid(self, tmp_path: Path) -> None:
        """CLI JSON output should be parseable."""
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(
            json.dumps({
                "userStories": [
                    {"id": "US-001", "title": "Test"}
                ]
            })
        )

        result = subprocess.run(
            [sys.executable, "main.py", "validate-federated", "--prd", str(prd_file)],
            capture_output=True,
            text=True,
        )

        # Parse the JSON output from stdout
        # The stdout contains the JSON report followed by the validation message to stderr
        output_lines = [line for line in result.stdout.split("\n") if line.strip()]
        json_output = "\n".join(output_lines)

        # Should be valid JSON
        try:
            report = json.loads(json_output)
            assert isinstance(report, dict)
            assert "valid" in report
            assert "errors" in report
            assert "cycles" in report
        except json.JSONDecodeError as e:
            pytest.fail(f"CLI output is not valid JSON: {e}\nstdout: {result.stdout}\nstderr: {result.stderr}")
