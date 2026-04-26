"""lib/federated_search.py — Federated full-text story search across main and sub-projects.

Loads prd.json and recursively resolves prd.include references, then scores each
story against a query using rapidfuzz token_set_ratio for fuzzy matching.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

# Fields to search within each story
_SEARCH_FIELDS = ("title", "description", "acceptanceCriteria")


def _score_story(story: dict[str, Any], query: str) -> int:
    """Return a fuzzy match score (0-100) for a story against a query."""
    query_lower = query.lower()
    best = 0
    for field in _SEARCH_FIELDS:
        value = story.get(field, "")
        if isinstance(value, list):
            text = " ".join(str(v) for v in value)
        else:
            text = str(value) if value else ""
        score = fuzz.token_set_ratio(query_lower, text.lower())
        if score > best:
            best = score
    return best


def _load_prd(prd_path: str) -> dict[str, Any]:
    """Load a prd.json file, returning parsed dict."""
    with open(prd_path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def search_across_projects(
    query: str,
    prd_root: str,
    min_score: int = 30,
    project_filter: str | None = None,
    _visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Search for stories matching query across prd_root and all prd.include sub-projects.

    Args:
        query: Search query string.
        prd_root: Path to the root prd.json file.
        min_score: Minimum fuzzy score (0-100) to include a result.
        project_filter: Optional sub-project name filter (matches prd.include filename stem).
        _visited: Internal set of already-visited prd paths (cycle detection).

    Returns:
        List of result dicts with keys: story_id, project, title, score, description.
        Sorted by score descending.
    """
    if _visited is None:
        _visited = set()

    abs_path = str(Path(prd_root).resolve())
    if abs_path in _visited:
        return []
    _visited.add(abs_path)

    results: list[dict[str, Any]] = []
    prd_dir = os.path.dirname(abs_path)

    try:
        data = _load_prd(abs_path)
    except (OSError, json.JSONDecodeError):
        return []

    # Determine project name from filename stem (main prd.json → "main")
    stem = Path(abs_path).stem
    project_name = "main" if stem == "prd" else stem

    # Apply project filter if specified
    include_this_project = project_filter is None or project_name == project_filter

    if include_this_project:
        for story in data.get("userStories", []):
            score = _score_story(story, query)
            if score >= min_score:
                results.append(
                    {
                        "story_id": story.get("id", ""),
                        "project": project_name,
                        "title": story.get("title", ""),
                        "score": score,
                        "description": (story.get("description") or "")[:120],
                    }
                )

    # Recursively load prd.include sub-projects
    for include_path in data.get("prd.include", []):
        sub_path = os.path.join(prd_dir, include_path)
        sub_results = search_across_projects(
            query,
            sub_path,
            min_score=min_score,
            project_filter=project_filter,
            _visited=_visited,
        )
        results.extend(sub_results)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
