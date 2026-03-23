#!/usr/bin/env python3
"""preflight.py — Validate SPIRAL runtime dependencies and configuration.

Usage:
    python -m lib.spiral.preflight [--spiral-home DIR] [--prd FILE]

Checks constitution.md, prd.json schema, spiral.config.sh required vars,
system tool versions (bash, node, python3, docker, jq), and directory
writability for .spiral/ and .spiral-workers/.

Exit code 0 when all checks pass, 1 when any check fails.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


class CheckResult(TypedDict):
    """Single preflight check result."""

    check_name: str
    status: str  # "pass" or "fail"
    remediation: str


def _check_constitution(spiral_home: Path) -> CheckResult:
    """Verify constitution.md exists."""
    constitution = spiral_home / ".specify" / "memory" / "constitution.md"
    # Also accept plain constitution.md in spiral_home
    if not constitution.exists():
        constitution = spiral_home / "constitution.md"
    if constitution.exists():
        return {
            "check_name": "constitution_exists",
            "status": "pass",
            "remediation": "",
        }
    return {
        "check_name": "constitution_exists",
        "status": "fail",
        "remediation": (
            "Create .specify/memory/constitution.md with non-negotiable quality standards. "
            "Run 'bash spiral.sh 1 --gate interactive' to create it interactively."
        ),
    }


def _check_prd_schema(spiral_home: Path, prd_path: Path) -> CheckResult:
    """Validate prd.json conforms to schema."""
    if not prd_path.is_absolute():
        prd_path = spiral_home / prd_path
    if not prd_path.exists():
        return {
            "check_name": "prd_schema_valid",
            "status": "fail",
            "remediation": f"Create {prd_path} using 'python main.py init' or copy templates/prd.example.json.",
        }
    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as exc:
        return {
            "check_name": "prd_schema_valid",
            "status": "fail",
            "remediation": f"Fix JSON syntax error in {prd_path}: {exc}",
        }

    sys.path.insert(0, str(spiral_home / "lib"))
    try:
        from prd.prd_schema import validate_prd

        errors = validate_prd(prd)
    except Exception as exc:  # noqa: BLE001
        return {
            "check_name": "prd_schema_valid",
            "status": "fail",
            "remediation": f"Could not run schema validator: {exc}",
        }

    if errors:
        joined = "; ".join(errors[:3])
        return {
            "check_name": "prd_schema_valid",
            "status": "fail",
            "remediation": f"Fix prd.json schema errors: {joined}",
        }
    return {"check_name": "prd_schema_valid", "status": "pass", "remediation": ""}


def _check_config_var(config_path: Path, var_name: str) -> CheckResult:
    """Check that spiral.config.sh exports a specific variable."""
    check_name = f"config_{var_name.lower()}_set"
    if not config_path.exists():
        return {
            "check_name": check_name,
            "status": "fail",
            "remediation": (
                f"Create spiral.config.sh and define {var_name}. "
                "Copy templates/spiral.config.example.sh as a starting point."
            ),
        }
    content = config_path.read_text(encoding="utf-8", errors="replace")
    # Accept lines like: VAR=value, export VAR=value, VAR="value"
    pattern = rf"(?m)^(?:export\s+)?{re.escape(var_name)}\s*="
    if re.search(pattern, content):
        return {"check_name": check_name, "status": "pass", "remediation": ""}
    return {
        "check_name": check_name,
        "status": "fail",
        "remediation": (
            f"Add '{var_name}=<value>' to spiral.config.sh. See templates/spiral.config.example.sh for examples."
        ),
    }


def _parse_version(output: str) -> tuple[int, ...]:
    """Extract first dotted version number from string."""
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", output)
    if not m:
        return (0,)
    return tuple(int(x) for x in m.groups() if x is not None)


def _check_tool_version(
    check_name: str,
    args: list[str],
    min_version: tuple[int, ...],
    remediation: str,
) -> CheckResult:
    """Run a command and check its version output meets minimum."""
    try:
        result = subprocess.run(  # noqa: S603
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = result.stdout + result.stderr
        version = _parse_version(output)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {
            "check_name": check_name,
            "status": "fail",
            "remediation": remediation,
        }

    if version >= min_version:
        return {"check_name": check_name, "status": "pass", "remediation": ""}
    got = ".".join(str(x) for x in version)
    need = ".".join(str(x) for x in min_version)
    return {
        "check_name": check_name,
        "status": "fail",
        "remediation": f"Found version {got}, need >= {need}. {remediation}",
    }


def _check_docker() -> CheckResult:
    """Check docker is available."""
    if shutil.which("docker") is None:
        return {
            "check_name": "docker_available",
            "status": "fail",
            "remediation": "Install Docker Desktop from https://www.docker.com/products/docker-desktop/",
        }
    try:
        r = subprocess.run(  # noqa: S603
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return {
                "check_name": "docker_available",
                "status": "fail",
                "remediation": "Docker daemon is not running. Start Docker Desktop.",
            }
    except subprocess.TimeoutExpired:
        return {
            "check_name": "docker_available",
            "status": "fail",
            "remediation": "Docker info timed out. Ensure Docker daemon is running.",
        }
    return {"check_name": "docker_available", "status": "pass", "remediation": ""}


def _check_jq(spiral_home: Path) -> CheckResult:
    """Check jq is available at ./ralph/jq.exe or in PATH."""
    bundled = spiral_home / "ralph" / "jq.exe"
    if bundled.exists():
        return {"check_name": "jq_available", "status": "pass", "remediation": ""}
    if shutil.which("jq") is not None:
        return {"check_name": "jq_available", "status": "pass", "remediation": ""}
    return {
        "check_name": "jq_available",
        "status": "fail",
        "remediation": (
            "Install jq: https://stedolan.github.io/jq/download/ or ensure ralph/jq.exe is present on Windows."
        ),
    }


def _check_dir_writable(path: Path, check_name: str) -> CheckResult:
    """Check that a directory is writable (creates it if absent)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".preflight_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return {"check_name": check_name, "status": "pass", "remediation": ""}
    except OSError as exc:
        return {
            "check_name": check_name,
            "status": "fail",
            "remediation": f"Directory {path} is not writable: {exc}. Check filesystem permissions.",
        }


