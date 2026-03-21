"""Phase G: Generate Release Notes from Completed Stories.

Extracts stories with passes=true from prd.json, groups by _source field,
and compiles into RELEASE_NOTES.md with semantic version header and story details.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.phases.phase_g_version_bump import parse_version_from_changelog
from lib.results_tsv import parse_results_tsv


def load_prd(prd_path: str = "prd.json") -> dict[str, Any]:
    """Load prd.json file.

    Args:
        prd_path: Path to prd.json file

    Returns:
        Parsed PRD dictionary

    Raises:
        ValueError: If file not found or invalid JSON
    """
    prd_file = Path(prd_path)
    if not prd_file.exists():
        raise ValueError(f"prd.json not found at {prd_path}")

    with open(prd_file, encoding="utf-8") as f:
        result: dict[str, Any] = json.load(f)
        return result


def get_story_metadata(story_id: str, results_path: str = "results.tsv") -> dict[str, str]:
    """Get tokens and cost for a story from results.tsv.

    Args:
        story_id: Story ID to look up
        results_path: Path to results.tsv

    Returns:
        Dict with 'tokens' and 'cost' keys (empty strings if not found)
    """
    try:
        records = parse_results_tsv(results_path)
    except Exception:
        return {"tokens": "", "cost": ""}

    # Find the first passing record for this story
    for record in records:
        if record.story_id == story_id and record.status == "pass":
            tokens = record.cache_read_tokens or record.cache_creation_tokens or ""
            cost = ""  # Cost calculation would go here if available
            return {"tokens": tokens, "cost": cost}

    return {"tokens": "", "cost": ""}


def format_story_entry(story: dict[str, Any], metadata: dict[str, str]) -> str:
    """Format a single story entry for release notes.

    Args:
        story: Story dict from prd.json
        metadata: Metadata dict with 'tokens' and 'cost'

    Returns:
        Formatted story entry string
    """
    story_id = story.get("id", "")
    title = story.get("title", "")
    tokens = metadata.get("tokens", "")
    cost = metadata.get("cost", "")

    # Format: - US-123: Title (X tokens, Y cost)
    if tokens and cost:
        entry = f"- {story_id}: {title} ({tokens} tokens, {cost})"
    elif tokens:
        entry = f"- {story_id}: {title} ({tokens} tokens)"
    else:
        entry = f"- {story_id}: {title}"

    # Add acceptance criteria as sub-bullets
    acs = story.get("acceptanceCriteria", [])
    if isinstance(acs, list):
        for ac in acs:
            entry += f"\n  - {ac}"

    return entry


def generate_release_notes(
    prd_path: str = "prd.json",
    output_path: str = "RELEASE_NOTES.md",
    changelog_path: str = "CHANGELOG.md",
    results_path: str = "results.tsv",
) -> str:
    """Generate RELEASE_NOTES.md from completed stories.

    Args:
        prd_path: Path to prd.json file
        output_path: Path where RELEASE_NOTES.md will be written
        changelog_path: Path to CHANGELOG.md (for version extraction)
        results_path: Path to results.tsv (for token/cost data)

    Returns:
        Content written to RELEASE_NOTES.md

    Raises:
        ValueError: If prd.json or CHANGELOG.md not found
    """
    # Load PRD
    prd = load_prd(prd_path)

    # Get version from CHANGELOG.md
    try:
        version = parse_version_from_changelog(changelog_path)
    except ValueError:
        version = "0.0.0"  # Fallback version if CHANGELOG.md not found

    # Filter completed stories (passes=true)
    completed_stories = [s for s in prd.get("userStories", []) if s.get("passes", False)]

    # Group by _source
    stories_by_source: dict[str, list[dict[str, Any]]] = {}
    for story in completed_stories:
        source = story.get("_source", "seed")
        if source not in stories_by_source:
            stories_by_source[source] = []
        stories_by_source[source].append(story)

    # Build release notes content
    lines = [f"# Release Notes - v{version}\n"]

    # Define source order and names
    source_names = {
        "test-fix": "Bug Fixes & Regression Prevention",
        "research": "Research & Validation",
        "ai-example": "AI-Generated Examples & Features",
        "test-story": "Test Coverage Improvements",
        "seed": "Core Features",
    }

    # Output sections in defined order
    for source in source_names:
        if source not in stories_by_source:
            continue

        stories = stories_by_source[source]
        section_name = source_names[source]

        lines.append(f"\n## {section_name}\n")
        for story in stories:
            metadata = get_story_metadata(story.get("id", ""), results_path)
            entry = format_story_entry(story, metadata)
            lines.append(entry)

    # Handle any sources not in the predefined list
    for source in stories_by_source:
        if source not in source_names:
            stories = stories_by_source[source]
            lines.append(f"\n## {source}\n")
            for story in stories:
                metadata = get_story_metadata(story.get("id", ""), results_path)
                entry = format_story_entry(story, metadata)
                lines.append(entry)

    content = "\n".join(lines) + "\n"

    # Write to output file
    output_file = Path(output_path)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)

    return content


def main() -> None:
    """Entry point for release notes generation."""
    try:
        content = generate_release_notes()
        print(f"✓ Generated RELEASE_NOTES.md ({len(content)} bytes)")
    except ValueError as e:
        print(f"❌ Failed to generate release notes: {e}")
        raise


if __name__ == "__main__":
    main()
