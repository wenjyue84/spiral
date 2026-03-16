#!/usr/bin/env python3
"""
lib/summarize_research.py — Hierarchical summarization for oversized Phase R outputs.

When Phase R research output exceeds SPIRAL_RESEARCH_SUMMARY_THRESHOLD tokens,
this module compresses story descriptions while preserving all acceptance
criteria, technical notes, and source URLs.

Usage:
  python lib/summarize_research.py --input _research_output.json \
      --output _research_summary.json --threshold 4000

  # Check only (exit 0 if under threshold, exit 2 if over)
  python lib/summarize_research.py --input _research_output.json --check-only

Output:
  Writes a summarized JSON file with the same schema as the input.
  Prints a JSON status line to stderr:
    {"event":"research_summarized","original_tokens":8500,"summary_tokens":2800,
     "stories":5,"reduction_pct":67}

Exit codes:
  0 — success (summarized or already under threshold)
  1 — error (bad input / missing file)
  2 — over threshold (--check-only mode)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Token counting (reuses pattern from truncate_context.py)
# ---------------------------------------------------------------------------

def _count_tokens_tiktoken(text: str) -> int:
    import tiktoken  # type: ignore[import-untyped,unused-ignore]
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _count_tokens_approx(text: str) -> int:
    return max(1, len(text) // 4)


def count_tokens(text: str) -> int:
    try:
        return _count_tokens_tiktoken(text)
    except (ImportError, Exception):
        return _count_tokens_approx(text)


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

# Fields that must be preserved verbatim in every story.
PRESERVE_FIELDS: frozenset[str] = frozenset([
    "id", "title", "acceptanceCriteria", "technicalNotes",
    "source", "dependencies", "priority", "estimatedComplexity",
    "_source",
])

# Fields whose text content can be compressed.
COMPRESSIBLE_FIELDS: list[str] = ["description"]

# Maximum description length (characters) after summarization.
MAX_DESC_CHARS = 300


def _truncate_description(desc: str, max_chars: int = MAX_DESC_CHARS) -> str:
    """Truncate a description to *max_chars*, preserving sentence boundaries."""
    if len(desc) <= max_chars:
        return desc
    # Try to cut at the last sentence boundary before max_chars.
    cut = desc[:max_chars]
    last_period = cut.rfind(".")
    last_newline = cut.rfind("\n")
    boundary = max(last_period, last_newline)
    if boundary > max_chars // 2:
        return desc[: boundary + 1].rstrip()
    return cut.rstrip() + "..."


def summarize_story(story: dict[str, Any]) -> dict[str, Any]:
    """Return a summarized copy of a single story dict."""
    result: dict[str, Any] = {}
    for key in story:
        if key in PRESERVE_FIELDS:
            result[key] = story[key]
        elif key in COMPRESSIBLE_FIELDS:
            result[key] = _truncate_description(str(story[key]))
        else:
            # Drop verbose extra fields (e.g. long _researchOutput blobs)
            # but keep small scalar values.
            val = story[key]
            if isinstance(val, str) and len(val) > MAX_DESC_CHARS:
                continue  # drop large string fields
            result[key] = val
    return result


def summarize_research(
    data: dict[str, Any],
    threshold: int,
) -> tuple[dict[str, Any], int, int, bool]:
    """
    Summarize research output if it exceeds *threshold* tokens.

    Returns:
        (output_data, original_tokens, final_tokens, was_summarized)
    """
    text = json.dumps(data, ensure_ascii=False)
    original_tokens = count_tokens(text)

    if original_tokens <= threshold:
        return data, original_tokens, original_tokens, False

    stories = data.get("stories", [])
    summarized_stories = [summarize_story(s) for s in stories]
    output = {**data, "stories": summarized_stories}

    final_text = json.dumps(output, ensure_ascii=False)
    final_tokens = count_tokens(final_text)
    return output, original_tokens, final_tokens, True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hierarchical summarization for Phase R research output"
    )
    parser.add_argument("--input", required=True, help="Path to _research_output.json")
    parser.add_argument("--output", help="Path to write summarized JSON (default: stdout)")
    parser.add_argument(
        "--threshold",
        type=int,
        default=int(os.environ.get("SPIRAL_RESEARCH_SUMMARY_THRESHOLD", "4000")),
        help="Token threshold (default: 4000)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Exit 0 if under threshold, 2 if over (no output written)",
    )
    args = parser.parse_args()

    try:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Error reading {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    text = json.dumps(data, ensure_ascii=False)
    original_tokens = count_tokens(text)

    if args.check_only:
        sys.exit(2 if original_tokens > args.threshold else 0)

    output, orig_tok, final_tok, was_summarized = summarize_research(
        data, args.threshold
    )

    if was_summarized:
        reduction_pct = round((1 - final_tok / orig_tok) * 100) if orig_tok > 0 else 0
        story_count = len(data.get("stories", []))
        status = {
            "event": "research_summarized",
            "original_tokens": orig_tok,
            "summary_tokens": final_tok,
            "stories": story_count,
            "reduction_pct": reduction_pct,
        }
        print(json.dumps(status), file=sys.stderr)

    result_text = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result_text)
            f.write("\n")
    else:
        print(result_text)


if __name__ == "__main__":
    main()
