#!/usr/bin/env python3
"""SPIRAL — sanitize_output.py

Sanitize LLM-generated file content before writing to disk.

Guards against indirect prompt injection attacks where a compromised upstream
package or injected web content fetched during Phase R causes Claude to emit:
  - ANSI escape sequences / control characters (terminal hijack)
  - Null bytes (binary injection)
  - Path traversal sequences (escape worktree sandbox)
  - Git hook / .git/ directory writes (CI/CD poisoning)
  - Unexpected executable files outside src/ and tests/ (malware drop)

Usage (library):
    from sanitize_output import sanitize_content, validate_write_path, safe_write_file

    clean = sanitize_content(raw_llm_content)
    validate_write_path("/repo/worktree/src/foo.py", "/repo/worktree")
    safe_write_file("/repo/worktree/src/foo.py", raw_llm_content, "/repo/worktree")

Usage (CLI):
    python lib/sanitize_output.py --check-path <path> --worktree <root>
    python lib/sanitize_output.py --sanitize-stdin --output <path> --worktree <root>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Sanitization constants ─────────────────────────────────────────────────────

# ANSI/VT100 escape sequence pattern (covers colour, cursor, title, OSC sequences)
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b          # ESC character
    (?:
        \[[0-9;?]*[A-Za-z]   # CSI sequences:  ESC [ ... <letter>
      | \][^\x07\x1b]*       # OSC sequences:  ESC ] ... (no BEL/ESC)
        (?:\x07|\x1b\\)?     #   terminated by BEL or ST
      | [PX^_][^\x1b]*\x1b\\ # DCS/SOS/PM/APC string sequences
      | [()][AB012]          # Charset designations
      | [DEHMNOVWXYZ\\]      # Single-char control functions
    )
""",
    re.VERBOSE,
)

# Executable file extensions that warrant extra scrutiny
_EXEC_EXTENSIONS = frozenset(
    {".sh", ".bash", ".zsh", ".fish", ".ps1", ".cmd", ".bat", ".py", ".rb", ".pl",
     ".js", ".mjs", ".cjs", ".ts", ".go", ".rs", ".c", ".cpp", ".cc"}
)

# Permitted top-level subdirs for executable writes without SPIRAL_ALLOW_EXEC_WRITES
_SAFE_EXEC_DIRS = ("src", "tests", "test", "lib", "scripts")

# Default audit log location (relative to worktree root or CWD)
_DEFAULT_AUDIT_LOG = ".spiral/security-audit.jsonl"


# ── Core sanitization ──────────────────────────────────────────────────────────


def sanitize_content(content: str) -> str:
    """Strip ANSI escape sequences and null bytes from *content*.

    This is a content-level sanitizer: it removes dangerous control characters
    while preserving the semantic meaning of the code.  Importantly, *string
    literals* that happen to contain ANSI codes (e.g. ``"\\x1b[32mGreen\\x1b[0m"``)
    are NOT touched because they appear as Python string escape sequences, not
    actual ESC bytes in the source text.

    Args:
        content: Raw LLM-generated file content.

    Returns:
        Sanitized content safe to write to disk.
    """
    if not content:
        return content

    # 1. Strip null bytes — binary injection guard
    content = content.replace("\x00", "")

    # 2. Strip actual ANSI/VT escape sequences (ESC bytes present in the raw text)
    content = _ANSI_ESCAPE_RE.sub("", content)

    return content


# ── Path validation ────────────────────────────────────────────────────────────


class PathViolation(Exception):
    """Raised when a write target violates worktree sandbox rules."""

    def __init__(self, message: str, violation_type: str, target: str, worktree_root: str) -> None:
        super().__init__(message)
        self.violation_type = violation_type
        self.target = target
        self.worktree_root = worktree_root


def validate_write_path(
    target_path: str | Path,
    worktree_root: str | Path,
    *,
    allow_exec_writes: bool = False,
    audit_log: Optional[str | Path] = None,
) -> Path:
    """Validate that *target_path* is a safe write destination.

    Checks performed (in order):
    1. Resolve both paths and assert target is under worktree_root.
    2. Block writes to any ``.git/`` subtree.
    3. Warn (or block) executable files written outside safe directories unless
       ``allow_exec_writes`` is True or ``SPIRAL_ALLOW_EXEC_WRITES=true`` env var.

    Args:
        target_path:    Destination path (absolute or relative to CWD).
        worktree_root:  Root of the story's git worktree.
        allow_exec_writes: Allow executable files anywhere in the worktree.
        audit_log:      Path to security-audit.jsonl; pass None to skip logging.

    Returns:
        Resolved absolute ``Path`` of the target (safe to write).

    Raises:
        PathViolation: If the path violates sandbox rules.
    """
    root = Path(os.path.realpath(worktree_root))
    target = Path(os.path.realpath(target_path))

    # ── 1. Path traversal ─────────────────────────────────────────────────────
    try:
        target.relative_to(root)
    except ValueError:
        msg = f"Path traversal blocked: {target} is outside worktree {root}"
        _audit(audit_log, "path_traversal_blocked", str(target), str(root), msg)
        raise PathViolation(msg, "path_traversal", str(target), str(root))

    # ── 2. .git/ directory writes ─────────────────────────────────────────────
    rel = target.relative_to(root)
    parts = rel.parts
    if parts and parts[0] == ".git":
        msg = f"Git directory write blocked: {target}"
        _audit(audit_log, "git_dir_write_blocked", str(target), str(root), msg)
        raise PathViolation(msg, "git_dir_write", str(target), str(root))

    # ── 3. Executable-file check ──────────────────────────────────────────────
    allow_exec = allow_exec_writes or os.environ.get("SPIRAL_ALLOW_EXEC_WRITES", "").lower() in (
        "1", "true", "yes",
    )
    if not allow_exec and target.suffix.lower() in _EXEC_EXTENSIONS:
        if not _in_safe_exec_dir(rel):
            msg = (
                f"Executable file write outside safe dirs blocked: {target} "
                f"(set SPIRAL_ALLOW_EXEC_WRITES=true to override)"
            )
            _audit(audit_log, "exec_write_blocked", str(target), str(root), msg)
            raise PathViolation(msg, "exec_write", str(target), str(root))

    return target


