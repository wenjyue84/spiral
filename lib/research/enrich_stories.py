#!/usr/bin/env python3
"""
SPIRAL — Story Enrichment (Phase E)

For each validated story with estimatedComplexity="medium" or sparse technicalNotes (<2 items),
calls Claude to:
  1. Rewrite vague acceptance criteria to be independently runnable
  2. Add exact file paths and test commands to technicalNotes
  3. Split stories touching 3+ files into 2 atomic stories

Runs between Phase S (validate) and Phase M (merge).
Gated by SPIRAL_STORY_ENRICHMENT=true.

Usage:
  python enrich_stories.py --validated-in .spiral/_validated_stories.json \\
                           --enriched-out .spiral/_enriched_stories.json
  python enrich_stories.py --validated-in ... --enriched-out ... --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")

ENRICH_PROMPT = """\
You are a story quality reviewer for an autonomous AI coding system called SPIRAL.
Ralph, the implementation agent, uses your output to implement stories. Ralph is
powered by a small/cheap model (haiku or sonnet), so stories must be crystal-clear.

Review the story JSON below and do EXACTLY ONE of the following:

**ACTION A — SPLIT**: If this story touches 3 or more source files OR would take a
senior engineer more than 15 minutes to implement cleanly, split it into exactly
2 smaller atomic stories.

**ACTION B — ENRICH**: Otherwise, enrich this story:
  1. Rewrite any acceptance criteria that are not independently verifiable by a single command.
  2. Add or improve technicalNotes so they include:
     - At least one "File to edit: <exact-relative-path> (<function or section>)" entry
     - At least one "Test command: <exact runnable command that verifies an AC>"
  3. Set estimatedComplexity to "small" or "medium" (never "large").
  4. Trim acceptanceCriteria to at most 4 items (keep the most specific ones).

Story to review:
{story_json}

Output ONLY valid JSON in one of these two shapes — no prose, no markdown fences:

Shape A (split):
{{"action": "split", "stories": [<story_object_1>, <story_object_2>]}}

Shape B (enrich):
{{"action": "enrich", "story": <enriched_story_object>}}

Story object schema:
{{
  "title": "Short imperative title (max 80 chars)",
  "priority": "<same as input>",
  "description": "2-3 sentences explaining what and why",
  "acceptanceCriteria": ["<independently runnable criterion>"],
  "technicalNotes": [
    "File to edit: path/to/file.py (function_name)",
    "Test command: uv run pytest tests/test_X.py::test_name -v"
  ],
  "filesTouch": ["path/to/file.py", "tests/test_file.py"],
  "dependencies": [],
  "estimatedComplexity": "small|medium"
}}

Rules:
- estimatedComplexity MUST be "small" or "medium" — never "large"
- Max 4 acceptance criteria per story
- Each AC must be runnable/checkable with a single shell command
- technicalNotes MUST include at least one file path and one test command
- filesTouch MUST list every file the story creates or modifies (implementation + test files)
- If splitting, each sub-story must independently satisfy its own acceptance criteria
- Preserve the original _source, dependencies, and priority fields
"""


def _should_enrich(story: dict[str, Any]) -> bool:
    """Return True if the story needs enrichment (medium complexity, sparse technicalNotes, or no filesTouch)."""
    complexity = story.get("estimatedComplexity", "")
    tech_notes = story.get("technicalNotes") or []
    files_to_touch = story.get("filesTouch") or []
    # Enrich if: medium+ complexity OR sparse technicalNotes OR no filesTouch
    return complexity in ("medium", "large") or len(tech_notes) < 2 or len(files_to_touch) == 0


def _claude_cmd() -> str:
    """Return the Claude CLI executable, using .cmd on Windows."""
    import shutil

    if sys.platform == "win32":
        return shutil.which("claude.cmd") or shutil.which("claude") or "claude.cmd"
    return shutil.which("claude") or "claude"


def call_claude(prompt: str, model: str) -> str:
    """Call Claude CLI with prompt via stdin (safe on Windows — avoids angle-bracket interpretation)."""
    cmd = [
        _claude_cmd(),
        "-p",
        "--model",
        model,
        "--max-turns",
        "3",
        "--output-format",
        "text",
        "--dangerously-skip-permissions",
    ]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout


def extract_json_from_response(text: str) -> dict[str, Any]:
    """Extract JSON from Claude response, handling markdown fences."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    patterns = [
        r"```json\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
        r'\{[\s\S]*"action"[\s\S]*\}',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            candidate = match.group(1) if match.lastindex else match.group(0)
            try:
                return json.loads(candidate.strip())
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not extract JSON from response:\n{text[:500]}")


