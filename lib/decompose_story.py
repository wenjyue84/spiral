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
import shutil
import subprocess
import sys
from typing import Any

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")

DECOMPOSE_PROMPT = """\
You are decomposing a user story that failed {retry_count} implementation attempts into smaller sub-stories.

## Parent Story
```json
{parent_json}
```

## Failure Context
These are the relevant failure notes from progress.txt:
```
{failure_context}
```

## Instructions
Break this story into 2-{max_sub} smaller, independently implementable sub-stories.

Rules:
1. Each sub-story must be completable in a single AI agent iteration (~15 minutes)
2. Together, the sub-stories must fully cover the parent's acceptance criteria
3. Each sub-story gets a SUBSET of the parent's acceptance criteria (redistribute, don't duplicate)
4. If order matters, set "ordered": true and I will chain dependencies
5. Keep titles short and imperative
6. estimatedComplexity must be "small" for all sub-stories
7. Do NOT add scope beyond the parent story

## Output Format
Return ONLY a JSON object (no markdown, no explanation):
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


def call_claude(prompt: str, model: str) -> str:
    """Call Claude CLI and return the text response."""
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--max-turns", "3",
        "--output-format", "text",
        "--dangerously-skip-permissions",
    ]
    result = subprocess.run(
        cmd,
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
    parser.add_argument("--model", default="sonnet", help="Claude model (default: sonnet)")
    parser.add_argument("--max-substories", type=int, default=4, help="Max sub-stories (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Print prompt without modifying prd.json")
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"[decompose] ERROR: {args.prd} not found", file=sys.stderr)
        return 1

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

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

    # Build prompt
    parent_json = json.dumps(parent, indent=2, ensure_ascii=False)
    prompt = DECOMPOSE_PROMPT.format(
        retry_count=3,
        parent_json=parent_json,
        failure_context=failure_context,
        max_sub=args.max_substories,
    )

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

    sub_stories_raw = data.get("stories", [])
    ordered = data.get("ordered", False)

    # Validate count
    if len(sub_stories_raw) < 2:
        print(f"[decompose] ERROR: Claude returned {len(sub_stories_raw)} stories (need at least 2)", file=sys.stderr)
        return 1
    if len(sub_stories_raw) > args.max_substories:
        print(f"[decompose] WARNING: truncating from {len(sub_stories_raw)} to {args.max_substories} sub-stories")
        sub_stories_raw = sub_stories_raw[:args.max_substories]

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
    tmp_path = args.prd + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(prd, f, indent=2, ensure_ascii=False)
        f.write("\n")
    shutil.move(tmp_path, args.prd)

    print(
        f"[decompose] Done: {args.story_id} → {len(new_entries)} sub-stories "
        f"({', '.join(child_ids)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
