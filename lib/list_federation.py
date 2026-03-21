"""lib/list_federation.py — Federation configuration summarizer (US-665).

Reads .spiral/federation.toml and prd.json to summarize federated setup:
sub-project names, story counts per project, and worker allocations.

Usage (Python API):
    from list_federation import load_federation_config, build_summary
    config = load_federation_config(Path(".spiral/federation.toml"))
    summary = build_summary(config, story_counts)

CLI usage (via main.py):
    spiral list-federation [--config .spiral/federation.toml] [--prd prd.json]
"""

import tomllib
from pathlib import Path
from typing import Any


def load_federation_config(config_path: Path) -> dict[str, Any]:
    """Load federation.toml and return parsed config.

    Args:
        config_path: Path to federation.toml

    Returns:
        dict with 'sub_projects' key: list of {name: str, workers: int}

    Raises:
        FileNotFoundError: if config_path does not exist
        ValueError: if config is malformed
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Federation config not found: {config_path}")

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    sub_projects: list[dict[str, Any]] = []
    for entry in raw.get("sub_projects", []):
        name = entry.get("name", "")
        if not name:
            raise ValueError("sub_projects entry missing 'name' field")
        workers = int(entry.get("workers", 1))
        sub_projects.append({"name": name, "workers": workers})

    return {"sub_projects": sub_projects}


def count_stories_by_project(stories: list[dict[str, Any]]) -> dict[str, int]:
    """Count active stories by sub_project field.

    Empty sub_project defaults to 'default'.

    Args:
        stories: list of story dicts from prd.json userStories

    Returns:
        dict mapping sub_project name -> story count
    """
    counts: dict[str, int] = {}
    for story in stories:
        if not isinstance(story, dict):
            continue
        sub_project = story.get("sub_project") or "default"
        sub_project = str(sub_project).strip() or "default"
        counts[sub_project] = counts.get(sub_project, 0) + 1
    return counts


def validate_consistency(
    config_projects: set[str],
    story_projects: set[str],
) -> list[str]:
    """Detect prd.json sub_project values not defined in federation.toml.

    'default' is always allowed even if not in config.

    Args:
        config_projects: set of sub_project names from federation.toml
        story_projects: set of sub_project names found in prd.json

    Returns:
        list of inconsistency error messages (empty = consistent)
    """
    errors: list[str] = []
    for proj in sorted(story_projects):
        if proj == "default":
            continue
        if proj not in config_projects:
            errors.append(
                f"prd.json references sub_project '{proj}' not defined in federation.toml"
            )
    return errors


def build_summary(
    config: dict[str, Any],
    story_counts: dict[str, int],
) -> dict[str, Any]:
    """Build the final JSON summary output.

    Args:
        config: parsed federation config from load_federation_config()
        story_counts: per-project story counts from count_stories_by_project()

    Returns:
        {sub_projects: [{name, story_count, workers}], total_stories, total_workers}
    """
    result_projects: list[dict[str, Any]] = []
    for proj in config["sub_projects"]:
        name: str = proj["name"]
        result_projects.append(
            {
                "name": name,
                "story_count": story_counts.get(name, 0),
                "workers": proj["workers"],
            }
        )

    # Include any prd.json projects not in config (e.g. 'default') as passthrough
    config_names = {p["name"] for p in config["sub_projects"]}
    for name, count in sorted(story_counts.items()):
        if name not in config_names:
            result_projects.append(
                {
                    "name": name,
                    "story_count": count,
                    "workers": 0,
                }
            )

    total_stories = sum(p["story_count"] for p in result_projects)
    total_workers = sum(p["workers"] for p in result_projects)

    return {
        "sub_projects": result_projects,
        "total_stories": total_stories,
        "total_workers": total_workers,
    }
