#!/usr/bin/env python3
"""
validate_phase_outputs.py — Validate SPIRAL phase output JSON files against schemas.

Checks .spiral/ phase output files against lib/schemas/phase_*.schema.json.

Usage:
    from validate_phase_outputs import validate_phase, validate_phases

    result = validate_phase("R", spiral_dir=".spiral", schema_dir="lib/schemas")
    # Returns: {valid: bool, phase: str, errors: [{file, line, expected, got}]}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Mapping from phase letter to output filename relative to spiral_dir.
# Phase M uses "../prd.json" to reference prd.json in the parent directory.
PHASE_FILE_MAP: dict[str, str] = {
    "R": "_research_output.json",
    "T": "_test_stories_output.json",
    "S": "_validated_stories.json",
    "M": "../prd.json",
}

VALID_PHASES: frozenset[str] = frozenset(PHASE_FILE_MAP.keys())
SCHEMA_FILE_PATTERN = "phase_{phase}.schema.json"


def _type_name(value: Any) -> str:
    """Return human-readable JSON type name for a Python value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _validate_object(
    data: Any,
    schema: dict[str, Any],
    path: str,
    errors: list[dict[str, Any]],
    filename: str,
) -> None:
    """Recursively validate data against a lightweight JSON Schema-like definition."""
    if not isinstance(data, dict):
        errors.append(
            {
                "file": filename,
                "line": 0,
                "expected": f"object at {path}",
                "got": _type_name(data),
            }
        )
        return

    # Check required fields
    for req in schema.get("required", []):
        if req not in data:
            errors.append(
                {
                    "file": filename,
                    "line": 0,
                    "expected": f"field '{req}' at {path}",
                    "got": "missing",
                }
            )

    # Check property types
    properties: dict[str, Any] = schema.get("properties", {})
    for key, prop_schema in properties.items():
        if key not in data:
            continue  # Already caught by required check

        value = data[key]
        prop_path = f"{path}.{key}"
        expected_type: str = prop_schema.get("type", "")

        if expected_type == "array":
            if not isinstance(value, list):
                errors.append(
                    {
                        "file": filename,
                        "line": 0,
                        "expected": f"array at {prop_path}",
                        "got": _type_name(value),
                    }
                )
            else:
                items_schema: dict[str, Any] = prop_schema.get("items", {})
                if items_schema:
                    for i, item in enumerate(value):
                        _validate_object(
                            item,
                            items_schema,
                            f"{prop_path}[{i}]",
                            errors,
                            filename,
                        )

        elif expected_type == "string":
            if not isinstance(value, str):
                errors.append(
                    {
                        "file": filename,
                        "line": 0,
                        "expected": f"string at {prop_path}",
                        "got": _type_name(value),
                    }
                )
            else:
                enum_values: list[str] = prop_schema.get("enum", [])
                if enum_values and value not in enum_values:
                    errors.append(
                        {
                            "file": filename,
                            "line": 0,
                            "expected": f"one of {enum_values} at {prop_path}",
                            "got": repr(value),
                        }
                    )

        elif expected_type == "boolean":
            if not isinstance(value, bool):
                errors.append(
                    {
                        "file": filename,
                        "line": 0,
                        "expected": f"boolean at {prop_path}",
                        "got": _type_name(value),
                    }
                )


def validate_phase(
    phase: str,
    spiral_dir: str | Path = ".spiral",
    schema_dir: str | Path = "lib/schemas",
) -> dict[str, Any]:
    """Validate a single phase output file against its schema.

    Args:
        phase: Phase letter (R, T, S, or M)
        spiral_dir: Directory containing phase output files (default: .spiral)
        schema_dir: Directory containing schema files (default: lib/schemas)

    Returns:
        {valid: bool, phase: str, errors: [{file, line, expected, got}]}
    """
    errors: list[dict[str, Any]] = []
    phase = phase.upper()

    if phase not in VALID_PHASES:
        return {
            "valid": False,
            "phase": phase,
            "errors": [
                {
                    "file": "",
                    "line": 0,
                    "expected": f"phase in {sorted(VALID_PHASES)}",
                    "got": phase,
                }
            ],
        }

    spiral_path = Path(spiral_dir)
    schema_path = Path(schema_dir)

    relative_file = PHASE_FILE_MAP[phase]
    if relative_file.startswith("../"):
        data_file = spiral_path.parent / relative_file[3:]
    else:
        data_file = spiral_path / relative_file

    schema_file = schema_path / SCHEMA_FILE_PATTERN.format(phase=phase)
    filename = str(data_file)

    # Load schema
    if not schema_file.exists():
        errors.append(
            {
                "file": str(schema_file),
                "line": 0,
                "expected": "schema file to exist",
                "got": "missing",
            }
        )
        return {"valid": False, "phase": phase, "errors": errors}

    try:
        with open(schema_file, encoding="utf-8") as f:
            schema: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(
            {
                "file": str(schema_file),
                "line": 0,
                "expected": "valid JSON schema",
                "got": str(exc),
            }
        )
        return {"valid": False, "phase": phase, "errors": errors}

    # Check data file exists
    if not data_file.exists():
        errors.append(
            {
                "file": filename,
                "line": 0,
                "expected": "file to exist",
                "got": "missing",
            }
        )
        return {"valid": False, "phase": phase, "errors": errors}

    # Load data
    try:
        with open(data_file, encoding="utf-8") as f:
            data: Any = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(
            {
                "file": filename,
                "line": 0,
                "expected": "valid JSON",
                "got": str(exc),
            }
        )
        return {"valid": False, "phase": phase, "errors": errors}

    # Validate structure
    _validate_object(data, schema, "$", errors, filename)

    return {
        "valid": len(errors) == 0,
        "phase": phase,
        "errors": errors,
    }


def validate_phases(
    phases: list[str] | None = None,
    spiral_dir: str | Path = ".spiral",
    schema_dir: str | Path = "lib/schemas",
) -> list[dict[str, Any]]:
    """Validate multiple phase output files.

    Args:
        phases: List of phase letters to validate (default: all phases)
        spiral_dir: Directory containing phase output files
        schema_dir: Directory containing schema files

    Returns:
        List of validation results, one per phase
    """
    if phases is None:
        phases = sorted(VALID_PHASES)
    return [validate_phase(phase, spiral_dir=spiral_dir, schema_dir=schema_dir) for phase in phases]


def format_text_report(results: list[dict[str, Any]]) -> str:
    """Format validation results as human-readable text."""
    lines: list[str] = []
    for result in results:
        phase = result["phase"]
        valid = result["valid"]
        errors: list[dict[str, Any]] = result["errors"]
        status = "ok" if valid else "fail"
        lines.append(f"[{status}] Phase {phase}")
        for err in errors:
            lines.append(f"  {err['file']}: expected {err['expected']}, got {err['got']}")
    return "\n".join(lines)
