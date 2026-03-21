#!/usr/bin/env python3
"""
SPIRAL Phase A — AI Story Suggestions (Source 2, per-iteration)

Analyzes prd.json state each iteration and generates AI story suggestions
via a Claude CLI subprocess call. Also loads queued ai-example picks
from Phase 0-D.

Inputs:
  prd.json                         — current PRD state
  .spiral/_ai_example_queue.json   — picks queued from Phase 0-D (optional)

Output:
  .spiral/_ai_suggest_output.json  — {"stories": [...]} with _source="ai-example"

Story generation:
  Calls Claude CLI (haiku model by default) with project goals, existing story
  titles, and focus theme (if set). Returns n stories each with title +
  description + 2-3 concrete ACs + complexity. Falls back to empty list on
  any CLI error or timeout.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_DEFAULT_TIMEOUT = int(os.environ.get("SPIRAL_AI_SUGGEST_TIMEOUT", "300"))


def load_queue(queue_path: str) -> list[dict[str, Any]]:
    """Load ai-example picks queued from Phase 0-D."""
    if not os.path.exists(queue_path):
        return []
    try:
        with open(queue_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
        stories: list[dict[str, Any]] = data.get("stories", [])
        return stories
    except (json.JSONDecodeError, OSError):
        return []


def clear_queue(queue_path: str) -> None:
    """Clear the queue after consuming it."""
    try:
        atomic_write_json(queue_path, {"stories": []})
    except OSError:
        pass


def _claude_cmd() -> str:
    """Return the Claude CLI executable, using .cmd on Windows."""
    if sys.platform == "win32":
        return shutil.which("claude.cmd") or shutil.which("claude") or "claude.cmd"
    return shutil.which("claude") or "claude"


def _build_prompt(prd: dict[str, Any], existing_titles: list[str], focus: str, n: int) -> str:
    goals: list[str] = prd.get("goals", [])
    goals_str = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(goals)) or "(no goals defined)"
    titles_str = "\n".join(f"- {t}" for t in existing_titles) or "(none)"
    focus_line = f"\nFocus area: {focus}\n" if focus else ""
    return f"""\
You are a product owner for SPIRAL (a self-iterating autonomous development system written in Python + Bash).

Project goals:
{goals_str}
{focus_line}
These stories are already implemented — do NOT suggest anything similar:
{titles_str}

Suggest exactly {n} new user stories that advance the project goals above.
Each story MUST:
- Have a specific, actionable title (no generic "Extend X", "Refactor Y", or "Add tests for Z")
- Address one of the project goals concretely
- Include 2-3 acceptance criteria with real details: file paths, function names, CLI commands, or test assertions
- Include filesTouch (list of exact file paths to create or modify) and technicalNotes (with at least one file path and one test command)
- Be implementable in under 200 lines of code (small or medium scope)