def _in_safe_exec_dir(rel: Path) -> bool:
    """Return True if *rel* (relative path) sits under a permitted exec dir."""
    if not rel.parts:
        return False
    # Allow if the *first* component is a safe dir, or if the file is at root
    # level (no subdirectory) and the dir has only one part.
    return rel.parts[0] in _SAFE_EXEC_DIRS


# ── Safe write ─────────────────────────────────────────────────────────────────


def safe_write_file(
    target_path: str | Path,
    content: str,
    worktree_root: str | Path,
    *,
    allow_exec_writes: bool = False,
    audit_log: Optional[str | Path] = None,
    encoding: str = "utf-8",
) -> Path:
    """Sanitize *content* and write it to *target_path* within *worktree_root*.

    This is the primary API for Phase I file writes.  It combines
    :func:`sanitize_content` and :func:`validate_write_path` into a single
    atomic operation:

    1. Validate the destination path (path traversal, .git/, exec check).
    2. Sanitize the content (strip ANSI codes and null bytes).
    3. Create parent directories as needed.
    4. Write the file atomically via a ``.tmp`` swap.

    Args:
        target_path:     Destination path.
        content:         Raw LLM-generated content to write.
        worktree_root:   Root of the story's git worktree.
        allow_exec_writes: Bypass executable-file restriction.
        audit_log:       Append security events here; None = skip.
        encoding:        File encoding (default utf-8).

    Returns:
        Resolved destination ``Path``.

    Raises:
        PathViolation: If any path/content check fails.
    """
    resolved = validate_write_path(
        target_path,
        worktree_root,
        allow_exec_writes=allow_exec_writes,
        audit_log=audit_log,
    )
    clean = sanitize_content(content)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    try:
        tmp.write_text(clean, encoding=encoding)
        os.replace(tmp, resolved)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    return resolved


# ── Audit logging ──────────────────────────────────────────────────────────────


def _audit(
    audit_log: Optional[str | Path],
    event: str,
    target: str,
    worktree_root: str,
    message: str,
) -> None:
    """Append a JSONL entry to *audit_log* (creates parent dirs as needed)."""
    if audit_log is None:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "target": target,
        "worktree_root": worktree_root,
        "message": message,
        "epoch": int(time.time()),
    }
    log_path = Path(audit_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sanitize LLM output and validate write paths for SPIRAL workers."
    )
    sub = p.add_subparsers(dest="cmd")

    # --- check-path subcommand ---
    cp = sub.add_parser("check-path", help="Validate a target write path.")
    cp.add_argument("--path", required=True, help="Target file path to validate")
    cp.add_argument("--worktree", required=True, help="Worktree root directory")
    cp.add_argument(
        "--allow-exec-writes",
        action="store_true",
        help="Allow executable files outside src/ and tests/",
    )
    cp.add_argument(
        "--audit-log",
        default=_DEFAULT_AUDIT_LOG,
        help=f"Security audit log path (default: {_DEFAULT_AUDIT_LOG})",
    )

    # --- sanitize subcommand ---
    s = sub.add_parser("sanitize", help="Sanitize stdin content and write to a file.")
    s.add_argument("--output", required=True, help="Output file path")
    s.add_argument("--worktree", required=True, help="Worktree root directory")
    s.add_argument(
        "--allow-exec-writes",
        action="store_true",
        help="Allow executable files outside src/ and tests/",
    )
    s.add_argument(
        "--audit-log",
        default=_DEFAULT_AUDIT_LOG,
        help=f"Security audit log path (default: {_DEFAULT_AUDIT_LOG})",
    )

    return p


def main() -> None:
    args = _build_parser().parse_args()

    if args.cmd == "check-path":
        try:
            resolved = validate_write_path(
                args.path,
                args.worktree,
                allow_exec_writes=args.allow_exec_writes,
                audit_log=args.audit_log,
            )
            print(f"  [sanitize] OK: {resolved}", file=sys.stderr)
        except PathViolation as exc:
            print(f"  [sanitize] BLOCKED ({exc.violation_type}): {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "sanitize":
        content = sys.stdin.read()
        try:
            resolved = safe_write_file(
                args.output,
                content,
                args.worktree,
                allow_exec_writes=args.allow_exec_writes,
                audit_log=args.audit_log,
            )
            print(f"  [sanitize] Written: {resolved}", file=sys.stderr)
        except PathViolation as exc:
            print(f"  [sanitize] BLOCKED ({exc.violation_type}): {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        _build_parser().print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
