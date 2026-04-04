"""lib/spiral/phase_m.py — Phase M Python orchestration layer.

Wraps the story merge operation with federated dependency ordering (US-617).
Before merging candidates into prd.json, stories are topologically sorted so
that dependency stories are merged before the stories that depend on them.

The heavy-lifting merge logic remains in lib/prd/merge_stories.py; this module
provides the ordering pre-step as required by US-617 AC3.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Ensure lib/impl is importable
_IMPL_DIR = Path(__file__).resolve().parent.parent / "impl"
sys.path.insert(0, str(_IMPL_DIR))

from phase_m_federated_order import order_federated_stories_by_dependency  # noqa: E402


def validate_quota(
    candidates: list[dict[str, Any]],
    prd_path: str | Path = "prd.json",
) -> tuple[bool, str]:
    """Validate per-sub-project story quotas before merge.

    Reads SPIRAL_QUOTA_* environment variables (e.g. SPIRAL_QUOTA_FRONTEND=30)
    and ensures that adding candidates won't exceed any sub-project's quota.

    Args:
        candidates: Story dicts to merge.
        prd_path: Path to prd.json to load existing stories.

    Returns:
        Tuple of (valid: bool, message: str).
        - If valid, message is empty string
        - If invalid, message is "Quota exceeded for <subproject>: <current>/<limit>"

    Raises:
        ValueError: If quota is exceeded.
    """
    # Load quotas from environment (e.g. SPIRAL_QUOTA_FRONTEND=30)
    quotas: dict[str, int] = {}
    for key, value in os.environ.items():
        if key.startswith("SPIRAL_QUOTA_"):
            subproject = key.replace("SPIRAL_QUOTA_", "").lower()
            try:
                quotas[subproject] = int(value)
            except ValueError:
                pass  # Skip malformed quota values

    # If no quotas defined, validation passes
    if not quotas:
        return True, ""

    # Count current stories per sub_project in prd.json
    current_counts: dict[str, int] = defaultdict(int)
    prd_p = Path(prd_path)
    if prd_p.exists():
        try:
            with open(prd_p, encoding="utf-8") as f:
                prd_data = json.load(f)
            existing_stories: list[dict[str, Any]] = prd_data.get("userStories", [])
            for story in existing_stories:
                sub_project = story.get("sub_project", "").lower() if story.get("sub_project") else "default"
                current_counts[sub_project] += 1
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # Count candidate stories per sub_project
    candidate_counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        sub_project = candidate.get("sub_project", "").lower() if candidate.get("sub_project") else "default"
        candidate_counts[sub_project] += 1

    # Check quotas
    for subproject, limit in quotas.items():
        current = current_counts.get(subproject, 0)
        new_count = current + candidate_counts.get(subproject, 0)
        if new_count > limit:
            msg = f"Quota exceeded for {subproject}: {new_count}/{limit}"
            raise ValueError(msg)

    return True, ""


def prd_merge(
    candidates: list[dict[str, Any]],
    prd_path: str | Path = "prd.json",
    *,
    skip_ordering: bool = False,
    skip_quota: bool = False,
) -> list[dict[str, Any]]:
    """Merge story candidates into prd.json with federated dependency ordering.

    This is the Python-level entry point for Phase M. It:
    1. Validates per-sub-project quotas (unless skipped).
    2. Applies topological ordering to candidates (so dependencies merge first).
    3. Returns the ordered candidates for downstream merge processing.

    Args:
        candidates: Story dicts to merge (from Phase S validated output).
        prd_path: Path to prd.json (used for context; actual write is in merge_stories.py).
        skip_ordering: If True, skip the federated ordering step (for testing).
        skip_quota: If True, skip quota validation (for testing).

    Returns:
        Ordered list of candidates, ready for merge_stories.py to process.

    Raises:
        ValueError: If a circular dependency is detected or quota is exceeded.
    """
    # Validate quotas before proceeding
    if not skip_quota:
        validate_quota(candidates, prd_path)

    if skip_ordering or not candidates:
        return list(candidates)

    result: list[dict[str, Any]] = order_federated_stories_by_dependency(candidates)
    return result


def load_candidates(path: str | Path) -> list[dict[str, Any]]:
    """Load story candidates from a JSON file."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return list(data)
    stories: list[dict[str, Any]] = data.get("stories", data.get("userStories", []))
    return stories
