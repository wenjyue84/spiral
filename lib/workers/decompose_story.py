#!/usr/bin/env python3
"""
SPIRAL — Story Decomposition
When a story exceeds MAX_RETRIES, decomposes it into 2-4 smaller sub-stories
using Claude analysis of the failure context.

Usage:
  python decompose_story.py --story-id US-005
  python decompose_story.py --story-id US-005 --prd prd.json --model sonnet --dry-run
"""

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from learned_lessons import query_lessons
from llm_models import DecompositionResult, validate_llm_json
from parse_story_hints import build_hint_context, extract_complexity_band
from prd_schema import validate_prd
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")


def build_lessons_section(lessons_path: str, story: dict[str, Any], top_k: int = 3) -> str:
    """Return a formatted lessons block to append to the decomposition prompt.

    Returns empty string when SPIRAL_LESSON_INJECTION=false or no matches found.
    """
    if os.environ.get("SPIRAL_LESSON_INJECTION", "true").lower() == "false":
        return ""
    from pathlib import Path

    matches = query_lessons(Path(lessons_path), story, top_k=top_k)
    if not matches:
        return ""
    lines = ["\n<learned_lessons>"]
    lines.append("  Previous failures to avoid when designing sub-stories:")
    for i, lesson in enumerate(matches, 1):
        lines.append(f"  {i}. [{lesson.get('error_category', 'error')}] {lesson.get('pattern', '')}")
        lines.append(f"     Fix: {lesson.get('fix', '')}")
    lines.append("</learned_lessons>\n")
    return "\n".join(lines)


_FAILURE_TYPE_ALIASES: dict[str, str] = {
    "syntax": "syntax",
    "logic": "logic",
    "scope": "scope",
    "timeout": "timeout",
    "type": "syntax",
    "import": "syntax",
    "test": "logic",
    "size": "scope",
    "complexity": "scope",
    "perf": "timeout",
    "performance": "timeout",
}


