#!/usr/bin/env python3
"""learning_extractor.py — Parse results.tsv and extract successful patterns.

Reads results.tsv for zero-retry stories and appends deduplicated patterns to
learning.md. This is the data-extraction half of the Phase L learning loop.
"""

import csv
import re
from pathlib import Path


def _ensure_learning_md(learning_md_path: Path) -> None:
    """Create learning.md from template if it doesn't exist.

    Args:
        learning_md_path: Path to learning.md
    """
    if learning_md_path.exists():
        return

    template_path = Path(__file__).parent.parent / "templates" / "learning.md"
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
    else:
        content = "# Learning Patterns\n\n## Successful Patterns\n\n## Failure Recovery\n\n## Scope Reduction Tips\n\n"

    learning_md_path.parent.mkdir(parents=True, exist_ok=True)
    learning_md_path.write_text(content, encoding="utf-8")


def _get_existing_story_ids(learning_md_path: Path) -> set[str]:
    """Extract all existing story IDs from learning.md.

    Args:
        learning_md_path: Path to learning.md

    Returns:
        Set of story IDs already in learning.md
    """
    if not learning_md_path.exists():
        return set()

    content = learning_md_path.read_text(encoding="utf-8")
    pattern = r"story_id:\s*([A-Za-z]+-\d+)"
    matches = re.findall(pattern, content)
    return set(matches)


def extract_patterns(
    results_tsv_path: Path,
    learning_md_path: Path,
    min_confidence: float = 0.7,
) -> int:
    """Extract patterns from results.tsv and append to learning.md.

    Reads results.tsv for rows where retry_num == '0' (first-try successes),
    deduplicates by story_id, and appends entries to the successful_patterns
    section of learning.md.

    Args:
        results_tsv_path: Path to results.tsv
        learning_md_path: Path to learning.md (created if absent)
        min_confidence: Confidence threshold for inclusion (unused, for future use)

    Returns:
        Number of new patterns added
    """
    # Ensure learning.md exists with template
    _ensure_learning_md(learning_md_path)

    if not results_tsv_path.exists():
        return 0

    # Get existing story IDs to avoid duplicates
    existing_ids = _get_existing_story_ids(learning_md_path)

    # Parse results.tsv
    new_patterns = []
    try:
        with open(results_tsv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            if reader.fieldnames is None:
                return 0

            for row in reader:
                # Filter for first-try successes
                retry_num_str = (row.get("retry_num") or "").strip()
                if retry_num_str != "0":
                    continue

                story_id = (row.get("story_id") or "").strip()
                if not story_id or story_id in existing_ids:
                    continue

                model_used = (row.get("model") or "").strip()
                story_title = (row.get("story_title") or "").strip()

                # Create pattern entry
                pattern_entry = {
                    "story_id": story_id,
                    "model_used": model_used,
                    "story_title": story_title,
                }
                new_patterns.append(pattern_entry)
                existing_ids.add(story_id)

    except (OSError, KeyError, ValueError):
        return 0

    if not new_patterns:
        return 0

    # Append to learning.md under successful_patterns section
    content = learning_md_path.read_text(encoding="utf-8")

    # Find the successful_patterns section
    section_marker = "## Successful Patterns"
    if section_marker not in content:
        # If section doesn't exist, add it before failure recovery
        content = content.replace(
            "## Failure Recovery",
            f"{section_marker}\n\n## Failure Recovery",
        )

    # Find position to insert (after section header, before next section)
    lines = content.split("\n")
    insert_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(section_marker):
            insert_idx = i + 1
            # Skip blank lines
            while insert_idx < len(lines) and lines[insert_idx].strip() == "":
                insert_idx += 1
            # Move back to first blank line for insertion
            insert_idx = i + 1
            break

    if insert_idx == -1:
        return 0

    # Format and insert new entries
    new_entries = []
    for pattern in new_patterns:
        entry = (
            f"- story_id: {pattern['story_id']}, model_used: {pattern['model_used']}, title: {pattern['story_title']}"
        )
        new_entries.append(entry)

    lines_to_insert = new_entries

    # Insert entries
    for entry_line in reversed(lines_to_insert):
        lines.insert(insert_idx, entry_line)

    updated_content = "\n".join(lines)
    learning_md_path.write_text(updated_content, encoding="utf-8")

    return len(new_patterns)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: learning_extractor.py <results.tsv> <learning.md>")
        sys.exit(1)

    results_path = Path(sys.argv[1])
    learning_path = Path(sys.argv[2])

    count = extract_patterns(results_path, learning_path)
    print(f"Added {count} new patterns to learning.md")
