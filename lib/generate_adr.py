#!/usr/bin/env python3
"""
generate_adr.py — Generate an Architecture Decision Record (ADR) for a passed story.

Called by ralph.sh after all quality gates pass, before the git commit, so
the ADR file is included in the story commit.

Reads story spec from prd.json, captures the staged git diff, calls
Claude haiku to generate a MADR-format ADR, writes it to docs/decisions/,
and records _adrPath on the prd.json story entry.

Usage:
    python lib/generate_adr.py --story-id US-042 --prd prd.json \\
        --output-dir docs/decisions [--model haiku]

Exit codes:
    0 — ADR written successfully; ADR path is printed to stdout
    1 — ADR generation failed (warning only; caller should not block commit)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spiral_io import configure_utf8_stdout
configure_utf8_stdout()

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_HERE, "prompts", "adr_template.md")

# Inline MADR template — used as fallback when prompts/adr_template.md is absent
_FALLBACK_TEMPLATE = """\
Generate an Architecture Decision Record (ADR) in MADR format.

Story ID: {story_id}
Title: {story_title}
Description: {story_description}

Acceptance Criteria:
{acceptance_criteria}

Git Diff:
```diff
{git_diff}
```

Write the ADR using ONLY this structure (no extra text):

# {story_id} — {story_title}

## Status

Accepted

## Context

<explain the problem or need this story addresses>

## Decision

<describe the design choices from the diff>

## Consequences

**Positive:**
- <benefit>

**Negative / Trade-offs:**
- <trade-off or "None identified">
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kebab(title: str) -> str:
    """Convert a story title to a kebab-case filename slug (max 60 chars)."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60]


def _get_staged_diff(max_lines: int = 500) -> str:
    """Return the staged git diff, falling back to the working-tree diff."""
    for cmd in (["git", "diff", "--cached"], ["git", "diff", "HEAD"]):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=15, encoding="utf-8", errors="replace",
            )
            diff = result.stdout
        except Exception:
            diff = ""
        if diff.strip():
            lines = diff.splitlines()[:max_lines]
            return "\n".join(lines)
    return ""


def _read_story(prd_path: str, story_id: str) -> dict[str, Any]:
    """Load and return a single story dict from prd.json."""
    with open(prd_path, encoding="utf-8") as fh:
        prd = json.load(fh)
    for story in prd.get("userStories", []):
        if story.get("id") == story_id:
            return dict(story)
    return {}


def _load_template() -> str:
    """Return the ADR prompt template, preferring the file version."""
    if os.path.isfile(_TEMPLATE_PATH):
        with open(_TEMPLATE_PATH, encoding="utf-8") as fh:
            return fh.read()
    return _FALLBACK_TEMPLATE


def _build_prompt(story: dict[str, Any], diff: str, template: str) -> str:
    """Interpolate story fields + diff into the ADR prompt template."""
    ac_lines = "\n".join(
        f"- {ac}" for ac in story.get("acceptanceCriteria", [])
    )
    return template.format(
        story_id=story.get("id", ""),
        story_title=story.get("title", ""),
        story_description=story.get("description", ""),
        acceptance_criteria=ac_lines or "(none listed)",
        git_diff=diff or "(no diff available)",
    )


def _call_claude(prompt: str, model: str = "haiku") -> str:
    """Call the `claude` CLI and return the response text.

    Uses the same invocation style as run_self_review() in ralph.sh:
    single-turn, dangerously-skip-permissions, text output format.
    Returns empty string on any failure (caller should treat as non-blocking).
    """
    system = (
        "You are a technical writer generating Architecture Decision Records (ADRs) "
        "in MADR format. Output ONLY the ADR markdown — no preamble, no explanation, "
        "no markdown code fences wrapping the whole response."
    )
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # mirror run_self_review() pattern

    try:
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--model", model,
                "--append-system-prompt", system,
                "--max-turns", "1",
                "--output-format", "text",
                "--dangerously-skip-permissions",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()
    except FileNotFoundError:
        print("  [adr] WARNING: claude CLI not found — skipping ADR", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("  [adr] WARNING: claude CLI timed out — skipping ADR", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"  [adr] WARNING: claude CLI error: {exc} — skipping ADR", file=sys.stderr)
    return ""


def _update_prd_adr_path(prd_path: str, story_id: str, adr_path: str) -> None:
    """Atomically record _adrPath on the story entry in prd.json."""
    sys.path.insert(0, _HERE)
    from prd_lock import prd_locked  # type: ignore[import]

    with prd_locked(prd_path, timeout=10) as prd:
        for story in prd.get("userStories", []):
            if story.get("id") == story_id:
                story["_adrPath"] = adr_path
                break


# ---------------------------------------------------------------------------
# Public API (used by tests)
# ---------------------------------------------------------------------------

def generate_adr(
    story_id: str,
    prd_path: str,
    output_dir: str,
    model: str = "haiku",
    *,
    diff_override: str | None = None,
) -> str | None:
    """Generate an ADR for *story_id* and return the written file path.

    Parameters
    ----------
    story_id:
        PRD story identifier, e.g. ``"US-042"``.
    prd_path:
        Path to ``prd.json``.
    output_dir:
        Directory where the ADR file will be written
        (created if absent).
    model:
        Claude model shortname passed to ``--model`` (default ``"haiku"``).
    diff_override:
        When provided, use this string as the diff instead of running
        ``git diff``.  Intended for tests.

    Returns
    -------
    str | None
        Absolute path to the written ADR file, or ``None`` on failure.
    """
    story = _read_story(prd_path, story_id)
    if not story:
        print(
            f"  [adr] WARNING: story {story_id} not found in {prd_path}",
            file=sys.stderr,
        )
        return None

    diff = diff_override if diff_override is not None else _get_staged_diff()
    template = _load_template()
    prompt = _build_prompt(story, diff, template)

    adr_text = _call_claude(prompt, model=model)
    if not adr_text:
        return None

    os.makedirs(output_dir, exist_ok=True)
    slug = _kebab(story.get("title", story_id))
    filename = f"{story_id}-{slug}.md"
    adr_path = os.path.join(output_dir, filename)

    with open(adr_path, "w", encoding="utf-8") as fh:
        fh.write(adr_text)
        if not adr_text.endswith("\n"):
            fh.write("\n")

    try:
        _update_prd_adr_path(prd_path, story_id, adr_path)
    except Exception as exc:  # noqa: BLE001
        print(
            f"  [adr] WARNING: could not update prd.json _adrPath: {exc}",
            file=sys.stderr,
        )

    return adr_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a MADR-format ADR for a passed Spiral story",
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g. US-042)")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument(
        "--output-dir", default="docs/decisions",
        help="Directory to write ADR files (created if absent)",
    )
    parser.add_argument(
        "--model", default="haiku",
        help="Claude model shortname (default: haiku)",
    )
    args = parser.parse_args(argv)

    result = generate_adr(
        story_id=args.story_id,
        prd_path=args.prd,
        output_dir=args.output_dir,
        model=args.model,
    )
    if result is None:
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
