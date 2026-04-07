"""federated_merge.py — Namespace-aware story deduplication for federated PRDs.

Accepts stories with namespace-qualified IDs (e.g., PROJ1/US-100) and returns
(accepted_stories, rejected_stories, error_log).

Same-namespace duplicate IDs are rejected; identical IDs from different namespaces
are both accepted.

Story: US-1171
"""

from __future__ import annotations

from typing import Any


def federated_merge(stories: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Deduplicate stories by namespace+ID pair.

    Args:
        stories: List of story dicts, each with an 'id' field (format: NAMESPACE/ID or plain ID)

    Returns:
        Tuple of (accepted_stories, rejected_stories, error_log)
        - accepted_stories: Stories with unique namespace+ID pairs
        - rejected_stories: Stories that collide on namespace+ID
        - error_log: Error messages describing conflicts
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    errors: list[str] = []

    # Track (namespace, id) -> list of stories with that key
    seen: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for story in stories:
        story_id = story.get("id", "")
        if not story_id:
            # Stories without ID are accepted (shouldn't happen, but be lenient)
            accepted.append(story)
            continue

        # Parse namespace and ID
        if "/" in story_id:
            namespace, base_id = story_id.split("/", 1)
        else:
            # No namespace; treat as default namespace
            namespace = ""
            base_id = story_id

        key = (namespace, base_id)

        if key not in seen:
            seen[key] = []
        seen[key].append(story)

    # Now partition stories based on whether their (namespace, id) key had collisions
    for key, stories_with_key in seen.items():
        if len(stories_with_key) > 1:
            # Collision: reject all stories with this key
            namespace, base_id = key
            full_id = f"{namespace}/{base_id}" if namespace else base_id
            error_msg = f"Duplicate story ID across namespace+ID: {full_id} appears {len(stories_with_key)} times"
            errors.append(error_msg)
            rejected.extend(stories_with_key)
        else:
            # No collision: accept this story
            accepted.append(stories_with_key[0])

    return accepted, rejected, errors
