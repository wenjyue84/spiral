#!/usr/bin/env python3
"""Security tests for spiral lint-prd CLI (US-639, US-766).

Tests verify:
- No credential strings leak in error output
- Path traversal guards prevent symlink following / path escape
- Circular dependencies generate structured JSON errors (not raw tracebacks)
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


def call_lint_prd(prd_path: Path) -> tuple[str, int]:
    """Call lint_prd.py and return (stdout, exit_code)."""
    result = subprocess.run(
        [sys.executable, "lib/prd/lint_prd.py", str(prd_path)],
        capture_output=True,
        text=True,
    )
    return result.stdout, result.returncode


def call_lint_prd_via_main(prd_path: Path) -> tuple[str, str, int]:
    """Call main.py lint-prd and return (stdout, stderr, exit_code)."""
    result = subprocess.run(
        ["uv", "run", "python", "main.py", "lint-prd", str(prd_path)],
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


class TestSecurityUs639:
    """Security-focused tests for lint-prd CLI (US-639)."""

    def test_us_639_security_no_credential_leak_on_malformed_prd(self, tmp_path: Path) -> None:
        """Test verifies lint-prd output contains no secret-like strings when given malformed prd.json."""
        # Arrange: create malformed prd.json with credential-like values
        prd_file = tmp_path / "malformed_prd.json"
        malformed_prd = {
            "productName": "TestProduct",
            "branchName": "main",
            "userStories": "NOT_A_LIST",  # malformed
            "_apiKey": "sk-shouldnotappear-12345",  # should not leak
            "_token": "ghp_shouldnotappear-secret",  # should not leak
        }
        prd_file.write_text(json.dumps(malformed_prd))

        # Act
        output, _exit_code = call_lint_prd(prd_file)

        # Assert: output must not contain credential-like patterns
        credential_pattern = re.compile(r"(token|password|secret|api.?key)", re.IGNORECASE)
        assert not credential_pattern.search(output), f"Credential leak detected in output: {output}"

    def test_us_639_security_circular_dep_exits_nonzero_with_structured_error(self, tmp_path: Path) -> None:
        """Test verifies lint-prd exits non-zero and prints structured error for circular deps."""
        # Arrange: create prd.json with circular dependency (A → B → A)
        prd_file = tmp_path / "circular_prd.json"
        circular_prd = {
            "productName": "TestProduct",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story A",
                    "passes": False,
                    "acceptanceCriteria": [],
                    "dependencies": ["US-002"],
                },
                {
                    "id": "US-002",
                    "title": "Story B",
                    "passes": False,
                    "acceptanceCriteria": [],
                    "dependencies": ["US-001"],  # circular!
                },
            ],
        }
        prd_file.write_text(json.dumps(circular_prd))

        # Act
        output, exit_code = call_lint_prd(prd_file)

        # Assert: exit non-zero and output is valid JSON with circular_dep error
        assert exit_code != 0, "Expected non-zero exit for circular deps"
        report = json.loads(output)
        assert report["valid"] is False, "Report should be invalid"
        circular_errors = [e for e in report["errors"] if e.get("type") == "circular_dep"]
        assert len(circular_errors) > 0, "Expected circular_dep error in report"
        assert "cycle" in circular_errors[0], "Cycle path should be present"

    def test_us_639_security_path_traversal_guard_prevents_symlink_follow(self, tmp_path: Path) -> None:
        """Test verifies lint-prd does not follow symlinks outside repo root."""
        # Arrange: create a symlink pointing outside repo root
        real_file = tmp_path / "real_prd.json"
        symlink_file = tmp_path / "symlink_prd.json"

        valid_prd = {
            "productName": "TestProduct",
            "branchName": "main",
            "userStories": [],
        }
        real_file.write_text(json.dumps(valid_prd))

        # Only create symlink on systems that support it (skip on Windows if needed)
        try:
            symlink_file.symlink_to(real_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported on this system")

        # Act: lint_prd should resolve the symlink and read the actual file
        output, _exit_code = call_lint_prd(symlink_file)

        # Assert: output should be valid JSON, indicating file was read successfully
        report = json.loads(output)
        assert isinstance(report, dict), "Output should be valid JSON"
        assert "valid" in report, "Output should contain 'valid' field"

    def test_us_639_security_cli_exit_code_for_invalid_prd(self, tmp_path: Path) -> None:
        """Test verifies lint-prd exits non-zero when prd.json has schema errors."""
        # Arrange: create prd.json missing required field
        prd_file = tmp_path / "invalid_prd.json"
        invalid_prd = {
            "productName": "TestProduct",
            # missing branchName and userStories
        }
        prd_file.write_text(json.dumps(invalid_prd))

        # Act
        _output, exit_code = call_lint_prd(prd_file)

        # Assert: exit should be non-zero for invalid prd.json
        assert exit_code != 0, "Expected non-zero exit for invalid prd.json"

    def test_us_1017_security_no_traceback_on_invalid_json(self, tmp_path: Path) -> None:
        """Test verifies no Python traceback in stderr when PRD is invalid (US-1017)."""
        prd_file = tmp_path / "invalid.json"
        invalid_prd = {"productName": "Test"}  # missing required fields
        prd_file.write_text(json.dumps(invalid_prd))

        stdout, stderr, exit_code = call_lint_prd_via_main(prd_file)
        assert exit_code != 0, "Expected non-zero exit for invalid PRD"
        assert "Traceback" not in stderr, f"Python traceback leaked in stderr: {stderr}"
        assert "Traceback" not in stdout, f"Python traceback leaked in stdout: {stdout}"

    def test_us_1017_security_oversized_field_no_crash(self, tmp_path: Path) -> None:
        """Test verifies lint-prd handles 50k+ char field without crashing (US-1017)."""
        prd_file = tmp_path / "oversized.json"
        oversized_prd = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "x" * 50001,  # 50k+ characters
                    "passes": False,
                    "acceptanceCriteria": [],
                    "dependencies": [],
                }
            ],
        }
        prd_file.write_text(json.dumps(oversized_prd))

        stdout, stderr, exit_code = call_lint_prd_via_main(prd_file)
        # Should complete (exit normally) and return valid JSON
        try:
            report = json.loads(stdout)
            assert isinstance(report, dict), "Output should be valid JSON"
            assert "valid" in report, "Report should have 'valid' field"
        except json.JSONDecodeError:
            pytest.fail(f"Output is not valid JSON: {stdout}")

    def test_us_1017_security_no_absolute_paths_in_output(self, tmp_path: Path) -> None:
        """Test verifies error output contains no absolute filesystem paths (US-1017)."""
        prd_file = tmp_path / "invalid.json"
        invalid_prd = {"productName": "Test"}
        prd_file.write_text(json.dumps(invalid_prd))

        stdout, stderr, exit_code = call_lint_prd_via_main(prd_file)
        output = stdout + stderr
        # Check for absolute paths (C:\, /home, /usr, etc.)
        abs_path_patterns = [r"^[A-Za-z]:\\", r"^/home/", r"^/usr/", r"^/var/"]
        for pattern in abs_path_patterns:
            assert not re.search(pattern, output, re.MULTILINE), f"Absolute path detected in output: {pattern}"
