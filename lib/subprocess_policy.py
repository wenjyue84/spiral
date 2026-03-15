"""lib/subprocess_policy.py — Python subprocess security policy for SPIRAL (US-265).

Enforces shell=False and per-phase command allowlists for all subprocess calls
made by SPIRAL Python modules, preventing command injection via LLM-generated
strings.

Usage::

    from lib.subprocess_policy import safe_run, PHASE_COMMAND_ALLOWLIST

    # Phase I: runs only if 'git' is in the Phase I allowlist
    result = safe_run(["git", "commit", "-m", msg], phase="I",
                      capture_output=True, text=True)

    # Phase R: blocks commands not in allowlist; logs violation to security-audit.jsonl
    result = safe_run(["curl", url], phase="R",
                      capture_output=True, text=True)

SubprocessPolicyViolation is raised (and the event is logged) when the
executable is not permitted in the given phase.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Per-phase command allowlist
# ---------------------------------------------------------------------------
# Maps phase name → frozenset of permitted executable names.
# The executable is the first element of the command list.
#
# Phase I allows core dev tools (git, python, node, npm) but explicitly
# excludes network-fetch tools (curl, wget) and raw shells (bash, sh) that
# an LLM-generated string could abuse for exfiltration or further injection.

PHASE_COMMAND_ALLOWLIST: dict[str, frozenset[str]] = {
    # Research phase — fetching is expected here
    "R": frozenset([
        "curl", "wget", "python", "python3", "uv", "cat", "ls",
        "jq", "head", "tail", "grep", "find", "echo", "printf",
        "wc", "sort", "uniq", "git",
    ]),
    # Implementation phase — build/test tools only; no network fetch or raw shell
    "I": frozenset([
        "git", "python", "python3", "uv", "node", "npm", "npx",
        "cargo", "make", "cat", "ls", "head", "tail", "grep",
        "find", "echo", "printf", "cp", "mv", "mkdir", "touch", "wc", "sort",
    ]),
    # Validation phase — test runners
    "V": frozenset([
        "python", "python3", "uv", "pytest", "npm", "npx",
        "bats", "cargo", "node", "cat", "ls", "grep", "echo", "printf",
    ]),
    # Merge phase — git operations only
    "M": frozenset([
        "git", "echo", "cat", "ls", "jq",
    ]),
    # Gate / check done phase
    "C": frozenset([
        "python", "python3", "uv", "git", "cat", "ls", "echo", "jq",
    ]),
    # Fallback: used when no phase is specified
    "global": frozenset([
        "git", "python", "python3", "uv", "node", "npm", "npx",
        "cat", "ls", "echo", "printf", "grep", "find", "head", "tail",
        "jq", "wc", "sort", "uniq", "curl", "wget",
    ]),
}

# ---------------------------------------------------------------------------
# Security audit log
# ---------------------------------------------------------------------------
_AUDIT_LOG_LOCK = threading.Lock()


def _security_audit_log_path() -> str:
    scratch = os.environ.get("SPIRAL_SCRATCH_DIR", ".spiral")
    return os.path.join(scratch, "security-audit.jsonl")


def _log_violation(executable: str, phase: str, cmd: list[str]) -> None:
    """Append a SubprocessPolicyViolation event to security-audit.jsonl."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "SubprocessPolicyViolation",
        "phase": phase,
        "blocked_executable": executable,
        "full_command": cmd,
    }
    log_path = _security_audit_log_path()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        with _AUDIT_LOG_LOCK:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Never crash the caller over audit-log I/O


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class SubprocessPolicyViolation(RuntimeError):
    """Raised when a subprocess call violates the per-phase command allowlist."""

    def __init__(self, executable: str, phase: str, cmd: list[str]) -> None:
        self.executable = executable
        self.phase = phase
        self.cmd = cmd
        super().__init__(
            f"[subprocess_policy] BLOCKED: executable '{executable}' is not "
            f"permitted in phase '{phase}'. Command: {cmd}"
        )


# ---------------------------------------------------------------------------
# Core enforcement function
# ---------------------------------------------------------------------------

def _resolve_allowlist(phase: str) -> frozenset[str]:
    """Return the allowlist for *phase*, falling back to 'global'."""
    return PHASE_COMMAND_ALLOWLIST.get(phase, PHASE_COMMAND_ALLOWLIST["global"])


def check_command(cmd: list[str], phase: str = "global") -> None:
    """Validate *cmd* against the allowlist for *phase*.

    Raises SubprocessPolicyViolation (and logs to security-audit.jsonl) if
    the executable (``cmd[0]``) is not in the phase allowlist.

    Arguments are always passed through as-is (shell metacharacters are treated
    as literal strings because shell=False is used).
    """
    if not cmd:
        raise ValueError("cmd must be a non-empty list")
    executable = os.path.basename(cmd[0])  # strip path prefix for matching
    allowed = _resolve_allowlist(phase)
    if executable not in allowed:
        _log_violation(executable, phase, cmd)
        raise SubprocessPolicyViolation(executable, phase, cmd)


def safe_run(
    cmd: list[str],
    phase: str = "global",
    **kwargs: Any,
) -> "subprocess.CompletedProcess[Any]":
    """subprocess.run() wrapper that enforces shell=False and the phase allowlist.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments as a list (never a string).
    phase : str
        SPIRAL phase name (R, I, V, M, C, global).
    **kwargs
        Forwarded to subprocess.run().  The ``shell`` keyword is silently
        forced to ``False`` regardless of what the caller passes.

    Raises
    ------
    SubprocessPolicyViolation
        If the executable is not permitted in *phase*.
    """
    if not isinstance(cmd, list):
        raise TypeError(
            f"safe_run requires cmd as a list, got {type(cmd).__name__}. "
            "Never pass a shell string to avoid command injection."
        )
    # Always enforce shell=False regardless of what the caller passed
    kwargs["shell"] = False

    check_command(cmd, phase)
    return subprocess.run(cmd, **kwargs)
