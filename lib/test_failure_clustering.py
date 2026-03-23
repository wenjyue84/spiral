#!/usr/bin/env python3
"""
lib/test_failure_clustering.py — Test Failure Clustering for Phase T

Groups test failure stories by source module. When 3+ tests fail from the same
source file, creates a single root-cause story instead of multiple individual stories.
"""

from typing import Any


def extract_source_file(test_id: str) -> str:
    """Extract source file path from test ID.

    Example: 'tests.unit.module.test_file.TestClass.test_method'
    Returns:  'tests/unit/module/test_file.py'

    Pattern: parts before Test* (class) are the module path.
    """
    parts = test_id.split(".")
    # Find where the test class starts (uppercase Test*)
    for i, part in enumerate(parts):
        # Check if this looks like a test class (starts with uppercase letter)
        if part and part[0].isupper():
            # Everything before this is the module path
            file_parts = parts[:i]
            if file_parts:
                return "/".join(file_parts) + ".py"
            break
    # Fallback: use all but last part (method)
    if len(parts) >= 2:
        return "/".join(parts[:-1]) + ".py"
    return test_id


def cluster_failures(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group test failure stories by source file.

    When 3+ stories have the same source file, combine them into a single
    root-cause story.

    Args:
        stories: List of story dicts from test synthesis, each with _source field
                containing "test-synthesis:TEST_ID"

    Returns:
        List of stories with failures clustered: individual stories remain if <3
        from same source, clustered story created if >=3 from same source.
    """
    if not stories:
        return []

    # Group stories by source file
    by_source: dict[str, list[dict[str, Any]]] = {}

    for story in stories:
        source = story.get("_source", "")
        if not source.startswith("test-synthesis:"):
            # Not a test failure, pass through
            by_source.setdefault("__passthrough__", []).append(story)
            continue

        test_id = source.replace("test-synthesis:", "")
        source_file = extract_source_file(test_id)

        if source_file not in by_source:
            by_source[source_file] = []
        by_source[source_file].append(story)

    # Build result: cluster if >=3, otherwise keep individual
    result = []
    passthrough = by_source.pop("__passthrough__", [])
    result.extend(passthrough)

    for source_file, file_stories in by_source.items():
        if len(file_stories) >= 3:
            # Create clustered story
            module_name = source_file.replace("/", ".").replace(".py", "")
            test_ids = [s.get("_source", "").replace("test-synthesis:", "") for s in file_stories]

            clustered = {
                "title": f"[Root Cause] Fix {module_name} causing {len(file_stories)} test failures",
                "priority": file_stories[0].get("priority", "medium"),
                "description": (
                    f"Multiple tests ({len(file_stories)}) are failing in {source_file}. "
                    f"Likely a single root cause affecting multiple test cases."
                ),
                "acceptanceCriteria": [
                    f"All {len(file_stories)} tests from {source_file} pass without error."
                ] + [f"  - `{tid}`" for tid in test_ids],
                "technicalNotes": [
                    f"Clustered {len(file_stories)} individual test failures:",
                    f"  - {source_file}",
                ] + [f"    - {tid}" for tid in test_ids],
                "dependencies": [],
                "estimatedComplexity": "small",
                "_source": f"test-clustering:{source_file}",
                "_clustered_from": test_ids,
            }
            result.append(clustered)
        else:
            # Keep individual stories
            result.extend(file_stories)

    return result
