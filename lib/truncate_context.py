#!/usr/bin/env python3
"""
SPIRAL — Truncate story context to fit Claude context window.

Measures token count of assembled prompt (base system prompt + story JSON).
If the count exceeds SPIRAL_CONTEXT_LIMIT (default: 180000), strips fields
from the story JSON in priority order:
  1. _researchOutput  (drop first — largest, least critical for implementation)
  2. hints / technicalHints  (helpful but not required)
  3. filesTouch  (file-path suggestions)
Core story spec fields (id, title, description, acceptanceCriteria,
technicalNotes, dependencies, priority, estimatedComplexity, passes) are
NEVER dropped.

Usage:
  # Pipe story JSON via stdin
  echo '{"id":"US-001",...}' | python lib/truncate_context.py

  # Pass story JSON directly
  python lib/truncate_context.py --story '{"id":"US-001",...}'

  # Include base-prompt token budget
  python lib/truncate_context.py --story '...' --base-prompt-file CLAUDE.md

Output:
  stdout: (possibly truncated) story JSON
  stderr: structured warning JSON if truncation occurred, e.g.:
    {"event":"context_truncated","story_id":"US-001",
     "original_tokens":195000,"truncated_tokens":175000,
     "dropped_fields":["_researchOutput"]}

Exit codes:
  0 — success
  1 — error (bad input / missing story JSON)

Environment:
  SPIRAL_CONTEXT_LIMIT — override default 180000 token threshold
  SPIRAL_CONTEXT_CACHE_DIR — directory for caching token counts
                              (default: none, caching disabled)
"""
import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT_LIMIT = 180_000

# Fields stripped in this order (least important first).
# Never strip CORE_FIELDS.
TRUNCATION_ORDER: list[str] = [
    "_researchOutput",
    "hints",
    "technicalHints",
    "filesTouch",
]

