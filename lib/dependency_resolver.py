#!/usr/bin/env python3
"""
SPIRAL — Story Dependency Auto-Resolver via NLP-based Keyword Inference

Scans prd.json story titles and descriptions for dependency keywords
('requires', 'depends on', 'blocked by', 'after', 'must complete') to infer
depends_on relationships. Validates DAG and outputs .spiral/dependencies.json
with criticality metrics.

Usage:
  python lib/dependency_resolver.py --prd prd.json [--output .spiral/dependencies.json]

Environment:
  SPIRAL_NLP_INFER_DEPS  — set to "true" to apply inferred deps to prd.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional, cast

sys.path.insert(0, os.path.dirname(__file__))
from core.spiral_io import atomic_write_json, configure_utf8_stdout
from prd.check_dag import find_cycles

configure_utf8_stdout()

# NLP keywords that indicate a dependency relationship
DEPENDENCY_KEYWORDS = {
    "requires": r"requires?",
    "depends_on": r"depends?\s+on",
    "blocked_by": r"blocked?\s+by",
    "after": r"after\b(?!\s+all)",  # avoid "after all"
    "must_complete": r"must\s+complete",
    "prerequisite": r"prerequisite",
    "wait": r"wait\s+(?:for|on|until)",
}


def extract_story_ids(text: str) -> list[str]:
    """Extract story IDs (US-NNN, UT-NNN, etc.) from text."""
    # Match patterns like US-123, UT-456, PROJECT-789 (case-insensitive)
    pattern = r"\b([A-Z]+[-_]?\d+)\b"
    matches = re.findall(pattern, text, re.IGNORECASE)
    # Normalize: remove underscores, convert to uppercase
    normalized = [m.replace("_", "-").upper() for m in matches]
    return list(set(normalized))


def infer_dependencies(
    stories: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """
    Scan story titles and descriptions for dependency keywords.
    Build a map of story_id -> list of inferred dependency IDs.

    Returns:
      dict mapping story_id to list of (upstream) dependency IDs
    """
    story_ids = {s.get("id") for s in stories if isinstance(s, dict) and "id" in s}
    inferred: dict[str, list[str]] = {sid: [] for sid in story_ids if sid}

    for story in stories:
        if not isinstance(story, dict) or "id" not in story:
            continue

        sid = story["id"]
        title = story.get("title", "")
        description = story.get("description", "")
        text = f"{title} {description}".lower()

        found_deps: set[str] = set()

        # Scan for dependency keywords and extract story IDs mentioned nearby
        for keyword, pattern in DEPENDENCY_KEYWORDS.items():
            if re.search(pattern, text, re.IGNORECASE):
                # Extract story IDs within 150 chars around the keyword match
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    start = max(0, match.start() - 150)
                    end = min(len(text), match.end() + 150)
                    context = text[start:end]
                    ids = extract_story_ids(context)
                    # Filter: only include IDs that exist in our story set and aren't self-refs
                    for dep_id in ids:
                        if dep_id in story_ids and dep_id != sid:
                            found_deps.add(dep_id)

        # Prefer extracted IDs, else try direct mentions if no keywords found
        if not found_deps:
            ids = extract_story_ids(text)
            for dep_id in ids:
                if dep_id in story_ids and dep_id != sid:
                    found_deps.add(dep_id)

        inferred[sid] = sorted(list(found_deps))

    return inferred


def compute_dag_metrics(
    stories: list[dict[str, Any]],
    inferred_deps: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """
    Compute DAG metrics for each story: blocked_by, critical, depth, blocker_count.

    Args:
      stories: List of story dicts
      inferred_deps: Dict mapping story_id -> list of dependency IDs

    Returns:
      Dict mapping story_id -> {depends_on, blocked_by, critical, depth_in_dag, blocker_count}
    """
    story_ids_raw = {
        s.get("id") for s in stories if isinstance(s, dict) and "id" in s and s.get("id")
    }
    story_ids = cast(set[str], story_ids_raw)
    metrics: dict[str, dict[str, Any]] = {}

    # Build reverse dependency map (what depends on me?)
    blocked_by: dict[str, set[str]] = {sid: set() for sid in story_ids}
    for sid, deps in inferred_deps.items():
        if not sid:
            continue
        for dep_id in deps:
            if dep_id in blocked_by:
                blocked_by[dep_id].add(sid)

    # Compute depth_in_dag via topological sort
    depth: dict[str, int] = {}
    # Convert lists to sets for comparison
    remaining = {sid: set(deps) for sid, deps in inferred_deps.items() if sid}
    resolved: set[str] = set()
    queue = [sid for sid in story_ids if not remaining.get(sid, set())]

    current_depth = 0
    while queue:
        batch = list(queue)
        for sid in batch:
            depth[sid] = current_depth
            resolved.add(sid)
        queue = []
        for sid in story_ids - resolved:
            if remaining.get(sid, set()) <= resolved:
                queue.append(sid)
        current_depth += 1

    # Compute criticality: a story is critical if many others depend on it
    blocker_counts = {sid: len(blocked_by.get(sid, set())) for sid in story_ids}
    max_blockers = max(blocker_counts.values()) if blocker_counts else 0
    critical_threshold = max(1, max_blockers // 2)  # Top 50% by blocker count

    # Build final metrics
    for sid in story_ids:
        metrics[sid] = {
            "depends_on": inferred_deps.get(sid, []),
            "blocked_by": sorted(list(blocked_by.get(sid, set()))),
            "critical": blocker_counts.get(sid, 0) >= critical_threshold,
            "depth_in_dag": depth.get(sid, 0),
            "blocker_count": blocker_counts.get(sid, 0),
        }

    return metrics


def cmd_resolve(
    prd_path: Path,
    output: Optional[Path] = None,
) -> int:
    """Main entry point: read prd.json, infer deps, validate DAG, output JSON."""
    if not prd_path.exists():
        print(f"[resolver] ERROR: {prd_path} not found", file=sys.stderr)
        return 1

    try:
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[resolver] ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    stories = prd.get("userStories", [])
    inferred = infer_dependencies(stories)

    # Count how many inferred dependencies
    total_inferred = sum(len(deps) for deps in inferred.values())
    print(f"[resolver] Inferred {total_inferred} dependencies from {len(stories)} stories")

    # Check for cycles before computing metrics
    cycles = find_cycles(stories)
    if cycles:
        print(f"[resolver] WARNING: Cycle detected involving {len(cycles)} stories:", file=sys.stderr)
        for sid in cycles:
            title = ""
            for s in stories:
                if isinstance(s, dict) and s.get("id") == sid:
                    title = s.get("title", "")
                    break
            print(f"  - {sid}: {title}", file=sys.stderr)

    # Compute metrics
    metrics = compute_dag_metrics(stories, inferred)

    # Output JSON
    output_data = {
        "timestamp": None,  # Will be set by caller
        "dependencies": metrics,
    }

    if output is None:
        output = Path(".spiral") / "dependencies.json"

    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(output), output_data)
    print(f"[resolver] Written to {output}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Infer story dependencies from NLP-based keyword matching",
    )
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Output path for dependencies JSON (default: .spiral/dependencies.json)",
    )
    args = parser.parse_args()

    prd_path = Path(args.prd)
    output = Path(args.output) if args.output else None
    return cmd_resolve(prd_path, output)


if __name__ == "__main__":
    sys.exit(main())