Output ONLY valid JSON — no explanation, no markdown:
{{"stories": [{{"title": "...", "priority": "medium", "description": "...", "acceptanceCriteria": ["ac1", "ac2"], "technicalNotes": ["File to edit: path/to/file.py (function_name)", "Test command: uv run pytest tests/test_X.py -v"], "filesTouch": ["path/to/file.py", "tests/test_file.py"], "estimatedComplexity": "small", "_source": "ai-example"}}]}}"""


def _suggest_via_llm(
    prd: dict[str, Any],
    existing_titles: list[str],
    focus: str,
    n: int,
    model: str | None = None,
) -> list[dict[str, Any]]:
    if n <= 0:
        return []
    if model is None:
        model = os.environ.get("SPIRAL_AI_SUGGEST_MODEL", _DEFAULT_MODEL)
    prompt = _build_prompt(prd, existing_titles, focus, n)
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
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"[A] WARNING: Claude CLI failed (exit {result.returncode}) — returning empty")
            return []
        raw = result.stdout.strip()
        # Strip markdown fences if model added them
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)

        # Handle both {"stories": [...]} and bare [...] array responses
        if isinstance(data, list):
            stories: list[dict[str, Any]] = data
        else:
            stories = data.get("stories", [])

        # Normalize snake_case fields to camelCase PRD schema
        _field_map = {
            "acceptance_criteria": "acceptanceCriteria",
            "estimated_complexity": "estimatedComplexity",
            "technical_notes": "technicalNotes",
            "files_to_touch": "filesTouch",
        }
        for s in stories:
            for snake, camel in _field_map.items():
                if snake in s and camel not in s:
                    s[camel] = s.pop(snake)
            for drop in ("id", "status"):
                s.pop(drop, None)
            s.setdefault("_source", "ai-example")
            s.setdefault("passes", False)
            s.setdefault("priority", "medium")
            s.setdefault("dependencies", [])
            if not s.get("acceptanceCriteria"):
                s["acceptanceCriteria"] = []

        print(f"[A] LLM generated {len(stories)} story candidates")
        return stories
    except subprocess.TimeoutExpired:
        print(f"[A] WARNING: Claude CLI timed out after {_DEFAULT_TIMEOUT}s -- returning empty")
        return []
    except Exception as exc:
        print(f"[A] WARNING: LLM story generation failed ({exc}) -- returning empty")
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase A: Generate AI story suggestions (Source 2, per-iteration)")
    parser.add_argument("--prd", default="prd.json")
    parser.add_argument(
        "--queue",
        default=".spiral/_ai_example_queue.json",
        help="Path to ai-example picks queued from Phase 0-D",
    )
    parser.add_argument("--out", default=".spiral/_ai_suggest_output.json")
    parser.add_argument("--focus", default="")
    parser.add_argument(
        "--max-suggest",
        type=int,
        default=5,
        help="Max AI-generated gap suggestions per iteration (default: 5)",
    )
    parser.add_argument(
        "--clear-queue",
        action="store_true",
        help="Clear the Phase 0-D queue after consuming it (default: keep)",
    )
    parser.add_argument(
        "--pending",
        type=int,
        default=0,
        help="Current pending story count (from PENDING var in spiral.sh)",
    )
    parser.add_argument(
        "--max-pending",
        type=int,
        default=0,
        help="SPIRAL_MAX_PENDING cap (0 = no cap check)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"  [A] WARNING: {args.prd} not found — no AI suggestions this iteration")
        atomic_write_json(args.out, {"stories": []})
        return 0

    with open(args.prd, encoding="utf-8") as f:
        prd: dict[str, Any] = json.load(f)

    # Load Phase 0-D queued picks
    queued = load_queue(args.queue)
    if queued:
        print(f"  [A] Loaded {len(queued)} queued ai-example pick(s) from Phase 0-D")

    # Check pending cap — skip LLM call if already at limit
    if args.max_pending > 0 and args.pending >= args.max_pending:
        print(f"  [A] Pending cap reached ({args.pending}/{args.max_pending}) — skipping LLM suggest")
        generated: list[dict[str, Any]] = []
    else:
        existing_titles = [s.get("title", "") for s in prd.get("userStories", [])]
        generated = _suggest_via_llm(
            prd,
            existing_titles=existing_titles,
            focus=args.focus,
            n=args.max_suggest,
        )
        if generated:
            print(f"  [A] Generated {len(generated)} AI suggestion(s) via LLM")

    all_suggestions = queued + generated

    # Deduplicate by lowercase title; ensure all tagged as ai-example
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for s in all_suggestions:
        key = s.get("title", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            s["_source"] = "ai-example"
            unique.append(s)

    atomic_write_json(args.out, {"stories": unique})
    print(f"  [A] AI suggestions: {len(unique)} candidate(s) → {args.out}")

    if args.clear_queue and queued:
        clear_queue(args.queue)
        print(f"  [A] Queue cleared ({args.queue})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
