"""lib/research/phase_r_federated.py — Merge per-sub-project Phase R research outputs.

Combines research outputs from multiple sub-projects into a single
_research_output.json, adding the sub_project field to each story and
detecting cross-sub-project duplicate story IDs.

CLI usage:
    python lib/research/phase_r_federated.py \\
        --sub-projects api,frontend \\
        --research-dir .spiral/ \\
        --output _research_output.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def merge_federated_research(
    sub_project_outputs: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Merge per-sub-project research outputs into a single result.

    Args:
        sub_project_outputs: List of dicts with {"sub_project": str, "stories": list}.

    Returns:
        Tuple of (merged_output, conflict_warnings).
        merged_output: {"stories": [...]} where each story has sub_project field.
        conflict_warnings: IDs that appear in multiple sub-projects.
    """
    all_stories: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}  # story_id -> first sub_project name
    conflicts: list[str] = []

    for entry in sub_project_outputs:
        sub_project = str(entry.get("sub_project", ""))
        stories = entry.get("stories", [])
        for story in stories:
            if not isinstance(story, dict):
                continue
            story_copy = dict(story)
            story_copy["sub_project"] = sub_project

            sid = story_copy.get("id", "")
            if sid:
                if sid in seen_ids:
                    conflicts.append(f"Story ID '{sid}' appears in both '{seen_ids[sid]}' and '{sub_project}'")
                else:
                    seen_ids[sid] = sub_project

            all_stories.append(story_copy)

    return {"stories": all_stories}, conflicts


def load_sub_project_research(research_dir: Path, sub_project: str) -> dict[str, Any]:
    """Load per-sub-project research JSON from _research_<sub_project>.json.

    Args:
        research_dir: Directory containing per-sub-project research files.
        sub_project: Sub-project name used as filename part.

    Returns:
        Dict with "stories" list. Returns {"stories": []} if file not found.
    """
    output_file = research_dir / f"_research_{sub_project}.json"
    if not output_file.exists():
        return {"stories": []}
    with open(output_file, encoding="utf-8") as f:
        try:
            data: Any = json.load(f)
        except json.JSONDecodeError:
            return {"stories": []}
    if not isinstance(data, dict):
        return {"stories": []}
    return data


def run_federated_research_merge(
    sub_projects: list[str],
    research_dir: Path,
    output_path: Path,
) -> list[str]:
    """Load per-sub-project research files and merge into one output file.

    Args:
        sub_projects: List of sub-project names.
        research_dir: Directory containing _research_<name>.json files.
        output_path: Where to write merged _research_output.json.

    Returns:
        List of conflict warning strings (empty if no conflicts).
    """
    sub_project_outputs: list[dict[str, Any]] = []
    for name in sub_projects:
        data = load_sub_project_research(research_dir, name)
        sub_project_outputs.append({"sub_project": name, "stories": data.get("stories", [])})

    merged, conflicts = merge_federated_research(sub_project_outputs)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")

    return conflicts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge per-sub-project Phase R research outputs into _research_output.json"
    )
    parser.add_argument(
        "--sub-projects",
        required=True,
        help="Comma-separated list of sub-project names",
    )
    parser.add_argument(
        "--research-dir",
        default=".",
        help="Directory containing _research_<name>.json files (default: .)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write merged _research_output.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for federated research merge."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    sub_projects = [s.strip() for s in args.sub_projects.split(",") if s.strip()]
    if not sub_projects:
        print("Error: --sub-projects must contain at least one name", file=sys.stderr)
        return 1

    research_dir = Path(args.research_dir)
    output_path = Path(args.output)

    conflicts = run_federated_research_merge(sub_projects, research_dir, output_path)
    for conflict in conflicts:
        print(f"CONFLICT: {conflict}", file=sys.stderr)

    try:
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        story_count = len(data.get("stories", []))
    except (json.JSONDecodeError, OSError):
        story_count = 0

    print(f"Merged {story_count} stories from {len(sub_projects)} sub-projects -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
