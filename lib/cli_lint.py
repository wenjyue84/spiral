#!/usr/bin/env python3
"""CLI command: spiral lint

Validates prd.json schema and spiral.config.sh variable references.
Exit 0 on success (no output), exit 1 on failure with error messages to stderr.

Usage:
  python main.py lint [--prd FILE] [--config FILE]
  spiral --lint
"""

import json
import re
import sys
from pathlib import Path

import jsonschema


def load_and_validate_prd(prd_path: str) -> list[str]:
    """
    Load and validate prd.json against prd.schema.json.

    Returns list of error strings. Empty list = valid.
    Errors include: file not found, JSON parse errors, schema validation errors.
    """
    errors: list[str] = []

    prd_file = Path(prd_path).resolve()
    if not prd_file.exists():
        errors.append(f"ERROR: prd.json: File not found: {prd_path}")
        return errors

    # Load prd.json
    try:
        with open(prd_file, encoding="utf-8") as f:
            prd_data = json.load(f)
    except json.JSONDecodeError as exc:
        errors.append(f"ERROR: prd.json line {exc.lineno}: Invalid JSON: {exc.msg}")
        return errors

    # Load schema - look in prd file's directory first, then current directory
    schema_candidates = [
        prd_file.parent / "prd.schema.json",
        Path.cwd() / "prd.schema.json",
    ]
    schema_file = None
    for candidate in schema_candidates:
        if candidate.exists():
            schema_file = candidate
            break

    if schema_file is None:
        msg = f"ERROR: prd.schema.json: File not found (looked in {schema_candidates[0].parent} and {Path.cwd()})"
        errors.append(msg)
        return errors

    try:
        with open(schema_file, encoding="utf-8") as f:
            schema = json.load(f)
    except json.JSONDecodeError as exc:
        errors.append(f"ERROR: prd.schema.json line {exc.lineno}: Invalid JSON: {exc.msg}")
        return errors

    # Validate against schema
    try:
        jsonschema.validate(instance=prd_data, schema=schema)
    except jsonschema.ValidationError as exc:
        # Try to get line number from JSON (best effort)
        errors.append(f"ERROR: prd.json: {exc.message}")
    except jsonschema.SchemaError as exc:
        errors.append(f"ERROR: prd.schema.json: {exc.message}")

    return errors


def check_config_sh(config_path: str) -> list[str]:
    """
    Check spiral.config.sh for undefined variable references.

    Looks for bare $VAR or ${VAR} usage without default values (${VAR:-default}).
    Ignores:
    - Variables with defaults: ${VAR:-...}
    - Variables in comments: # ...
    - Variables in strings: "..."

    Returns list of error strings. Empty list = valid.
    """
    errors: list[str] = []

    config_file = Path(config_path)
    if not config_file.exists():
        # Config file is optional, don't error if missing
        return errors

    try:
        with open(config_file, encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"ERROR: spiral.config.sh: {exc}")
        return errors

    # Pattern to find variable usages: $VAR or ${VAR}
    # But exclude ${VAR:-...} which has a default
    var_pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")

    for line_num, line in enumerate(lines, 1):
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Remove all ${VAR:-...} patterns to avoid false positives (variables with defaults)
        # This regex matches ${VAR:-anything} or ${VAR:?anything}
        cleaned = re.sub(r"\$\{([A-Z_][A-Z0-9_]*):[-?][^}]*\}", "", line)

        # Find bare variables
        for match in var_pattern.finditer(cleaned):
            var_name = match.group(1) or match.group(2)
            if var_name:
                errors.append(
                    f"ERROR: spiral.config.sh line {line_num}: "
                    f"Undefined variable: ${var_name} (use ${{VAR:-default}} for defaults)"
                )

    return errors


def lint(prd_path: str = "prd.json", config_path: str = "spiral.config.sh") -> int:
    """
    Validate prd.json and spiral.config.sh.

    Returns 0 on success (no output), 1 on failure (errors printed to stderr).
    """
    all_errors: list[str] = []

    # Validate prd.json
    all_errors.extend(load_and_validate_prd(prd_path))

    # Validate spiral.config.sh
    all_errors.extend(check_config_sh(config_path))

    # Output errors to stderr and exit
    if all_errors:
        for error in all_errors:
            print(error, file=sys.stderr)
        return 1

    return 0
