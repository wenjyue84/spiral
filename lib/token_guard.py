#!/usr/bin/env python3
"""
lib/token_guard.py — Pre-flight token count guard using the Anthropic API.

Uses client.beta.messages.count_tokens() to verify assembled prompts fit
within the target model's context window before submission to Claude.

Falls back to tiktoken-based approximation when the Anthropic SDK is
unavailable or ANTHROPIC_API_KEY is not set.

When token count > SPIRAL_CONTEXT_BUDGET_TOKENS (default 150000), the
story context is trimmed via lib/truncate_context.truncate_story() and
a warning event is written to spiral_events.jsonl.

Usage (CLI):
  # Check a story JSON; emit trimmed result to stdout
  echo '{"id":"US-001",...}' | python lib/token_guard.py --model sonnet

  # Include base prompt budget
  python lib/token_guard.py --story '...' --model sonnet --base-prompt-file CLAUDE.md

Output:
  stdout: (possibly truncated) story JSON
  stderr: structured JSON warning if budget exceeded

Exit codes:
  0 — success (story fits or was trimmed)
  1 — error (bad input / missing story JSON)

Environment:
  SPIRAL_CONTEXT_BUDGET_TOKENS — max token budget (default: 150000)
  ANTHROPIC_API_KEY            — API key for count_tokens API call
  SCRATCH_DIR                  — directory for spiral_events.jsonl (default: .spiral)
  SPIRAL_RUN_ID                — run ID injected into emitted events
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

DEFAULT_BUDGET = 150_000

# Short alias → full model ID mapping
_MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


def _resolve_model(model: str) -> str:
    """Map a short alias (haiku/sonnet/opus) to a full Claude model ID."""
    lower = (model or "").strip().lower()
    for alias, full in _MODEL_ALIASES.items():
        if alias in lower:
            return full
    # Already a full ID or unrecognised — return as-is, fallback to sonnet
    return model if model else _MODEL_ALIASES["sonnet"]


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def count_tokens_anthropic(messages: list[dict[str, Any]], model: str) -> int | None:
    """
    Call the Anthropic beta.messages.count_tokens endpoint.

    Returns the input token count, or None when:
    - the ``anthropic`` SDK is not installed
    - ``ANTHROPIC_API_KEY`` is not set
    - any network / API error occurs

    The count_tokens endpoint does NOT consume quota tokens.
    """
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.beta.messages.count_tokens(
            model=_resolve_model(model),
            messages=messages,
            betas=["token-counting-2024-11-01"],
        )
        return int(response.input_tokens)
    except Exception:  # noqa: BLE001
        return None


def _count_tokens_approx(text: str) -> int:
    """Approximate token count using tiktoken or 4-char heuristic."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Flatten messages list to a single string for approximate counting."""
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
    return " ".join(parts)


def count_tokens(messages: list[dict[str, Any]], model: str = "sonnet") -> tuple[int, str]:
    """
    Count input tokens for *messages*.

    Tries the Anthropic API first; falls back to tiktoken/4-char approximation.

    Returns:
        (token_count, method)  where method is "anthropic_api" or "approx"
    """
    result = count_tokens_anthropic(messages, model)
    if result is not None:
        return result, "anthropic_api"
    return _count_tokens_approx(_messages_to_text(messages)), "approx"


# ---------------------------------------------------------------------------
# spiral_events.jsonl writer
# ---------------------------------------------------------------------------


def _emit_event(event: dict[str, Any], scratch_dir: str) -> None:
    """Append a structured JSON line to spiral_events.jsonl (best-effort)."""
    log_path = os.path.join(scratch_dir, "spiral_events.jsonl")
    try:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Never crash the pipeline over a log-write failure


# ---------------------------------------------------------------------------
# Core guard logic
# ---------------------------------------------------------------------------


