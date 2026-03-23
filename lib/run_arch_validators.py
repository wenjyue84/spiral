#!/usr/bin/env python3
"""lib/run_arch_validators.py — CLI runner for arch validators in Phase V.

Reads SPIRAL_ARCH_VALIDATORS env var, builds CodeDiff from git diff,
runs all validators, and outputs JSON to stdout.

Exit code: 0 = all validators passed, 1 = violations found or error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _get_repo_root() -> str:
    """Return the git repository root (falls back to cwd)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return os.getcwd()


def _get_diff_file_info(repo_root: str) -> list[dict[str, object]]:
    """Return list of {path, is_new} dicts for files changed vs HEAD~1."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--name-status"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0 or not result.stdout.strip():
            # Fallback: all tracked files (e.g. single-commit repo)
            ls = subprocess.run(
                ["git", "ls-files"],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            return [
                {"path": line.strip(), "is_new": False}
                for line in ls.stdout.splitlines()
                if line.strip()
            ]
        files: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, path = parts
            files.append({"path": path.strip(), "is_new": status.startswith("A")})
        return files
    except Exception:
        return []


def build_code_diff(repo_root: str) -> object:
    """Build a CodeDiff from the current git state."""
    lib_path = os.path.dirname(os.path.abspath(__file__))
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from arch_validators import CodeDiff, DiffFile

    raw_files = _get_diff_file_info(repo_root)
    diff_files: list[DiffFile] = []

    for f_info in raw_files:
        path = str(f_info["path"])
        abs_path = os.path.join(repo_root, path)
        try:
            size_bytes = os.path.getsize(abs_path)
        except OSError:
            size_bytes = 0

        content = ""
        if path.endswith(".py"):
            try:
                content = Path(abs_path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass

        diff_files.append(
            DiffFile(
                path=path,
                size_bytes=size_bytes,
                content=content,
                is_new=bool(f_info["is_new"]),
            )
        )

    return CodeDiff(files=diff_files, repo_root=repo_root)


def main() -> int:
    lib_path = os.path.dirname(os.path.abspath(__file__))
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    from arch_validators import load_validators

    validators_str = os.environ.get("SPIRAL_ARCH_VALIDATORS", "")
    if not validators_str.strip():
        out = {
            "arch_validation_failed": False,
            "violations": [],
            "message": "No arch validators configured",
        }
        print(json.dumps(out))
        return 0

    try:
        validators = load_validators(validators_str)
    except ValueError as exc:
        out = {
            "arch_validation_failed": True,
            "violations": [],
            "message": str(exc),
        }
        print(json.dumps(out))
        return 1

    repo_root = _get_repo_root()
    code_diff = build_code_diff(repo_root)

    all_violations: list[dict[str, str]] = []
    for validator in validators:
        for v in validator.validate(code_diff):
            all_violations.append(
                {
                    "validator": v.validator,
                    "file_path": v.file_path,
                    "message": v.message,
                    "violation_type": v.violation_type,
                }
            )

    failed = len(all_violations) > 0
    out = {
        "arch_validation_failed": failed,
        "violations": all_violations,
        "message": (
            f"{len(all_violations)} violation(s) found"
            if failed
            else "All validators passed"
        ),
    }
    print(json.dumps(out))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