def _enrich_one(story: dict[str, Any], model: str, dry_run: bool = False) -> list[dict[str, Any]]:
    """Enrich or split one story. Returns 1-2 story dicts. On failure, returns original unchanged."""
    story_json = json.dumps(story, indent=2, ensure_ascii=False)
    prompt = ENRICH_PROMPT.format(story_json=story_json)

    if dry_run:
        print(f"  [E] DRY-RUN: would enrich {story.get('title', '?')!r}")
        return [story]

    try:
        response = call_claude(prompt, model)
        result = extract_json_from_response(response)
    except Exception as exc:
        print(f"  [E] WARNING: enrichment failed for {story.get('title', '?')!r}: {exc}")
        return [story]  # passthrough — never block on enrichment failure

    action = result.get("action", "")

    if action == "split":
        sub_stories = result.get("stories", [])
        if not isinstance(sub_stories, list) or len(sub_stories) < 2:
            print(f"  [E] WARNING: split response malformed for {story.get('title', '?')!r} — keeping original")
            return [story]
        # Inherit metadata from parent
        enriched = []
        for sub in sub_stories[:2]:  # cap at 2
            sub.setdefault("priority", story.get("priority", "medium"))
            sub.setdefault("dependencies", story.get("dependencies", []))
            sub.setdefault("passes", False)
            sub["_source"] = story.get("_source", "research")
            sub["_enrichedFrom"] = story.get("title", "")
            enriched.append(sub)
        return enriched

    elif action == "enrich":
        enriched_story = result.get("story", {})
        if not isinstance(enriched_story, dict) or not enriched_story.get("title"):
            print(f"  [E] WARNING: enrich response malformed for {story.get('title', '?')!r} — keeping original")
            return [story]
        # Preserve fields that Claude should not change
        enriched_story.setdefault("priority", story.get("priority", "medium"))
        enriched_story.setdefault("dependencies", story.get("dependencies", []))
        enriched_story["passes"] = story.get("passes", False)
        enriched_story["_source"] = story.get("_source", "research")
        enriched_story["_enriched"] = True
        return [enriched_story]

    else:
        print(f"  [E] WARNING: unknown action {action!r} for {story.get('title', '?')!r} — keeping original")
        return [story]


def enrich_stories(
    validated_path: str,
    enriched_path: str,
    model: str = "sonnet",
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Read validated stories, enrich eligible ones, write output.
    Returns (enriched_count, split_count).
    """
    if not os.path.isfile(validated_path):
        print(f"  [E] ERROR: {validated_path} not found", file=sys.stderr)
        return 0, 0

    with open(validated_path, encoding="utf-8") as f:
        data = json.load(f)

    stories: list[dict[str, Any]] = data.get("stories", [])
    if not stories:
        print("  [E] No stories to enrich — writing empty output")
        atomic_write_json(enriched_path, {"stories": []})
        return 0, 0

    output_stories: list[dict[str, Any]] = []
    enriched_count = 0
    split_count = 0

    for story in stories:
        if _should_enrich(story):
            title = story.get("title", "?")
            print(
                f"  [E] Enriching: {title[:70]!r} (complexity={story.get('estimatedComplexity', '?')}, "
                f"notes={len(story.get('technicalNotes') or [])})"
            )
            result = _enrich_one(story, model, dry_run=dry_run)
            if len(result) > 1:
                split_count += 1
                enriched_count += len(result)
                print(f"  [E]   → split into {len(result)} stories")
            elif result and result[0] is not story:
                enriched_count += 1
                print("  [E]   → enriched")
            output_stories.extend(result)
        else:
            output_stories.append(story)  # passthrough — small + well-specified

    atomic_write_json(enriched_path, {"stories": output_stories})
    return enriched_count, split_count


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL Phase E: enrich validated stories before Phase M merge")
    parser.add_argument("--validated-in", required=True, help="Path to _validated_stories.json")
    parser.add_argument("--enriched-out", required=True, help="Output path for enriched stories")
    parser.add_argument("--model", default="sonnet", help="Claude model (default: sonnet)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without calling Claude")
    args = parser.parse_args()

    enriched, split = enrich_stories(
        validated_path=args.validated_in,
        enriched_path=args.enriched_out,
        model=args.model,
        dry_run=args.dry_run,
    )

    print(f"  [E] Done: {enriched} stories enriched/split ({split} splits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
