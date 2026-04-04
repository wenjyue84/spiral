"""lib/federated_schema_validator.py — Federated prd.json schema validator (US-1057).

Validates multi-subproject prd.json for:
- Duplicate story IDs across subprojects (AC1)
- Namespace prefix violations (AC2)

CLI: spiral validate-federated-schema prd.json
Exits with code 1 on validation failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def detect_duplicates(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect story IDs that appear more than once across subprojects.

    Returns:
        List of {story_id, locations: [sub_project, ...]} for each duplicate.
    """
    seen: dict[str, list[str]] = {}
    for story in stories:
        sid = story.get("id", "")
        if not sid:
            continue
        sub_project = story.get("sub_project", "<root>")
        if sid not in seen:
            seen[sid] = []
        seen[sid].append(str(sub_project))

    duplicates = []
    for sid, locations in seen.items():
        if len(locations) > 1:
            duplicates.append({"story_id": sid, "locations": locations})
    return duplicates


def validate_namespace_prefixes(
    stories: list[dict[str, Any]],
    namespace_rules: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate stories in each subproject use the required ID prefix.

    Args:
        stories: Story dicts with 'id' and 'sub_project' fields.
        namespace_rules: {subproject_name: required_prefix} e.g. {"makan": "MAKAN-"}

    Returns:
        List of violations with {story_id, sub_project, required_prefix, suggestion}.
    """
    violations = []
    for story in stories:
        sid = story.get("id", "")
        sub_project = story.get("sub_project", "")
        if not sid or not sub_project:
            continue
        required_prefix = namespace_rules.get(str(sub_project))
        if required_prefix is None:
            continue
        if not sid.startswith(required_prefix):
            violations.append(
                {
                    "story_id": sid,
                    "sub_project": sub_project,
                    "required_prefix": required_prefix,
                    "suggestion": f"Rename '{sid}' to '{required_prefix}{sid}'",
                }
            )
    return violations


def _build_namespace_rules(prd_dict: dict[str, Any]) -> dict[str, str]:
    """Extract namespace prefix rules from prd.json subProjects field.

    Supports entries as:
    - {name: "makan", namespace_prefix: "MAKAN-"}
    - {namespace: "makan", prefix: "MAKAN-"}
    - plain string "makan" (prefix inferred as "MAKAN-")
    """
    rules: dict[str, str] = {}
    sub_projects = prd_dict.get("subProjects") or []
    for sp in sub_projects:
        if isinstance(sp, dict):
            name = sp.get("name") or sp.get("namespace")
            prefix = sp.get("namespace_prefix") or sp.get("prefix")
            if name and prefix:
                rules[str(name)] = str(prefix)
            elif name:
                rules[str(name)] = name.upper() + "-"
        elif isinstance(sp, str):
            rules[sp] = sp.upper() + "-"
    return rules


def validate(
    prd_dict: dict[str, Any],
    namespace_rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run full federated schema validation.

    Args:
        prd_dict: Parsed prd.json dict.
        namespace_rules: Optional override for {subproject: required_prefix}.
                         If None, inferred from prd_dict["subProjects"].

    Returns:
        {
            "pass": bool,
            "error_count": int,
            "errors": [{"type", "story_id", "message", ...}],
            "suggestions": ["Rename 'US-1' to 'MAKAN-US-1'", ...],
        }
    """
    stories: list[dict[str, Any]] = prd_dict.get("userStories", [])
    if not isinstance(stories, list):
        stories = []

    if namespace_rules is None:
        namespace_rules = _build_namespace_rules(prd_dict)

    errors: list[dict[str, Any]] = []
    suggestions: list[str] = []

    # AC1: Duplicate IDs across subprojects
    for dup in detect_duplicates(stories):
        errors.append(
            {
                "type": "duplicate_story_id",
                "story_id": dup["story_id"],
                "locations": dup["locations"],
                "message": (
                    f"Story ID '{dup['story_id']}' appears in multiple subprojects: "
                    + ", ".join(f"'{loc}'" for loc in dup["locations"])
                ),
            }
        )

    # AC2: Namespace prefix violations
    if namespace_rules:
        for v in validate_namespace_prefixes(stories, namespace_rules):
            errors.append(
                {
                    "type": "namespace_prefix_violation",
                    "story_id": v["story_id"],
                    "sub_project": v["sub_project"],
                    "required_prefix": v["required_prefix"],
                    "message": (
                        f"Story '{v['story_id']}' in subproject '{v['sub_project']}' "
                        f"must start with prefix '{v['required_prefix']}'"
                    ),
                }
            )
            suggestions.append(v["suggestion"])

    return {
        "pass": len(errors) == 0,
        "error_count": len(errors),
        "errors": errors,
        "suggestions": suggestions,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for standalone usage."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate federated prd.json schema (US-1057)")
    parser.add_argument("prd", help="Path to prd.json")
    parser.add_argument(
        "--namespace",
        action="append",
        metavar="NAME:PREFIX",
        help="Override namespace rules, e.g. --namespace makan:MAKAN-",
    )
    args = parser.parse_args(argv)

    prd_path = Path(args.prd)
    if not prd_path.exists():
        print(json.dumps({"error": f"File not found: {prd_path}"}), file=sys.stderr)
        return 1

    try:
        with open(prd_path, encoding="utf-8") as f:
            prd_dict = json.load(f)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}), file=sys.stderr)
        return 1

    namespace_rules: dict[str, str] | None = None
    if args.namespace:
        namespace_rules = {}
        for entry in args.namespace:
            if ":" in entry:
                name, prefix = entry.split(":", 1)
                namespace_rules[name] = prefix

    result = validate(prd_dict, namespace_rules)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
