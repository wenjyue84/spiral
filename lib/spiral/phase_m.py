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
from pathlib import Path
from typing import Any

# Ensure lib/impl is importable
_IMPL_DIR = Path(__file__).resolve().parent.parent / "impl"
sys.path.insert(0, str(_IMPL_DIR))

from phase_m_federated_order import order_federated_stories_by_dependency  # noqa: E402


def prd_merge(
    candidates: list[dict[str, Any]],
    prd_path: str | Path = "prd.json",
    *,
    skip_ordering: bool = False,
) -> list[dict[str, Any]]:
    """Merge story candidates into prd.json with federated dependency ordering.

    This is the Python-level entry point for Phase M. It:
    1. Applies topological ordering to candidates (so dependencies merge first).
    2. Returns the ordered candidates for downstream merge processing.

    Args:
        candidates: Story dicts to merge (from Phase S validated output).
        prd_path: Path to prd.json (used for context; actual write is in merge_stories.py).
        skip_ordering: If True, skip the federated ordering step (for testing).

    Returns:
        Ordered list of candidates, ready for merge_stories.py to process.

    Raises:
        ValueError: If a circular dependency is detected in candidate stories.
    """
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
