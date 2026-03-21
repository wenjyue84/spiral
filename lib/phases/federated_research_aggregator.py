"""federated_research_aggregator.py — Merge per-sub-project Gemini research outputs.

Combines multiple _research_<sub_project>.json files into a single
_research_output.json with sub_project field on each discovered story.
Detects duplicate story IDs across sub-projects and emits warnings.

CLI usage (called from phase_r_federated.sh):
    python lib/phases/federated_research_aggregator.py \\
        --outputs-dir /tmp/.spiral \\
        --sub-projects api frontend \\
        --output /tmp/.spiral/_research_output.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Union


def aggregate_federated_research(
    sub_project_outputs: Mapping[str, Union[str, Path]],
) -> tuple[dict[str, Any], list[str]]:
    """Merge per-sub-project research JSON files into one output.

    Args:
        sub_project_outputs: Mapping of sub_project_name -> path to JSON file
            containing {"stories": [...]}

    Returns:
        Tuple of (merged_output, warnings).
        merged_output: {"stories": [...]} with sub_project field on each story.
        warnings: List of warning strings for missing files, invalid JSON,
            or duplicate story IDs across sub-projects.
    """
    all_stories: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}  # story_id -> first sub_project that claimed it
    warnings: list[str] = []

    for sub_project, path in sub_project_outputs.items():
        p = Path(path)
        if not p.exists():
            warnings.append(f"[R/federated] Missing research output for sub-project '{sub_project}': {p}")
            continue

        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"[R/federated] Invalid JSON for sub-project '{sub_project}': {exc}")
            continue

        stories = data.get("stories", [])
        for story in stories:
            if not isinstance(story, dict):
                continue
            story_copy = dict(story)
            story_copy["sub_project"] = sub_project

            sid = story_copy.get("id") or ""
            if sid:
                if sid in seen_ids:
                    warnings.append(
                        f"[R/federated] Duplicate story ID '{sid}' across sub-projects "
                        f"'{seen_ids[sid]}' and '{sub_project}' — flagged as conflict"
                    )
                else:
                    seen_ids[sid] = sub_project

            all_stories.append(story_copy)

    return {"stories": all_stories}, warnings


def _build_sub_project_map(outputs_dir: Path, sub_projects: list[str]) -> Mapping[str, Path]:
    """Build mapping of sub_project -> expected output file path."""
    return {sp: outputs_dir / f"_research_{sp}.json" for sp in sub_projects}


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Aggregate federated per-sub-project research outputs")
    parser.add_argument(
        "--outputs-dir",
        required=True,
        help="Directory containing _research_<sub_project>.json files",
    )
    parser.add_argument(
        "--sub-projects",
        nargs="+",
        required=True,
        help="List of sub-project names",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write aggregated _research_output.json",
    )
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir)
    sub_project_map = _build_sub_project_map(outputs_dir, args.sub_projects)

    merged, warnings = aggregate_federated_research(sub_project_map)

    for warning in warnings:
        print(warning, file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

    story_count = len(merged.get("stories", []))
    print(f"[R/federated] Aggregated {story_count} stories from {len(args.sub_projects)} sub-projects → {out_path}")


if __name__ == "__main__":
    main()