def guard_story(
    story: dict[str, Any],
    model: str = "sonnet",
    base_prompt: str = "",
    budget: int = DEFAULT_BUDGET,
    scratch_dir: str = ".spiral",
) -> tuple[dict[str, Any], int, bool]:
    """
    Pre-flight token check for a single story dict.

    Assembles the messages array that Claude would receive (base_prompt +
    story JSON), counts tokens, and trims the story if the count exceeds
    *budget*.  Emits a ``token_budget_exceeded`` event to spiral_events.jsonl
    when truncation is triggered.

    Parameters
    ----------
    story:
        The story dict loaded from prd.json.
    model:
        Claude model alias or full ID (default: "sonnet").
    base_prompt:
        Content of the system/base prompt file (e.g. ralph/CLAUDE.md).
    budget:
        Maximum allowed token count (default: SPIRAL_CONTEXT_BUDGET_TOKENS
        env var or 150 000).
    scratch_dir:
        Directory containing spiral_events.jsonl (default: ".spiral").

    Returns
    -------
    (story_dict, token_count, was_truncated)
    """
    from truncate_context import truncate_story

    story_text = json.dumps(story, ensure_ascii=False)

    # Build messages list matching the real Claude invocation
    messages: list[dict[str, Any]] = []
    if base_prompt:
        messages.append({"role": "user", "content": base_prompt})
    messages.append({"role": "user", "content": story_text})

    token_count, method = count_tokens(messages, model)
    story_id = story.get("id", "unknown")

    if token_count <= budget:
        return story, token_count, False

    # ── Truncate ───────────────────────────────────────────────────────────
    base_tokens = _count_tokens_approx(base_prompt) if base_prompt else 0
    trimmed, original_total, final_total, dropped = truncate_story(story, base_tokens=base_tokens, limit=budget)

    # ── Emit event ─────────────────────────────────────────────────────────
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "token_budget_exceeded",
        "story_id": story_id,
        "model": model,
        "token_count": token_count,
        "budget": budget,
        "truncated_tokens": final_total,
        "dropped_fields": dropped,
        "method": method,
    }
    run_id = os.environ.get("SPIRAL_RUN_ID", "")
    if run_id:
        event["run_id"] = run_id
    _emit_event(event, scratch_dir)

    return trimmed, token_count, True


# ---------------------------------------------------------------------------
# Estimate helper (used by main.py estimate)
# ---------------------------------------------------------------------------


def estimate_pending_tokens(
    prd_path: str,
    model: str = "sonnet",
    budget: int = DEFAULT_BUDGET,
) -> dict[str, Any]:
    """
    Count how many pending stories would exceed *budget* and report stats.

    Returns a dict with:
      - pending: int        total pending stories
      - over_budget: int    stories whose story JSON alone exceeds budget
      - budget: int         token budget used
      - model: str          model alias used for counting
    """
    if not os.path.isfile(prd_path):
        return {"pending": 0, "over_budget": 0, "budget": budget, "model": model}

    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)

    pending = [
        s
        for s in prd.get("userStories", [])
        if not s.get("passes") and not s.get("_skipped") and not s.get("_decomposed")
    ]

    over_budget = 0
    for story in pending:
        story_text = json.dumps(story, ensure_ascii=False)
        messages: list[dict[str, Any]] = [{"role": "user", "content": story_text}]
        # Use approx only here to keep estimate fast (no API calls)
        approx = _count_tokens_approx(_messages_to_text(messages))
        if approx > budget:
            over_budget += 1

    return {
        "pending": len(pending),
        "over_budget": over_budget,
        "budget": budget,
        "model": model,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Token guard: pre-flight token count before Claude submission")
    parser.add_argument("--story", help="Story JSON string (reads from stdin if omitted)")
    parser.add_argument("--model", default="sonnet", help="Claude model alias (default: sonnet)")
    parser.add_argument(
        "--base-prompt-file",
        dest="base_prompt_file",
        help="Path to base system prompt file (counted toward budget)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=0,
        help="Token budget override (default: SPIRAL_CONTEXT_BUDGET_TOKENS or 150000)",
    )
    parser.add_argument(
        "--scratch-dir",
        dest="scratch_dir",
        default="",
        help="Directory for spiral_events.jsonl (default: SCRATCH_DIR env or .spiral)",
    )
    args = parser.parse_args(argv)

    # Read story JSON
    raw = args.story if args.story is not None else sys.stdin.read()
    if not raw.strip():
        print("[token_guard] ERROR: no story JSON provided", file=sys.stderr)
        return 1

    try:
        story = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[token_guard] ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(story, dict):
        print("[token_guard] ERROR: story JSON must be a dict", file=sys.stderr)
        return 1

    # Resolve budget
    budget = args.budget or int(os.environ.get("SPIRAL_CONTEXT_BUDGET_TOKENS", DEFAULT_BUDGET))

    # Resolve scratch dir
    scratch_dir = args.scratch_dir or os.environ.get("SCRATCH_DIR", ".spiral")

    # Resolve base prompt
    base_prompt = ""
    if args.base_prompt_file and os.path.isfile(args.base_prompt_file):
        try:
            with open(args.base_prompt_file, encoding="utf-8", errors="replace") as f:
                base_prompt = f.read()
        except OSError:
            pass

    trimmed, token_count, was_truncated = guard_story(
        story,
        model=args.model,
        base_prompt=base_prompt,
        budget=budget,
        scratch_dir=scratch_dir,
    )

    if was_truncated:
        warning = {
            "event": "token_budget_exceeded",
            "story_id": story.get("id", "unknown"),
            "token_count": token_count,
            "budget": budget,
        }
        print(json.dumps(warning), file=sys.stderr)

    print(json.dumps(trimmed, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
