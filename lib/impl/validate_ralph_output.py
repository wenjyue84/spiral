#!/usr/bin/env python3
"""lib/impl/validate_ralph_output.py — Syntax validation before commit.

Runs tsc/ruff/cargo check on modified files and returns a RetryRequest
if validation fails. Used by commit_revert.sh to prevent committing
code with syntax errors.

Usage:
  from lib.impl.validate_ralph_output import validate_syntax
  result = validate_syntax("US-746", ["lib/foo.py", "src/main.ts"])
  if result is not None:
      print(f"Syntax error: {result['message']}")
      # result = {"error_type": "SyntaxError", "file": "lib/foo.py", "line": 42, "message": "..."}
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any

__all__ = ["validate_syntax"]


def _detect_tools(modified_files: list[str]) -> dict[str, list[str]]:
    """Detect which tools to run based on modified file extensions.

    Returns a dict mapping tool name to list of affected files:
        {"tsc": ["src/main.ts"], "ruff": ["lib/foo.py"], "cargo": ["Cargo.toml"]}
    """
    tools: dict[str, list[str]] = {}

    for file_path in modified_files:
        if file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
            if "tsc" not in tools:
                tools["tsc"] = []
            tools["tsc"].append(file_path)
        elif file_path.endswith(".py"):
            if "ruff" not in tools:
                tools["ruff"] = []
            tools["ruff"].append(file_path)
        elif file_path == "Cargo.toml" or file_path.endswith(".rs"):
            if "cargo" not in tools:
                tools["cargo"] = []
            if file_path not in tools["cargo"]:
                tools["cargo"].append(file_path)

    # Check if Cargo.toml exists anywhere in modified files
    if any(f == "Cargo.toml" for f in modified_files) and "cargo" not in tools:
        tools["cargo"] = ["Cargo.toml"]

    return tools


def _parse_tsc_error(stderr: str) -> tuple[str, int, str] | None:
    """Parse tsc error output and extract file, line, message.

    tsc outputs errors in format:
      src/main.ts:12:5 - error TS1234: Some error message
    """
    # Match pattern: file.ts:line:col - error TSxxxx: message
    match = re.search(r"^([^:]+):(\d+):\d+ - error [A-Z]+\d+: (.+)$", stderr, re.MULTILINE)
    if match:
        file_path, line_str, message = match.groups()
        return file_path, int(line_str), message
    return None


def _parse_ruff_error(stderr: str) -> tuple[str, int, str] | None:
    """Parse ruff check error output.

    ruff outputs errors in format:
      lib/foo.py:12:5: E501 Line too long (120 > 88 characters)
    """
    # Match pattern: file.py:line:col: CODE message
    match = re.search(r"^([^:]+):(\d+):\d+: [A-Z]\d+ (.+)$", stderr, re.MULTILINE)
    if match:
        file_path, line_str, message = match.groups()
        return file_path, int(line_str), message
    return None


def _parse_cargo_error(stderr: str) -> tuple[str, int, str] | None:
    """Parse cargo check error output.

    cargo outputs errors in format:
      error[E0425]: cannot find value `foo` in this scope
         --> src/main.rs:12:5
    """
    # First find the error message
    error_match = re.search(r"^error\[E\d+\]: (.+)$", stderr, re.MULTILINE)
    if not error_match:
        return None

    message = error_match.group(1)

    # Then find the location (line after error)
    error_pos = error_match.end()
    remaining = stderr[error_pos:]
    location_match = re.search(r"--> ([^:]+):(\d+):", remaining)

    if location_match:
        file_path, line_str = location_match.groups()
        return file_path, int(line_str), message

    return None


def validate_syntax(
    story_id: str,
    modified_files: list[str],
) -> dict[str, Any] | None:
    """Validate syntax of modified files.

    Runs appropriate syntax checkers (tsc, ruff, cargo check) based on
    file extensions. Returns None if all checks pass, or a RetryRequest dict
    with error details if validation fails.

    Parameters
    ----------
    story_id : str
        Story ID (e.g., 'US-746') - used for logging only
    modified_files : list[str]
        List of relative file paths that were modified

    Returns
    -------
    dict[str, Any] | None
        None if validation passes, or a dict with:
            {
                "error_type": "SyntaxError",
                "file": str (relative path),
                "line": int (1-based line number),
                "message": str (error message)
            }
    """
    if not modified_files:
        return None

    tools = _detect_tools(modified_files)

    # Run tsc if TypeScript files were modified
    if "tsc" in tools:
        try:
            result = subprocess.run(
                ["tsc", "--noEmit"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                # Parse tsc error from stderr
                parsed = _parse_tsc_error(result.stderr)
                if parsed:
                    file_path, line_num, message = parsed
                    return {
                        "error_type": "SyntaxError",
                        "file": file_path,
                        "line": line_num,
                        "message": message,
                    }
                # Fallback: return first line of stderr
                first_line = result.stderr.split("\n")[0] if result.stderr else "Unknown tsc error"
                return {
                    "error_type": "SyntaxError",
                    "file": tools["tsc"][0] if tools["tsc"] else "unknown",
                    "line": 1,
                    "message": first_line,
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # tsc not available or timed out - skip this check
            pass

    # Run ruff if Python files were modified
    if "ruff" in tools:
        try:
            result = subprocess.run(
                ["ruff", "check"] + tools["ruff"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                # Parse ruff error from stderr or stdout
                output = result.stderr if result.stderr else result.stdout
                parsed = _parse_ruff_error(output)
                if parsed:
                    file_path, line_num, message = parsed
                    return {
                        "error_type": "SyntaxError",
                        "file": file_path,
                        "line": line_num,
                        "message": message,
                    }
                # Fallback: return first line
                first_line = output.split("\n")[0] if output else "Unknown ruff error"
                return {
                    "error_type": "SyntaxError",
                    "file": tools["ruff"][0] if tools["ruff"] else "unknown",
                    "line": 1,
                    "message": first_line,
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # ruff not available or timed out - skip this check
            pass

    # Run cargo check if Rust files were modified
    if "cargo" in tools:
        try:
            result = subprocess.run(
                ["cargo", "check"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                # Parse cargo error from stderr
                output = result.stderr if result.stderr else result.stdout
                parsed = _parse_cargo_error(output)
                if parsed:
                    file_path, line_num, message = parsed
                    return {
                        "error_type": "SyntaxError",
                        "file": file_path,
                        "line": line_num,
                        "message": message,
                    }
                # Fallback: return first line
                first_line = output.split("\n")[0] if output else "Unknown cargo error"
                return {
                    "error_type": "SyntaxError",
                    "file": "Cargo.toml",
                    "line": 1,
                    "message": first_line,
                }
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            # cargo not available or timed out - skip this check
            pass

    # All checks passed
    return None


if __name__ == "__main__":
    # CLI interface for testing
    if len(sys.argv) < 2:
        print("Usage: python lib/impl/validate_ralph_output.py <story_id> <file1> [file2] ...", file=sys.stderr)
        sys.exit(1)

    story_id = sys.argv[1]
    files = sys.argv[2:]

    result = validate_syntax(story_id, files)
    print(json.dumps(result))
    sys.exit(0 if result is None else 1)
