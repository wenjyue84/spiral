#!/usr/bin/env python3
"""Validate story ID namespacing for federated multi-repo projects.

Enforces pattern: {REPO}_{TYPE}-{NUMBER} where REPO is one of the allowed repos.
Rejects cross-repo dependencies.
"""

import json
import re
import sys
from typing import Any


def validate_federated_namespaces(
    prd: dict[str, Any], repos: list[str]
) -> dict[str, Any]:
    """
    Validate all story IDs match federated namespace pattern.

    Pattern: {REPO}_{TYPE}-{NUMBER} where REPO is in the repos list.
    Rejects stories with cross-repo references.

    Args:
        prd: Loaded prd.json dict
        repos: List of valid repo names (e.g., ["backend", "frontend"])

    Returns:
        dict with keys:
        - valid: bool (True if all pass)
        - errors: list[str] (validation errors)
        - warnings: list[str] (non-fatal issues)
        - passed_count: int (stories with correct namespace)
        - failed_count: int (stories with incorrect namespace)
    """
    errors: list[str] = []
    warnings: list[str] = []
    passed_count = 0
    failed_count = 0

    stories = prd.get("userStories", [])
    if not stories:
        return {
            "valid": True,
            "errors": [],
            "warnings": ["No stories found in prd.json"],
            "passed_count": 0,
            "failed_count": 0,
        }

    for story in stories:
        story_id = story.get("id", "")
        if not story_id:
            errors.append("Found story with missing 'id' field")
            failed_count += 1
            continue

        # Check namespace pattern
        repo, is_valid = _validate_namespace_pattern(story_id, repos)
        if not is_valid:
            errors.append(
                f"[{story_id}] Invalid namespace. Expected format: "
                f"{{REPO}}_{{TYPE}}-{{NUMBER}} where REPO in {repos}"
            )
            failed_count += 1
        else:
            passed_count += 1

        # Check cross-repo references in dependencies
        dependencies = story.get("dependencies", [])
        if dependencies:
            for dep_id in dependencies:
                dep_repo, is_valid = _validate_namespace_pattern(dep_id, repos)
                if repo and dep_repo and repo != dep_repo:
                    errors.append(
                        f"[{story_id}] Cross-repo dependency rejected: "
                        f"{repo} story cannot depend on {dep_id}"
                    )
                    failed_count += 1
                    passed_count = max(0, passed_count - 1)

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "passed_count": passed_count,
        "failed_count": failed_count,
    }

    return result


def _validate_namespace_pattern(story_id: str, repos: list[str]) -> tuple[str, bool]:
    """
    Validate story ID against {REPO}_{TYPE}-{NUMBER} pattern.

    Args:
        story_id: Story ID to validate (e.g., "backend_US-001")
        repos: List of valid repo names

    Returns:
        (repo_name, is_valid) tuple. repo_name is "" if invalid.
    """
    # Pattern: {REPO}_{TYPE}-{NUMBER}
    # Example: backend_US-001, frontend_UT-999
    pattern = r"^([a-z_]+)_(US|UT)-(\d+)$"
    match = re.match(pattern, story_id)

    if not match:
        return "", False

    repo_name = match.group(1)
    if repo_name not in repos:
        return "", False

    return repo_name, True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <prd_file> <repos_csv>")
        print("  prd_file: path to prd.json")
        print("  repos_csv: comma-separated repo names (e.g., 'backend,frontend')")
        sys.exit(1)

    prd_path = sys.argv[1]
    repos_str = sys.argv[2]
    repos = [r.strip() for r in repos_str.split(",") if r.strip()]

    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"[spiral] ERROR: Failed to load {prd_path}: {e}", file=sys.stderr)
        sys.exit(1)

    result = validate_federated_namespaces(prd, repos)

    print("[spiral] Federated namespace validation")
    print(f"  Repositories: {repos}")
    print(f"  Passed: {result['passed_count']} | Failed: {result['failed_count']}")
    if result["errors"]:
        print("  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")
    if result["warnings"]:
        print("  Warnings:")
        for warn in result["warnings"]:
            print(f"    - {warn}")

    sys.exit(0 if result["valid"] else 1)
