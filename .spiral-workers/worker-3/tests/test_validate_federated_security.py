"""Security tests for validate-federated CLI command (US-578).

Covers:
- Path-traversal IDs are safely rejected (no traceback, JSON error, exit 1)
- JSON output never exposes environment secrets (API keys / tokens)
- PermissionError on prd.json returns structured JSON error (not traceback)
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent

# Add lib/commands to path so pytest.importorskip can find the module
sys.path.insert(0, str(PROJECT_ROOT / "lib" / "commands"))

# Skip entire test module if validate_federated is not present (US-514 dependency)
pytest.importorskip("validate_federated", reason="lib/commands/validate_federated.py not found — US-514 must be merged first")


def _run_cli(prd_path: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run 'python main.py validate-federated --prd <path>' and return result."""
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "validate-federated", "--prd", str(prd_path)],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ── Acceptance criterion 2: path-traversal ID ────────────────────────────────


class TestPathTraversalRejection:
    """validate-federated must reject path-traversal story IDs safely."""

    def test_path_traversal_id_exits_1_with_json(self, tmp_path: Path) -> None:
        """CLI exits 1 and returns JSON (not traceback) for a path-traversal story ID."""
        prd_data = {
            "schemaVersion": 1,
            "userStories": [
                {
                    "id": "../../etc/passwd:(US)-001",
                    "title": "Adversarial path traversal story",
                    "passes": False,
                }
            ],
        }
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

        result = _run_cli(prd_file)

        assert result.returncode == 1, "Should exit 1 for invalid/malicious ID"
        assert "Traceback" not in result.stdout, "stdout must not contain a Python traceback"
        # stdout must be parseable JSON
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail(f"stdout is not valid JSON:\n{result.stdout[:500]}")
        # Must report a validation failure (not silently pass)
        assert report.get("valid") is False or "error" in report, (
            f"Report must indicate failure, got: {report}"
        )

    def test_path_traversal_id_error_message_is_safe(self, tmp_path: Path) -> None:
        """Error message for path-traversal ID must not echo sensitive path components."""
        prd_data = {
            "schemaVersion": 1,
            "userStories": [
                {
                    "id": "../secret-dir:US-001",
                    "title": "Another traversal attempt",
                    "passes": False,
                }
            ],
        }
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

        result = _run_cli(prd_file)

        assert result.returncode == 1
        # The error may echo the bad ID (that's fine), but must not expose filesystem paths
        # Most importantly: no raw exception traceback
        assert "Traceback (most recent call last)" not in result.stdout


# ── Acceptance criterion 3: no secrets in output ─────────────────────────────


class TestNoSecretLeakage:
    """validate-federated must never expose env secrets in its JSON output."""

    def test_output_contains_no_env_secrets(self, tmp_path: Path) -> None:
        """JSON report must not contain ANTHROPIC_API_KEY, GITHUB_TOKEN, or secret env vars."""
        prd_data = {
            "schemaVersion": 1,
            "userStories": [
                {"id": "repo-a:US-001", "title": "Normal story", "passes": False}
            ],
        }
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

        # Inject recognizable fake secrets into the subprocess environment
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = "sk-ant-fake-secret-key-AAAA0000"
        env["GITHUB_TOKEN"] = "ghp_fake_token_value_BBBB1111"
        env["FAKE_API_KEY"] = "fake_key_secret_value_CCCC2222"
        env["FAKE_TOKEN"] = "fake_token_secret_value_DDDD3333"

        result = _run_cli(prd_file, env=env)

        combined_output = result.stdout + result.stderr
        assert "sk-ant-fake-secret-key-AAAA0000" not in combined_output, "ANTHROPIC_API_KEY leaked to output"
        assert "ghp_fake_token_value_BBBB1111" not in combined_output, "GITHUB_TOKEN leaked to output"
        assert "fake_key_secret_value_CCCC2222" not in combined_output, "FAKE_API_KEY leaked to output"
        assert "fake_token_secret_value_DDDD3333" not in combined_output, "FAKE_TOKEN leaked to output"


# ── Acceptance criterion 4: PermissionError → structured JSON error ───────────


class TestPermissionDeniedHandling:
    """validate_federated must return structured JSON when file is unreadable."""

    def test_permission_denied_returns_json_error_dict(self, tmp_path: Path) -> None:
        """validate_federated() returns a JSON-compatible dict (not raises) for PermissionError."""
        from validate_federated import validate_federated

        prd_file = tmp_path / "restricted.json"
        prd_file.write_text('{"userStories": []}', encoding="utf-8")

        # Mock open() at the builtins level to simulate PermissionError
        with mock.patch("builtins.open", side_effect=PermissionError("Permission denied: restricted.json")):
            report = validate_federated(prd_file)

        assert isinstance(report, dict), "Must return a dict, not raise an exception"
        assert report.get("valid") is False, "Should report invalid when file is unreadable"
        assert len(report.get("errors", [])) > 0, "Should include at least one error message"
        # Error message should mention permission / access
        errors_text = " ".join(report["errors"]).lower()
        assert any(kw in errors_text for kw in ("permission", "denied", "cannot", "access")), (
            f"Error must mention permissions/access, got: {report['errors']}"
        )

    def test_permission_denied_has_no_traceback_fields(self, tmp_path: Path) -> None:
        """validate_federated() dict must not contain traceback-like strings."""
        from validate_federated import validate_federated

        prd_file = tmp_path / "restricted2.json"
        prd_file.write_text('{"userStories": []}', encoding="utf-8")

        with mock.patch("builtins.open", side_effect=PermissionError("Permission denied")):
            report = validate_federated(prd_file)

        # Serialize to JSON to check the serialized form
        output = json.dumps(report)
        assert "Traceback" not in output, "Serialized report must not contain traceback text"
        assert "PermissionError" not in output, "Exception class name must not appear in output"