def load_learned_lessons_for_complexity(
    complexity_band: str,
    learning_path: str,
) -> dict[str, list[str]]:
    """Parse learning.md for patterns matching the given complexity_band.

    Expected format::

        ## Small Stories
        - [syntax] Check imports before writing implementation
        - [scope] Limit each sub-story to one function

    Returns dict mapping failure_type -> [pattern strings] for the given band.
    Returns empty dict when the file is missing or band has no entries.
    """
    if not os.path.isfile(learning_path):
        return {}
    try:
        with open(learning_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return {}

    band = complexity_band.lower().strip()
    section_header = f"## {band.capitalize()} Stories"
    result: dict[str, list[str]] = {}
    in_section = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_section = stripped.lower() == section_header.lower()
            continue
        if not in_section:
            continue
        m = re.match(r"^[-*]\s+\[(\w+)\]\s+(.+)$", stripped)
        if m:
            raw_ft = m.group(1).lower()
            ft = _FAILURE_TYPE_ALIASES.get(raw_ft, raw_ft)
            result.setdefault(ft, []).append(m.group(2).strip())

    return result


DECOMPOSE_PROMPT = """\
You are decomposing a failed user story into 2-{max_sub} smaller, independent sub-stories.

<parent_story>
  <id>{parent_id}</id>
  <title>{parent_title}</title>
  <description>{parent_description}</description>
  <acceptance_criteria>
    {parent_ac}
  </acceptance_criteria>
</parent_story>

<failure_context>
{failure_context}
</failure_context>
{learned_patterns}
Rules:
1. Sub-stories must be completable in one AI agent turn (~15 mins).
2. Together, sub-stories must fully cover the parent's acceptance criteria.
3. Redistribute parent's acceptance criteria among sub-stories.
4. If order matters, set "ordered": true.
5. Titles must be short and imperative.
6. Complexity must be "small".
7. Do NOT add scope.

Output ONLY a JSON object:
{{
  "ordered": true,
  "stories": [
    {{
      "title": "...",
      "description": "...",
      "acceptanceCriteria": ["..."],
      "technicalNotes": ["..."],
      "estimatedComplexity": "small"
    }}
  ]
}}
"""


def find_next_id(stories: list[dict[str, Any]]) -> int:
    """Scan all PREFIX-NNN ids, return max+1. Handles gaps safely."""
    ids = []
    for s in stories:
        m = re.match(rf"{re.escape(STORY_PREFIX)}-(\d+)$", s.get("id", ""))
        if m:
            ids.append(int(m.group(1)))
    return max(ids) + 1 if ids else 1


def extract_failure_context(progress_path: str, story_id: str, max_lines: int = 60) -> str:
    """Extract lines from progress.txt that mention the story ID."""
    if not os.path.isfile(progress_path):
        return "(no progress file found)"
    lines = []
    try:
        with open(progress_path, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError:
        return "(could not read progress file)"

    # Grab lines mentioning the story ID + surrounding context
    for i, line in enumerate(all_lines):
        if story_id in line:
            start = max(0, i - 2)
            end = min(len(all_lines), i + 5)
            for j in range(start, end):
                if all_lines[j] not in lines:
                    lines.append(all_lines[j])

    if not lines:
        # Fallback: last N lines
        lines = all_lines[-max_lines:]

    return "".join(lines[-max_lines:]).strip()


def extract_json_from_response(text: str) -> dict[str, Any]:
    """Extract JSON from Claude's response, handling markdown fences."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    patterns = [
        r"```json\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
        r"\{[\s\S]*\"stories\"[\s\S]*\}",
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


def _claude_cmd() -> str:
    """Return the Claude CLI executable name, using .cmd on Windows."""
    import shutil
    import sys

    if sys.platform == "win32":
        return shutil.which("claude.cmd") or shutil.which("claude") or "claude.cmd"
    return shutil.which("claude") or "claude"


def call_claude(prompt: str, model: str) -> str:
    """Call Claude CLI and return the text response.

    Prompt is passed via stdin (not as a CLI argument) to avoid Windows
    cmd.exe interpreting XML angle-brackets in the prompt as shell redirects.
    """
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


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL story decomposer")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--story-id", required=True, help="Story ID to decompose (e.g. US-005)")
    parser.add_argument("--progress", default="progress.txt", help="Path to progress.txt")
    parser.add_argument("--lessons", default=".spiral/learned_lessons.jsonl", help="Path to lessons JSONL")
    parser.add_argument("--learning-path", default="", help="Path to learning.md for complexity-band hints")
    parser.add_argument("--model", default="sonnet", help="Claude model (default: sonnet)")
    parser.add_argument("--max-substories", type=int, default=4, help="Max sub-stories (default: 4)")
    parser.add_argument("--enable-hints", action="store_true", help="Parse @spiral:hint-* markers from description")
    parser.add_argument("--learned-hints", default="", help="Recovery hints from failure history (newline-separated)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt without modifying prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[decompose] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    errors = validate_prd(prd)
    if errors:
        print("[schema] PRD validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    stories: list[dict[str, Any]] = prd.get("userStories", [])

    # Find the target story
    parent = None
    for s in stories:
        if s.get("id") == args.story_id:
            parent = s
            break

    if parent is None:
        print(f"[decompose] ERROR: story {args.story_id} not found in {args.prd}", file=sys.stderr)
        return 1

    # Guard: already decomposed
    if parent.get("_decomposed"):
        print(f"[decompose] {args.story_id} is already decomposed — skipping")
        return 0

    # Guard: is a sub-story (prevent infinite recursion)
    if parent.get("_decomposedFrom"):
        print(f"[decompose] {args.story_id} is a sub-story of {parent['_decomposedFrom']} — refusing to decompose")
        return 1

    # Extract failure context
    failure_context = extract_failure_context(args.progress, args.story_id)

    # Build learned-patterns sidecar from learning.md
    learning_md = args.learning_path or os.path.join(
        os.path.dirname(os.path.abspath(args.prd)), ".spiral", "learning.md"
    )
    band = parent.get("estimatedComplexity", "small")
    lp = load_learned_lessons_for_complexity(band, learning_md)
    if lp:
        bullets = []
        for ft in ("syntax", "logic", "scope", "timeout"):
            for p in lp.get(ft, [])[:2]:
                bullets.append(f"  - [{ft}] {p}")
        lp_text = f"\n<learned_patterns complexity='{band}'>\n" + "\n".join(bullets[:6]) + "\n</learned_patterns>\n"
    else:
        lp_text = ""

    # Extract complexity band hint from description
    hint_text = ""
    if args.enable_hints:
        description = parent.get("description", "")
        hint_band = extract_complexity_band(description)
        if hint_band:
            hint_text = build_hint_context(hint_band)
            print(f"[decompose] Using @spiral:hint-complexity-band:{hint_band}")

    # Build recovery hints from failure history
    recovery_hints_text = ""
    if args.learned_hints:
        hints_list = [h.strip() for h in args.learned_hints.split("\n") if h.strip()]
        if hints_list:
            recovery_hints_text = "\n<learned_recovery_hints>\n"
            for hint in hints_list[:5]:  # Limit to 5 hints
                recovery_hints_text += f"  - {hint}\n"
            recovery_hints_text += "</learned_recovery_hints>\n"
            print(f"[decompose] Injected {len(hints_list)} recovery hints from failure history")

    # Build prompt
    parent_ac_string = "\n".join(f"    - {ac}" for ac in parent.get("acceptanceCriteria", []))
    prompt = DECOMPOSE_PROMPT.format(
        parent_id=parent.get("id"),
        parent_title=parent.get("title"),
        parent_description=parent.get("description", ""),
        parent_ac=parent_ac_string,
        failure_context=failure_context,
        max_sub=args.max_substories,
        learned_patterns=lp_text + hint_text + recovery_hints_text,
    )
    prompt += build_lessons_section(args.lessons, parent)

    if args.dry_run:
        print("[decompose] DRY RUN — prompt that would be sent to Claude:")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        return 0

    # Call Claude
    print(f"[decompose] Asking Claude ({args.model}) to decompose {args.story_id}...")
    try:
        response = call_claude(prompt, args.model)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"[decompose] ERROR: {e}", file=sys.stderr)
        return 1

    # Parse response
    try:
        data = extract_json_from_response(response)
    except ValueError as e:
        print(f"[decompose] ERROR: {e}", file=sys.stderr)
        return 1

    # Validate LLM output with Pydantic model (US-203)
    try:
        validated = validate_llm_json(DecompositionResult, data, "decompose_story")
    except ValidationError as exc:
        print(f"[decompose] ERROR: LLM output validation failed: {exc}", file=sys.stderr)
        return 1

    sub_stories_raw = [s.model_dump() for s in validated.stories]
    ordered = validated.ordered

    # Validate count
    if len(sub_stories_raw) < 2:
        print(f"[decompose] ERROR: Claude returned {len(sub_stories_raw)} stories (need at least 2)", file=sys.stderr)
        return 1
    if len(sub_stories_raw) > args.max_substories:
        print(f"[decompose] WARNING: truncating from {len(sub_stories_raw)} to {args.max_substories} sub-stories")
        sub_stories_raw = sub_stories_raw[: args.max_substories]

    # Validate each sub-story
    for i, ss in enumerate(sub_stories_raw):
        if not ss.get("title"):
            print(f"[decompose] ERROR: sub-story {i} has no title", file=sys.stderr)
            return 1
        if not ss.get("acceptanceCriteria"):
            print(f"[decompose] ERROR: sub-story {i} has no acceptanceCriteria", file=sys.stderr)
            return 1

    # Assign IDs
    next_num = find_next_id(stories)
    child_ids = []
    new_entries = []

    for i, ss in enumerate(sub_stories_raw):
        story_id = f"{STORY_PREFIX}-{next_num:03d}"
        next_num += 1
        child_ids.append(story_id)

        # Build dependencies: inherit parent's deps for first; chain if ordered
        deps = list(parent.get("dependencies", []))
        if ordered and i > 0:
            deps.append(child_ids[i - 1])

        entry: dict[str, Any] = {
            "id": story_id,
            "title": ss["title"],
            "priority": parent.get("priority", "medium"),
            "description": ss.get("description", ""),
            "acceptanceCriteria": ss["acceptanceCriteria"],
            "technicalNotes": ss.get("technicalNotes", []),
            "dependencies": deps,
            "estimatedComplexity": "small",
            "passes": False,
            "_decomposedFrom": args.story_id,
        }
        new_entries.append(entry)
        print(f"[decompose]   + [{story_id}] {entry['title'][:70]}")

    # Mark parent as decomposed
    parent["_decomposed"] = True
    parent["_decomposedInto"] = child_ids

    # Append sub-stories to prd
    prd["userStories"] = stories + new_entries

    # Atomic write
    atomic_write_json(args.prd, prd)

    print(f"[decompose] Done: {args.story_id} → {len(new_entries)} sub-stories ({', '.join(child_ids)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
