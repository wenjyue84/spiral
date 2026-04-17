#!/usr/bin/env python3
"""write_ralph_lessons.py — Generate a lessons sidecar file for Ralph workers.

Reads .spiral/learned_lessons.jsonl, finds top-K lessons matching a story,
and writes them to .spiral/ralph-lessons-<story_id>.md.

Usage:
    python lib/write_ralph_lessons.py \
        --story-json '{"id":"US-123","title":"..."}' \
        --lessons .spiral/learned_lessons.jsonl \
        --output .spiral/ralph-lessons-US-123.md \
        --top-k 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from learned_lessons import query_lessons


def write_lessons_sidecar(
    story: dict[str, Any],
    lessons_path: Path,
    output_path: Path,
    top_k: int = 3,
) -> bool:
    """Write a Markdown sidecar with relevant lessons for a story.

    Returns True if lessons were written, False if no matches or disabled.
    """
    if os.environ.get("SPIRAL_LESSON_INJECTION", "true").lower() == "false":
        return False

    if not lessons_path.exists():
        return False

    matches = query_lessons(lessons_path, story, top_k=top_k)
    if not matches:
        return False

    lines = [
        "## Learned Lessons (from past failures)",
        "",
        "These lessons were extracted from previous SPIRAL iterations.",
        "Avoid repeating these mistakes:",
        "",
    ]
    for i, lesson in enumerate(matches, 1):
        cat = lesson.get("error_category", "error")
        pattern = lesson.get("pattern", "")
        fix = lesson.get("fix", "")
        lines.append(f"{i}. **[{cat}]** {pattern}")
        if fix:
            lines.append(f"   - Fix: {fix}")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Ralph lessons sidecar")
    parser.add_argument("--story-json", required=True, help="Story JSON string or @file")
    parser.add_argument("--lessons", default=".spiral/learned_lessons.jsonl")
    parser.add_argument("--output", required=True, help="Output .md path")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    story_src = args.story_json
    if story_src.startswith("@"):
        story = json.loads(Path(story_src[1:]).read_text(encoding="utf-8"))
    else:
        story = json.loads(story_src)

    wrote = write_lessons_sidecar(
        story=story,
        lessons_path=Path(args.lessons),
        output_path=Path(args.output),
        top_k=args.top_k,
    )
    sys.exit(0 if wrote else 1)


if __name__ == "__main__":
    main()