# These fields constitute the "story spec" and must never be removed.
CORE_FIELDS: frozenset[str] = frozenset([
    "id",
    "title",
    "description",
    "acceptanceCriteria",
    "technicalNotes",
    "dependencies",
    "priority",
    "estimatedComplexity",
    "passes",
])


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def _count_tokens_tiktoken(text: str) -> int:
    """Count tokens using tiktoken cl100k_base (exact for GPT/Claude models)."""
    import tiktoken  # type: ignore[import]
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _count_tokens_approx(text: str) -> int:
    """Approximate token count: 1 token ≈ 4 characters (conservative estimate)."""
    return max(1, len(text) // 4)


def count_tokens(text: str) -> int:
    """
    Count tokens in *text*.

    Uses tiktoken cl100k_base when available; falls back to a 4-char/token
    approximation so the function works without optional dependencies.
    """
    try:
        return _count_tokens_tiktoken(text)
    except (ImportError, Exception):
        return _count_tokens_approx(text)


# ---------------------------------------------------------------------------
# Core truncation logic
# ---------------------------------------------------------------------------

def truncate_story(
    story: dict,
    base_tokens: int = 0,
    limit: int = DEFAULT_CONTEXT_LIMIT,
) -> tuple[dict, int, int, list[str]]:
    """
    Truncate *story* dict so that base_tokens + story_tokens <= limit.

    Strips fields in TRUNCATION_ORDER; never strips CORE_FIELDS.

    Returns:
        (truncated_story, original_tokens, final_tokens, dropped_fields)
    """
    story_text = json.dumps(story, ensure_ascii=False)
    original_story_tokens = count_tokens(story_text)
    original_total = base_tokens + original_story_tokens

    if original_total <= limit:
        return story, original_total, original_total, []

    # Work on a shallow copy so we don't mutate the caller's dict
    truncated = dict(story)
    dropped: list[str] = []

    for field in TRUNCATION_ORDER:
        if original_total <= limit:
            break
        if field not in truncated:
            continue
        del truncated[field]
        dropped.append(field)
        new_text = json.dumps(truncated, ensure_ascii=False)
        original_total = base_tokens + count_tokens(new_text)

    final_total = base_tokens + count_tokens(json.dumps(truncated, ensure_ascii=False))
    return truncated, base_tokens + original_story_tokens, final_total, dropped


# ---------------------------------------------------------------------------
# Token-count caching (optional, keyed by story_id + attempt)
# ---------------------------------------------------------------------------

def _cache_path(cache_dir: str, story_id: str, attempt: int) -> str:
    safe_id = story_id.replace("/", "_").replace("\\", "_")
    return os.path.join(cache_dir, f"tokens_{safe_id}_{attempt}.json")


def load_cached_tokens(
    cache_dir: str, story_id: str, attempt: int
) -> int | None:
    """Return cached token count or None if no cache entry exists."""
    if not cache_dir:
        return None
    path = _cache_path(cache_dir, story_id, attempt)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return int(data["tokens"])
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return None


def save_cached_tokens(
    cache_dir: str, story_id: str, attempt: int, tokens: int
) -> None:
    """Persist token count to cache."""
    if not cache_dir:
        return
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, story_id, attempt)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"story_id": story_id, "attempt": attempt, "tokens": tokens}, f)
    except OSError:
        pass  # Cache write failure is non-fatal


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Truncate story context to fit Claude context window"
    )
    parser.add_argument(
        "--story",
        help="Story JSON string (reads from stdin if omitted)",
    )
    parser.add_argument(
        "--base-prompt-file",
        dest="base_prompt_file",
        help="Path to base system prompt file (used for token budget calculation)",
    )
    parser.add_argument(
        "--base-tokens",
        dest="base_tokens",
        type=int,
        default=0,
        help="Pre-computed base prompt token count (alternative to --base-prompt-file)",
    )
    parser.add_argument(
        "--attempt",
        type=int,
        default=0,
        help="Retry attempt number for cache keying",
    )
    args = parser.parse_args(argv)

    # Read story JSON
    if args.story is not None:
        raw = args.story
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        print("[truncate_context] ERROR: no story JSON provided", file=sys.stderr)
        return 1

    try:
        story = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[truncate_context] ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(story, dict):
        print("[truncate_context] ERROR: story JSON must be a dict", file=sys.stderr)
        return 1

    # Resolve token limit from env or default
    limit_str = os.environ.get("SPIRAL_CONTEXT_LIMIT", "")
    try:
        limit = int(limit_str) if limit_str else DEFAULT_CONTEXT_LIMIT
    except ValueError:
        limit = DEFAULT_CONTEXT_LIMIT

    # Resolve base token budget
    base_tokens = args.base_tokens
    if args.base_prompt_file and os.path.isfile(args.base_prompt_file):
        try:
            with open(args.base_prompt_file, encoding="utf-8", errors="replace") as f:
                base_text = f.read()
            base_tokens = count_tokens(base_text)
        except OSError:
            pass

    # Check token-count cache
    story_id = story.get("id", "unknown")
    cache_dir = os.environ.get("SPIRAL_CONTEXT_CACHE_DIR", "")
    cached = load_cached_tokens(cache_dir, story_id, args.attempt)
    if cached is not None and cached <= limit:
        # Under limit per cache — emit story unchanged
        print(json.dumps(story, ensure_ascii=False))
        return 0

    # Perform truncation
    truncated, original_total, final_total, dropped = truncate_story(
        story, base_tokens=base_tokens, limit=limit
    )

    # Cache the original total for this story/attempt
    save_cached_tokens(cache_dir, story_id, args.attempt, original_total)

    # Emit structured warning to stderr if truncation occurred
    if dropped:
        warning = {
            "event": "context_truncated",
            "story_id": story_id,
            "original_tokens": original_total,
            "truncated_tokens": final_total,
            "limit": limit,
            "dropped_fields": dropped,
        }
        print(json.dumps(warning), file=sys.stderr)

    # Emit (possibly truncated) story JSON to stdout
    print(json.dumps(truncated, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
