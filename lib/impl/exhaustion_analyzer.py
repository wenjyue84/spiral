#!/usr/bin/env python3
"""
exhaustion_analyzer.py — Post-mortem analysis for stories that exhausted max retries.

When a story fails haiku→sonnet→opus, this module categorizes the root cause,
generates a suggestion, and returns a structured report for saving to
.spiral/exhausted_stories/{story_id}_analysis.json.

Usage (from retry.sh after 3rd failure):
    python lib/impl/exhaustion_analyzer.py --story-id US-123 --attempts attempts.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# ── Error keyword patterns ────────────────────────────────────────────────────

_TIMEOUT_PATTERNS = [
    "timeout",
    "timed out",
    "deadline exceeded",
    "killed",
    "context deadline",
    "operation timed out",
]

_TOKEN_LIMIT_PATTERNS = [
    "token limit",
    "max_tokens",
    "context length",
    "context window",
    "input too long",
    "prompt too long",
    "too many tokens",
    "output length",
]

_ASSERTION_PATTERNS = [
    "assertionerror",
    "assert ",
    "assertion failed",
    "expected ",
    "acceptance criteria",
    "passes: false",
    "test failed",
    "pytest",
    "unittest",
]

_PARSE_PATTERNS = [
    "syntaxerror",
    "parse error",
    "json decode",
    "invalid json",
    "unexpected token",
    "malformed",
    "cannot parse",
    "parsing failed",
]

_API_ERROR_PATTERNS = [
    "api error",
    "rate limit",
    "overloaded",
    "503",
    "502",
    "500",
    "connection error",
    "network error",
    "anthropic",
    "openai",
    "model error",
]


def _classify_error(error_text: str) -> str:
    """Classify a single error string into a root cause category."""
    lower = error_text.lower()
    if any(p in lower for p in _TIMEOUT_PATTERNS):
        return "timeout"
    if any(p in lower for p in _TOKEN_LIMIT_PATTERNS):
        return "token_limit"
    if any(p in lower for p in _ASSERTION_PATTERNS):
        return "assertion"
    if any(p in lower for p in _PARSE_PATTERNS):
        return "parse"
    if any(p in lower for p in _API_ERROR_PATTERNS):
        return "api_error"
    return "unknown"


def _build_suggestion(root_cause: str, is_repeated: bool) -> str:
    """Return an actionable suggestion based on root cause."""
    suggestions: dict[str, str] = {
        "timeout": (
            "Split story into smaller sub-stories. "
            "Consider setting SPIRAL_WORKER_TIMEOUT higher or decomposing into 2-3 sub-tasks."
        ),
        "token_limit": (
            "Story context is too large. "
            "Reduce filesTouch scope, split into sub-stories, or use a model with larger context window."
        ),
        "assertion": (
            "Acceptance criteria not met across all attempts. "
            "Add _decomposed antiPattern. Review ACs for ambiguity or missing implementation context."
        ),
        "parse": (
            "Model output could not be parsed. "
            "Inspect ralph output logs. Story may have malformed JSON in prd.json or ambiguous description."
        ),
        "api_error": (
            "API errors prevented completion. "
            "Check API key validity, rate limits, and model availability. Retry after cooling off."
        ),
        "unknown": (
            "Error pattern unclear. Inspect .spiral/logs/ for raw ralph output. Consider manual decomposition."
        ),
    }
    suggestion = suggestions.get(root_cause, suggestions["unknown"])
    if is_repeated and root_cause == "assertion":
        suggestion += " Mark story as _decomposed: true and add _antiPatterns entry."
    return suggestion


def analyze_exhausted_story(
    story_id: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Analyze a story that exhausted all retry attempts.

    Args:
        story_id: Story identifier (e.g. "US-123")
        attempts: List of attempt dicts, each with keys:
            - attempt_num: int
            - model: str
            - error: str  (error message or empty string)
            - exit_code: int
            - duration_seconds: float

    Returns:
        Dict with keys:
            root_cause: str (timeout|token_limit|assertion|parse|api_error|unknown)
            error_pattern: str (most common error substring)
            suggestion: str (actionable next step)
            model_sequence: list[str]
            error_counts: dict[str, int]
            most_common_tokens_in_failures: list[str]
            confidence_score: float (0.0–1.0)
            attempts_analyzed: int
    """
    if not attempts:
        return {
            "root_cause": "unknown",
            "error_pattern": "",
            "suggestion": _build_suggestion("unknown", False),
            "model_sequence": [],
            "error_counts": {},
            "most_common_tokens_in_failures": [],
            "confidence_score": 0.0,
            "attempts_analyzed": 0,
        }

    # Build model sequence
    model_sequence = [str(a.get("model", "unknown")) for a in attempts]

    # Classify each attempt
    error_counts: dict[str, int] = {}
    classified: list[str] = []
    error_texts: list[str] = []

    for attempt in attempts:
        error_text = str(attempt.get("error", ""))
        error_texts.append(error_text)
        category = _classify_error(error_text)
        classified.append(category)
        error_counts[category] = error_counts.get(category, 0) + 1

    # Root cause = most frequent classification
    root_cause = max(error_counts, key=lambda k: error_counts[k])

    # Confidence = fraction of attempts sharing the same root cause
    total_attempts = len(attempts)
    matching = error_counts[root_cause]
    confidence_score = round(matching / total_attempts, 2) if total_attempts > 0 else 0.0

    # Error pattern = most common 3-word substring in error messages
    all_words: list[str] = []
    for text in error_texts:
        words = text.lower().split()
        all_words.extend(words[:20])  # cap per-attempt contribution

    # Find most common meaningful words (skip single chars and common stopwords)
    stopwords = {"the", "a", "an", "in", "of", "to", "and", "or", "is", "was", "for"}
    word_freq: dict[str, int] = {}
    for w in all_words:
        cleaned = w.strip(".,;:\"'()[]{}")
        if len(cleaned) > 2 and cleaned not in stopwords:
            word_freq[cleaned] = word_freq.get(cleaned, 0) + 1

    top_tokens = sorted(word_freq, key=lambda k: word_freq[k], reverse=True)[:5]

    # Error pattern: join the top tokens as representative pattern
    error_pattern = " ".join(top_tokens) if top_tokens else root_cause

    # Is the root cause repeated consistently (same error each time)?
    is_repeated = confidence_score >= 0.67

    suggestion = _build_suggestion(root_cause, is_repeated)

    return {
        "story_id": story_id,
        "root_cause": root_cause,
        "error_pattern": error_pattern,
        "suggestion": suggestion,
        "model_sequence": model_sequence,
        "error_counts": error_counts,
        "most_common_tokens_in_failures": top_tokens,
        "confidence_score": confidence_score,
        "attempts_analyzed": total_attempts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze exhausted story retry attempts and output root cause JSON.")
    parser.add_argument("--story-id", required=True, help="Story ID, e.g. US-123")
    parser.add_argument(
        "--attempts",
        required=True,
        help="JSON file with list of attempt dicts (attempt_num, model, error, exit_code, duration_seconds)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output file path, or '-' for stdout (default: stdout)",
    )
    args = parser.parse_args()

    with open(args.attempts) as f:
        attempts: list[dict[str, Any]] = json.load(f)

    result = analyze_exhausted_story(args.story_id, attempts)

    output_json = json.dumps(result, indent=2)
    if args.output == "-":
        print(output_json)
    else:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as out:
            out.write(output_json + "\n")
        print(f"[exhaustion_analyzer] Report saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
