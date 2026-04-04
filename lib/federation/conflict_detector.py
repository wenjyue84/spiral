"""Detect file conflicts across sub-projects in a federated PRD (US-1044)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileConflict:
    """A conflict where 2+ sub-projects plan to touch the same file."""

    file_path: str
    sub_projects: set[str]
    story_ids: list[str]
    suggested_resolution: str = field(default="")

    def to_dict(self) -> dict[str, object]:
        """Serialize to plain dict for YAML/JSON output."""
        return {
            "file_path": self.file_path,
            "sub_projects": sorted(self.sub_projects),
            "story_ids": self.story_ids,
            "suggested_resolution": self.suggested_resolution,
        }


def _suggest_resolution(file_path: str, sub_projects: set[str]) -> str:
    """Generate a human-readable merge strategy for the conflict."""
    ordered = sorted(sub_projects)
    first = ordered[0]
    rest = ", ".join(ordered[1:])
    if "test" in file_path or file_path.startswith("tests/"):
        return f"Shared test file: extract shared fixtures into a common conftest; merge {first} first, then {rest}."
    if file_path.endswith(("__init__.py", ".cfg", ".toml", ".ini", ".yaml", ".yml", ".json")):
        return (
            f"Shared config/init file: coordinate edits to avoid semantic conflicts; "
            f"merge {first} with manual review of overlapping sections."
        )
    return (
        f"Sequential merge order recommended: {' \u2192 '.join(ordered)}. "
        f"Review overlapping changes before merging later sub-projects."
    )


def detect_file_conflicts(prd_dict: dict[str, object]) -> list[FileConflict]:
    """Analyze stories by sub_project; return conflicts where 2+ sub-projects touch the same file."""
    file_map: dict[str, dict[str, list[str]]] = {}

    stories = prd_dict.get("userStories", [])
    if not isinstance(stories, list):
        return []

    for story in stories:
        if not isinstance(story, dict):
            continue
        sub = str(story.get("sub_project", "default"))
        story_id = str(story.get("id", ""))
        files_touch = story.get("filesTouch", [])
        if not isinstance(files_touch, list):
            continue
        for f in files_touch:
            file_path = str(f)
            if file_path not in file_map:
                file_map[file_path] = {}
            if sub not in file_map[file_path]:
                file_map[file_path][sub] = []
            file_map[file_path][sub].append(story_id)

    conflicts: list[FileConflict] = []
    for file_path, subs_map in sorted(file_map.items()):
        if len(subs_map) >= 2:
            sub_projects = set(subs_map.keys())
            story_ids = [sid for sids in subs_map.values() for sid in sids]
            conflicts.append(
                FileConflict(
                    file_path=file_path,
                    sub_projects=sub_projects,
                    story_ids=story_ids,
                    suggested_resolution=_suggest_resolution(file_path, sub_projects),
                )
            )
    return conflicts