def run_checks(
    spiral_home: Path | None = None,
    prd_path: Path | None = None,
) -> list[CheckResult]:
    """Run all preflight checks and return results.

    Args:
        spiral_home: Root directory of SPIRAL project (default: cwd).
        prd_path: Path to prd.json, relative to spiral_home (default: prd.json).

    Returns:
        List of CheckResult dicts with check_name, status, remediation.
    """
    if spiral_home is None:
        spiral_home = Path(os.getcwd())
    if prd_path is None:
        prd_path = Path("prd.json")

    config_path = spiral_home / "spiral.config.sh"
    results: list[CheckResult] = []

    # AC1: Config and schema checks
    results.append(_check_constitution(spiral_home))
    results.append(_check_prd_schema(spiral_home, prd_path))
    results.append(_check_config_var(config_path, "SPIRAL_VALIDATE_CMD"))
    results.append(_check_config_var(config_path, "SPIRAL_COST_CEILING"))

    # AC2: System tool version checks
    results.append(
        _check_tool_version(
            "bash_version_ge4",
            ["bash", "--version"],
            (4,),
            "Install bash >= 4. On macOS: brew install bash. On Windows: Git Bash >= 4.",
        )
    )
    results.append(
        _check_tool_version(
            "node_version_ge20",
            ["node", "--version"],
            (20,),
            "Install Node.js >= 20 from https://nodejs.org/",
        )
    )
    results.append(
        _check_tool_version(
            "python3_version_ge313",
            [sys.executable, "--version"],
            (3, 13),
            "Install Python >= 3.13 (via pyenv, uv, or https://python.org/downloads/)",
        )
    )
    results.append(_check_docker())
    results.append(_check_jq(spiral_home))

    # AC2: Directory writability
    results.append(_check_dir_writable(spiral_home / ".spiral", "spiral_dir_writable"))
    results.append(_check_dir_writable(spiral_home / ".spiral-workers", "spiral_workers_dir_writable"))

    return results


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns exit code 0 if all checks pass, 1 if any fail.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate SPIRAL runtime dependencies and configuration.",
    )
    parser.add_argument(
        "--spiral-home",
        default=".",
        metavar="DIR",
        help="SPIRAL project root directory (default: current directory)",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="FILE",
        help="Path to prd.json, relative to spiral-home (default: prd.json)",
    )
    args = parser.parse_args(argv)

    spiral_home = Path(args.spiral_home).resolve()
    prd_path = Path(args.prd)

    results = run_checks(spiral_home=spiral_home, prd_path=prd_path)

    print(json.dumps(results, indent=2))

    failed = [r for r in results if r["status"] == "fail"]
    total = len(results)
    passed = total - len(failed)

    print()
    if not failed:
        print(f"All checks passed ({passed}/{total}) - ready to run SPIRAL")
        return 0

    print(f"{len(failed)} checks failed - see hints above")
    for r in failed:
        print(f"  - {r['check_name']}: {r['remediation']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
