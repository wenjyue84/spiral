#!/usr/bin/env python3
"""mypy_to_github_annotations.py — Convert mypy --output json to GitHub Actions annotations.

Reads mypy JSON output from stdin and emits GitHub Actions workflow commands
(::error::, ::warning::) that create inline PR annotations.

Usage:
    uv run mypy lib/ --strict --output json | uv run python lib/mypy_to_github_annotations.py

Exit code mirrors the number of errors found (0 = clean).
"""
import json
import sys
from typing import Any


def severity_cmd(severity: str) -> str:
    """Map mypy severity to GitHub Actions annotation level."""
    if severity == "error":
        return "error"
    if severity == "warning":
        return "warning"
    return "notice"


def emit_annotation(msg: dict[str, Any]) -> None:
    """Print a single GitHub Actions annotation command."""
    level = severity_cmd(msg.get("severity", "error"))
    file_path = msg.get("file", "")
    line = msg.get("line", 1)
    col = msg.get("column", 1)
    message = msg.get("message", "")
    code = msg.get("code", "")
    hint = f" [{code}]" if code else ""
    # GitHub annotation format: ::level file=FILE,line=LINE,col=COL::MESSAGE
    print(f"::{level} file={file_path},line={line},col={col}::{message}{hint}")


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 0

    error_count = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # mypy may emit non-JSON lines (e.g. summary) — skip them
            continue
        emit_annotation(msg)
        if msg.get("severity") == "error":
            error_count += 1

    return error_count


if __name__ == "__main__":
    sys.exit(main())
