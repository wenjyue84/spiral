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
                errors.append(
                    f"Invalid ID format: {story_id!r} (expected format: '(US|UT)-NNN' or 'namespace:(US|UT)-NNN')"
                )

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


def _detect_cycles(prd_dict: dict[str, Any]) -> list[list[str]]:
    """Detect circular dependencies in the story dependency graph.

    Uses depth-first search (DFS) with recursion to find all cycles
    in the dependency graph. Returns cycles with full traversal paths,
    de-duplicated so each unique cycle is reported once.

    Args:
        prd_dict: Parsed prd.json

    Returns:
        List of cycles, each cycle represented as a path list
        (e.g., ["repo-a:US-001", "repo-b:US-005", "repo-a:US-001"])
    """
    # Build adjacency list (graph) — only include valid story IDs
    graph: dict[str, list[str]] = {}
    story_ids: set[str] = set()

    for story in prd_dict.get("userStories", []):
        story_id = story.get("id", "")
        if story_id:
            story_ids.add(story_id)

    # Now build graph edges
    for story in prd_dict.get("userStories", []):
        story_id = story.get("id", "")
        if not story_id:
            continue

        graph[story_id] = []
        deps = story.get("dependencies", [])
        if not isinstance(deps, list):
            continue

        for dep_id in deps:
            if isinstance(dep_id, dict):
                dep_id = dep_id.get("id", "")
            # Only add edge if target story exists
            if isinstance(dep_id, str) and dep_id in story_ids:
                graph[story_id].append(dep_id)

    # Find cycles using DFS
    cycles_set: set[tuple[str, ...]] = set()
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        """DFS to detect cycles."""
        if node in rec_stack:
            # Found a cycle: extract it from the path
            try:
                cycle_start_idx = path.index(node)
                cycle = path[cycle_start_idx:] + [node]
                # Canonicalize to deduplicate: rotate so min element is first
                if cycle:
                    cycle_nodes = cycle[:-1]
                    min_node = min(cycle_nodes)
                    min_idx = cycle_nodes.index(min_node)
                    canonical = tuple(cycle_nodes[min_idx:] + cycle_nodes[:min_idx] + [min_node])
                    cycles_set.add(canonical)
            except ValueError:
                pass
            return

        if node in visited:
            return

        visited.add(node)
        rec_stack.add(node)
        new_path = path + [node]

        for neighbor in graph.get(node, []):
            dfs(neighbor, new_path)

        rec_stack.discard(node)

    # Run DFS from all unvisited nodes
    for node_id in story_ids:
        if node_id not in visited:
            dfs(node_id, [])

    # Convert back to list of lists
    return [list(cycle) for cycle in cycles_set]


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
    cycles = _detect_cycles(prd_dict)

    all_errors = id_errors + dup_errors + dep_errors
    valid = len(all_errors) == 0 and len(cycles) == 0

    return {
        "valid": valid,
        "errors": all_errors,
        "cycles": cycles,
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
    if report["errors"] or report["cycles"]:
        print("\nValidation FAILED:", file=sys.stderr)
        if report["errors"]:
            print(f"  {len(report['errors'])} error(s):", file=sys.stderr)
            for error in report["errors"]:
                print(f"    - {error}", file=sys.stderr)
        if report["cycles"]:
            print(f"  {len(report['cycles'])} cycle(s):", file=sys.stderr)
            for cycle in report["cycles"]:
                print(f"    - {' -> '.join(cycle)}", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nValidation PASSED: No issues found", file=sys.stderr)
        sys.exit(0)
