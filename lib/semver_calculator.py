"""lib/semver_calculator.py — Phase G Semantic Version Calculator (US-555).

Auto-bumps the project version based on story complexity scores and types.
Follows SemVer 2.0.0: breaking -> major, feature -> minor, fix -> patch.

Usage as module:
    from semver_calculator import calculate_next_version, generate_changelog_segment
    version = calculate_next_version("v1.2.3", stories)
    changelog = generate_changelog_segment(stories, "prd.json")

Usage as CLI:
    python lib/semver_calculator.py --previous-tag v1.2.3 --complexity-file story-complexity.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ── SemVer tier constants ────────────────────────────────────────────────────

TIER_FIX = 0
TIER_FEATURE = 1
TIER_BREAKING = 2

_TYPE_TO_TIER: dict[str, int] = {
    "fix": TIER_FIX,
    "feature": TIER_FEATURE,
    "breaking": TIER_BREAKING,
}

# ── Version parsing ──────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse_version(tag: str) -> tuple[int, int, int]:
    """Parse a semver tag like 'v1.2.3' or '1.2.3' into (major, minor, patch).

    Raises ValueError if the tag does not match SemVer 2.0.0 core format.
    """
    m = _SEMVER_RE.match(tag.strip())
    if not m:
        raise ValueError(f"Invalid semver tag: {tag!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# ── Core API ─────────────────────────────────────────────────────────────────


def calculate_next_version(previous_tag: str, stories: list[dict[str, Any]]) -> str:
    """Compute the next SemVer version from story types.

    Rules (SemVer 2.0.0):
        - Any story with type="breaking" -> bump major, reset minor & patch
        - Otherwise any type="feature"   -> bump minor, reset patch
        - Otherwise (all "fix")          -> bump patch

    The highest-tier change wins across all stories.

    Args:
        previous_tag: Previous version tag, e.g. "v1.2.3" or "1.2.3".
        stories: List of dicts with at least {story_id, score, type}.
                 type must be one of "breaking", "feature", or "fix".

    Returns:
        Next version string WITHOUT the 'v' prefix, e.g. "2.0.0".
    """
    major, minor, patch = _parse_version(previous_tag)

    # Determine highest tier across all stories
    highest_tier = TIER_FIX
    for story in stories:
        story_type = story.get("type", "fix")
        tier = _TYPE_TO_TIER.get(story_type, TIER_FIX)
        if tier > highest_tier:
            highest_tier = tier
        if highest_tier == TIER_BREAKING:
            break  # Can't go higher

    if highest_tier == TIER_BREAKING:
        return f"{major + 1}.0.0"
    elif highest_tier == TIER_FEATURE:
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def generate_changelog_segment(
    stories: list[dict[str, Any]],
    prd_path: str,
) -> str:
    """Generate a markdown changelog segment grouped by semver tier.

    Groups stories into Breaking Changes, Features, and Fixes sections.
    Enriches each entry with the story description from prd.json when available.

    Args:
        stories: List of dicts with {story_id, score, type}.
        prd_path: Path to prd.json for enriching story descriptions.

    Returns:
        Markdown-formatted changelog segment string.
    """
    # Load PRD for description lookup
    prd_descriptions: dict[str, str] = {}
    prd_file = Path(prd_path)
    if prd_file.exists():
        try:
            with open(prd_file, encoding="utf-8") as f:
                prd = json.load(f)
            for s in prd.get("userStories", []):
                sid = s.get("id", "")
                title = s.get("title", "")
                desc = s.get("description", "")
                # Prefer title, fall back to first 80 chars of description
                prd_descriptions[sid] = title or (desc[:80] + "..." if len(desc) > 80 else desc)
        except (json.JSONDecodeError, OSError):
            pass

    # Group stories by tier
    breaking: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []

    for story in stories:
        story_type = story.get("type", "fix")
        if story_type == "breaking":
            breaking.append(story)
        elif story_type == "feature":
            features.append(story)
        else:
            fixes.append(story)

    lines: list[str] = []

    if breaking:
        lines.append("### Breaking Changes\n")
        for s in breaking:
            sid = s.get("story_id", "unknown")
            desc = prd_descriptions.get(sid, "")
            entry = f"- **{sid}**"
            if desc:
                entry += f": {desc}"
            lines.append(entry + "\n")
        lines.append("\n")

    if features:
        lines.append("### Features\n")
        for s in features:
            sid = s.get("story_id", "unknown")
            desc = prd_descriptions.get(sid, "")
            entry = f"- **{sid}**"
            if desc:
                entry += f": {desc}"
            lines.append(entry + "\n")
        lines.append("\n")

    if fixes:
        lines.append("### Fixes\n")
        for s in fixes:
            sid = s.get("story_id", "unknown")
            desc = prd_descriptions.get(sid, "")
            entry = f"- **{sid}**"
            if desc:
                entry += f": {desc}"
            lines.append(entry + "\n")
        lines.append("\n")

    return "".join(lines)


def calculate_next_version_from_results_tsv(previous_tag: str, results_tsv_path: str) -> str:
    """Calculate next SemVer version based on retry_count from results.tsv.

    Deterministic calculation: reads results.tsv and counts stories with
    retry_count >= 3. If count >= 2, bumps minor version. Otherwise, bumps patch.

    This function is pure (deterministic) — identical inputs always produce
    identical outputs, independent of timestamps or system state.

    Args:
        previous_tag: Previous version tag, e.g. "v1.2.3" or "1.2.3".
        results_tsv_path: Path to results.tsv file with columns:
                         story_id, retry_count, [other columns ignored]

    Returns:
        Next version string WITHOUT the 'v' prefix, e.g. "1.1.0" or "1.0.1".

    Raises:
        ValueError: If version tag is invalid or retry_count cannot be parsed.
        FileNotFoundError: If results.tsv does not exist.
    """
    import csv

    major, minor, patch = _parse_version(previous_tag)

    # Read results.tsv and count stories with retry_count >= 3
    results_path = Path(results_tsv_path)
    if not results_path.exists():
        raise FileNotFoundError(f"results.tsv not found: {results_tsv_path}")

    retry_count_threshold_stories = 0
    with open(results_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader is None:
            raise ValueError(f"Failed to parse results.tsv: {results_tsv_path}")

        for row in reader:
            try:
                retry_count = int(row.get("retry_count", "0"))
                if retry_count >= 3:
                    retry_count_threshold_stories += 1
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid retry_count in results.tsv: {row.get('retry_count')}") from e

    # Determine bump tier: >= 2 stories with retry_count >= 3 → minor, else → patch
    if retry_count_threshold_stories >= 2:
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


# ── CLI entrypoint ───────────────────────────────────────────────────────────


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase G Semantic Version Calculator (US-555)",
    )
    parser.add_argument(
        "--previous-tag",
        required=True,
        metavar="TAG",
        help="Previous version tag (e.g. v1.2.3)",
    )
    parser.add_argument(
        "--complexity-file",
        required=True,
        metavar="FILE",
        help="Path to story-complexity.json with scored stories",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="FILE",
        help="Path to prd.json for changelog enrichment (default: prd.json)",
    )
    parser.add_argument(
        "--changelog",
        action="store_true",
        help="Also print changelog segment",
    )

    args = parser.parse_args()

    complexity_path = Path(args.complexity_file)
    if not complexity_path.exists():
        print(f"ERROR: {args.complexity_file} not found", file=sys.stderr)
        return 1

    with open(complexity_path, encoding="utf-8") as f:
        stories: list[dict[str, Any]] = json.load(f)

    version = calculate_next_version(args.previous_tag, stories)
    print(version)

    if args.changelog:
        segment = generate_changelog_segment(stories, args.prd)
        if segment.strip():
            print()
            print(segment, end="")

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
