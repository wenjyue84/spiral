#!/usr/bin/env python3
"""federation_check.py — CLI handler for federation namespace validation.

Outputs a summary table with sub-project names, story counts, collision count,
and auto-fix suggestions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from spiral.federation_validator import validate_federation_namespaces


def format_summary_table(result, prd_file: Path) -> str:
    """Format validation result as a summary table.

    Args:
        result: ValidationResult from validate_federation_namespaces
        prd_file: Path to the prd.json file

    Returns:
        Formatted table string
    """
    lines: list[str] = []
    lines.append("")
    lines.append(f"[federation] Namespace validation for {prd_file}")
    lines.append("")

    # Summary line
    if result.is_valid:
        lines.append("  ✓ Valid   | No collisions detected")
    else:
        lines.append(f"  ✗ Invalid | {len(result.collisions)} collision(s) found")

    lines.append("")

    # Per-project story counts
    project_counts: dict[str, int] = {}
    for story_id, projects_map in result.namespace_map.items():
        for project in projects_map:
            project_counts[project] = project_counts.get(project, 0) + 1

    if project_counts:
        lines.append("  Projects:")
        for project_name in sorted(project_counts):
            count = project_counts[project_name]
            status = "✓"
            lines.append(f"    {status} {project_name:<20} {count:>3} stories")

    # Collisions detail
    if result.collisions:
        lines.append("")
        lines.append("  Collisions:")
        for collision in result.collisions:
            story_id = collision["story_id"]
            projects = collision["projects"]
            projects_str = ", ".join(f"{p}:{px}" for p, px in sorted(projects.items()))
            lines.append(f"    ✗ {story_id:<15} {projects_str}")

    # Suggestions
    if result.suggestions:
        lines.append("")
        lines.append("  Auto-fix suggestions:")
        for suggestion in result.suggestions:
            lines.append(f"    • {suggestion}")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """CLI entry point for federation validate command."""
    if len(sys.argv) < 2:
        print("Usage: python federation_check.py <prd.json>", file=sys.stderr)
        return 1

    prd_file = Path(sys.argv[1])
    if not prd_file.exists():
        print(f"Error: {prd_file} not found", file=sys.stderr)
        return 1

    try:
        with open(prd_file, encoding="utf-8") as f:
            prd_dict = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {prd_file}: {e}", file=sys.stderr)
        return 1

    result = validate_federation_namespaces(prd_dict)
    summary = format_summary_table(result, prd_file)
    print(summary)

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    exit(main())
