#!/usr/bin/env python3
"""validate_env.py — SPIRAL startup environment variable validator (US-264).

Reads env_schema.json, validates all listed env vars against the current
environment, prints a colour-coded summary table, and exits with code 1
if any required var is missing or invalid.

Usage:
    python lib/validate_env.py [--schema PATH]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ANSI colour codes (suppressed when not a TTY)
_IS_TTY = sys.stdout.isatty()
_RED = "\033[31m" if _IS_TTY else ""
_YELLOW = "\033[33m" if _IS_TTY else ""
_GREEN = "\033[32m" if _IS_TTY else ""
_BOLD = "\033[1m" if _IS_TTY else ""
_RESET = "\033[0m" if _IS_TTY else ""

# URL validation pattern (basic; requires scheme + host)
_URL_RE = re.compile(
    r"^https?://[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%\-]+"
)


def _is_valid_url(value: str) -> bool:
    return bool(_URL_RE.match(value))


def _is_valid_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _is_valid_bool(value: str) -> bool:
    return value.lower() in {"0", "1", "true", "false", "yes", "no"}


def _validate_type(var_type: str, value: str) -> str | None:
    """Return error description if invalid, or None if valid."""
    if var_type == "url":
        if not _is_valid_url(value):
            return f"expected URL starting with http:// or https://, got \"{value}\""
    elif var_type == "int":
        if not _is_valid_int(value):
            return f"expected integer, got \"{value}\""
    elif var_type == "bool":
        if not _is_valid_bool(value):
            return f"expected bool (0/1/true/false), got \"{value}\""
    return None


def validate(schema_path: Path) -> int:
    """Validate env vars against schema. Returns exit code (0 or 1)."""
    if not schema_path.exists():
        print(
            f"[validate_env] ERROR: env_schema.json not found at {schema_path}",
            file=sys.stderr,
        )
        return 1

    with schema_path.open(encoding="utf-8") as f:
        schema: dict[str, Any] = json.load(f)

    vars_spec: list[dict[str, Any]] = schema.get("vars", [])

    missing_required: list[str] = []
    invalid_vars: list[str] = []
    missing_optional: list[str] = []
    ok_vars: list[str] = []

    rows: list[tuple[str, str, str, str]] = []  # (status_tag, name, detail, fix)

    for spec in vars_spec:
        name: str = spec["name"]
        required: bool = spec.get("required", False)
        var_type: str = spec.get("type", "string")
        description: str = spec.get("description", "")
        fix_hint: str = spec.get("fix_hint", f"export {name}=<value>")
        default: str = spec.get("default", "")

        value = os.environ.get(name)

        if value is None or value == "":
            if required:
                missing_required.append(name)
                rows.append(
                    (
                        f"{_RED}MISSING{_RESET}",
                        name,
                        description,
                        fix_hint,
                    )
                )
                # Print actionable line immediately
                print(
                    f"{_RED}MISSING{_RESET} [{name}]: {description}. "
                    f"Fix: {fix_hint}"
                )
            elif not value and not default:
                # Optional, no default, currently absent — warn
                missing_optional.append(name)
                rows.append(
                    (
                        f"{_YELLOW}ABSENT{_RESET}",
                        name,
                        description,
                        fix_hint,
                    )
                )
            else:
                ok_vars.append(name)
                rows.append(("skip", name, description, ""))
        else:
            # Var is set; validate type (skip type check for plain strings)
            if var_type != "string":
                type_error = _validate_type(var_type, value)
                if type_error:
                    invalid_vars.append(name)
                    rows.append(
                        (
                            f"{_RED}INVALID{_RESET}",
                            name,
                            type_error,
                            fix_hint,
                        )
                    )
                    print(
                        f"{_RED}INVALID{_RESET} [{name}]: {type_error}. "
                        f"Fix: {fix_hint}"
                    )
                else:
                    ok_vars.append(name)
                    rows.append((f"{_GREEN}OK{_RESET}", name, description, ""))
            else:
                ok_vars.append(name)
                rows.append((f"{_GREEN}OK{_RESET}", name, description, ""))

    # Summary table header
    total = len(vars_spec)
    n_ok = len(ok_vars)
    n_missing_req = len(missing_required)
    n_invalid = len(invalid_vars)
    n_absent_opt = len(missing_optional)

    print()
    print(f"{_BOLD}SPIRAL env validation — {total} vars checked{_RESET}")
    print(
        f"  {_GREEN}OK{_RESET}: {n_ok}  "
        f"{_RED}MISSING required{_RESET}: {n_missing_req}  "
        f"{_RED}INVALID{_RESET}: {n_invalid}  "
        f"{_YELLOW}absent optional{_RESET}: {n_absent_opt}"
    )

    if n_missing_req > 0 or n_invalid > 0:
        print(
            f"\n{_RED}[validate_env] FAIL — {n_missing_req} required var(s) missing, "
            f"{n_invalid} invalid. Fix above and re-run.{_RESET}"
        )
        return 1

    if n_absent_opt > 0:
        print(
            f"{_YELLOW}[validate_env] WARN — {n_absent_opt} optional var(s) absent "
            f"(features using them are disabled).{_RESET}"
        )

    print(f"{_GREEN}[validate_env] OK — all required vars present.{_RESET}")
    return 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate SPIRAL environment variables against env_schema.json"
    )
    parser.add_argument(
        "--schema",
        default=str(Path(__file__).parent.parent / "env_schema.json"),
        help="Path to env_schema.json (default: <spiral_root>/env_schema.json)",
    )
    args = parser.parse_args()

    sys.exit(validate(Path(args.schema)))


if __name__ == "__main__":
    main()
