r"""CLI command: validate-federated — Validate federated prd.json structure.

Checks for:
- Story ID format: ^[a-z-]+:(US|UT)-\d{3}$
- Duplicate IDs across repos
- Unresolved cross-repo dependencies
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _validate_ids(prd_dict: dict[str, Any]) -> list[str]:
    """Validate story ID format across all stories.

    Valid format: ^[a-z-]+:(US|UT)-\\d{3}$
    Examples: repo-a:US-001, my-project:UT-042

    Args:
        prd_dict: Parsed prd.json

    Returns:
        List of error strings (empty if all IDs are valid)
    """
    errors: list[str] = []
    id_pattern = re.compile(r"^[a-z-]+(:(US|UT)-\d{3})?$")

    for story in prd_dict.get("userStories", []):
        story_id = story.get("id", "")
        if not story_id:
            errors.append(f"Story at index {prd_dict.get('userStories', []).index(story)} has no id field")
            continue

        # Allow non-namespaced IDs (e.g., US-001) for main project
        # Require namespaced format (repo:US-001) for federated
        if ":" in story_id:
            # Namespaced ID - validate full format
            if not id_pattern.match(story_id):
                errors.append(f"Invalid ID format: {story_id!r} (expected format: 'namespace:(US|UT)-NNN')")
        else:
            # Non-namespaced ID - validate base format (US-NNN or UT-NNN)
            base_pattern = re.compile(r"^(US|UT)-\d{3}$")
            if not base_pattern.match(story_id):
                errors.append(f"Invalid ID format: {story_id!r} (expected format: '(US|UT)-NNN' or 'namespace:(US|UT)-NNN')")

    return errors


def _find_duplicates(prd_dict: dict[str, Any]) -> list[str]:
    """Detect duplicate story IDs.

    Args:
        prd_dict: Parsed prd.json

    Returns:
        List of error strings describing duplicates
    """
    errors: list[str] = []
    seen_ids: dict[str, int] = {}

    for idx, story in enumerate(prd_dict.get("userStories", [])):
        story_id = story.get("id", "")
        if story_id in seen_ids:
            errors.append(f"Duplicate ID: {story_id!r} appears at indices {seen_ids[story_id]} and {idx}")
        else:
            seen_ids[story_id] = idx

    return errors


def _find_unresolved_deps(prd_dict: dict[str, Any]) -> list[str]:
    """Detect unresolved cross-repo dependencies.

    A dependency is unresolved if a story depends_on another story ID
    that is not present in the prd.json.

    Args:
        prd_dict: Parsed prd.json

    Returns:
        List of error strings describing unresolved dependencies
    """
    errors: list[str] = []
    available_ids = {s.get("id") for s in prd_dict.get("userStories", []) if s.get("id")}

    for story in prd_dict.get("userStories", []):
        story_id = story.get("id", "")
        deps = story.get("dependencies", [])

        if not isinstance(deps, list):
            continue

        for dep_id in deps:
            if isinstance(dep_id, dict):
                # Handle dependency objects with 'id' field
                dep_id = dep_id.get("id", "")
            if isinstance(dep_id, str) and dep_id not in available_ids:
                errors.append(f"Unresolved dependency: {story_id!r} depends_on {dep_id!r} (not found in prd.json)")

    return errors


def validate_federated(prd_path: Path) -> dict[str, Any]:
    """Validate federated prd.json structure.

    Args:
        prd_path: Path to prd.json file

    Returns:
        Report dict with keys: valid (bool), errors (list), cycles (list)
    """
    if not prd_path.exists():
        return {
            "valid": False,
            "errors": [f"File not found: {prd_path}"],
            "cycles": [],
        }

    try:
        with open(prd_path, "r", encoding="utf-8") as f:
            prd_dict = json.load(f)
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "errors": [f"Invalid JSON: {e}"],
            "cycles": [],
        }

    # Run all validation checks
    id_errors = _validate_ids(prd_dict)
    dup_errors = _find_duplicates(prd_dict)
    dep_errors = _find_unresolved_deps(prd_dict)

    all_errors = id_errors + dup_errors + dep_errors
    valid = len(all_errors) == 0

    return {
        "valid": valid,
        "errors": all_errors,
        "cycles": [],  # Placeholder for future cycle detection (US-515)
    }


def add_subparser(subparsers: Any) -> None:
    """Register validate-federated subcommand with argparse.

    Args:
        subparsers: An argparse._SubParsersAction from ArgumentParser.add_subparsers()
    """
    parser = subparsers.add_parser(
        "validate-federated",
        help="Validate federated prd.json structure (ID format, duplicates, dependencies)",
    )
    parser.add_argument(
        "--prd",
        type=str,
        default="prd.json",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--sub-projects",
        type=str,
        default="",
        help="Comma-separated list of sub-project names (optional, for documentation)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Path to write JSON report (optional; prints to stdout if omitted)",
    )


def run(args: argparse.Namespace) -> None:
    """Execute validate-federated command."""
    prd_path = Path(getattr(args, "prd", "prd.json"))
    output_path = getattr(args, "output", "")

    report = validate_federated(prd_path)

    # Write or print report
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {output_path}")
    else:
        print(json.dumps(report, indent=2))

    # Print summary to stderr
    if report["errors"]:
        print(f"\nValidation FAILED: {len(report['errors'])} error(s)", file=sys.stderr)
        for error in report["errors"]:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nValidation PASSED: No issues found", file=sys.stderr)
        sys.exit(0)
