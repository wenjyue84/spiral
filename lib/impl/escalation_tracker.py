#!/usr/bin/env python3
"""lib/impl/escalation_tracker.py — Track model escalations with categorized reason codes.

Detects why a story was escalated (token_limit, syntax_error, timeout, api_error)
and writes entries to .spiral/escalations.json for dashboard analysis (US-646).

Usage:
  uv run python lib/impl/escalation_tracker.py \\
    --story-id US-001 \\
    --attempt 1 \\
    --model-used haiku \\
    --retry-model sonnet \\
    --stderr-file /path/to/stderr.txt

Output format (.spiral/escalations.json):
  [
    {
      "story": "US-001",
      "attempt": 1,
      "model_used": "haiku",
      "reason": "token_limit",
      "tokens_haiku": 95000,
      "retry_model": "sonnet",
      "timestamp": "2026-03-21T12:00:00Z"
    }
  ]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["detect_reason_code", "write_escalation", "EscalationReason"]


class EscalationReason:
    """Categorized reason codes for model escalation."""

    TOKEN_LIMIT = "token_limit"
    SYNTAX_ERROR = "syntax_error"
    TIMEOUT = "timeout"
    API_ERROR = "api_error"

    VALID = {TOKEN_LIMIT, SYNTAX_ERROR, TIMEOUT, API_ERROR}


def detect_reason_code(stderr_text: str) -> str:
    """Detect escalation reason from Ralph stderr output.

    Heuristic order:
      1. Token limit: "context.*exceed|token.*limit|prompt.*too.*long|95000|context.*full"
      2. Timeout: "timeout|timed out|deadline.*exceeded"
      3. Syntax error: "SyntaxError|invalid syntax|parse error"
      4. API error: "api.*error|rate.*limit|authentication"
      5. Default: "api_error"
    """
    if not stderr_text:
        return EscalationReason.API_ERROR

    text_lower = stderr_text.lower()

    # Token limit patterns
    if re.search(
        r"context.*exceed|token.*limit|prompt.*too.*long|95000|context.*full|"
        r"input.*exceeds|exceed.*max|token.*budget",
        text_lower,
    ):
        return EscalationReason.TOKEN_LIMIT

    # Timeout patterns
    if re.search(r"timeout|timed out|deadline.*exceeded|timeout.*error", text_lower):
        return EscalationReason.TIMEOUT

    # Syntax error patterns
    if re.search(
        r"syntaxerror|invalid syntax|parse error|unexpected token|"
        r"malformed.*json|json.*decode",
        text_lower,
    ):
        return EscalationReason.SYNTAX_ERROR

    # API error patterns
    if re.search(
        r"api.*error|rate.*limit|authentication.*fail|permission.*denied|"
        r"api.*unavailable|service.*error",
        text_lower,
    ):
        return EscalationReason.API_ERROR

    # Default fallback
    return EscalationReason.API_ERROR


def write_escalation(
    story_id: str,
    attempt: int,
    model_used: str,
    reason: str,
    retry_model: str,
    tokens_used: int = 0,
    escalations_file: str | None = None,
) -> bool:
    """Write an escalation entry to .spiral/escalations.json.

    Parameters
    ----------
    story_id : str
        Story identifier (e.g., 'US-001')
    attempt : int
        Attempt number (1-based)
    model_used : str
        Model that failed (e.g., 'claude-haiku-4-5-20251001')
    reason : str
        Reason code (token_limit, syntax_error, timeout, api_error)
    retry_model : str
        Model to retry with (e.g., 'claude-sonnet-4-6')
    tokens_used : int, optional
        Estimated tokens used (default: 0)
    escalations_file : str, optional
        Path to escalations.json (default: .spiral/escalations.json)

    Returns
    -------
    bool
        True on success, False on write error
    """
    if reason not in EscalationReason.VALID:
        reason = EscalationReason.API_ERROR

    if escalations_file is None:
        escalations_file = ".spiral/escalations.json"

    # Ensure parent directory exists
    Path(escalations_file).parent.mkdir(parents=True, exist_ok=True)

    # Load existing entries or start fresh
    entries: list[dict[str, Any]] = []
    if Path(escalations_file).exists():
        try:
            with open(escalations_file, encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, IOError):
            entries = []

    # Append new escalation entry
    entry = {
        "story": story_id,
        "attempt": attempt,
        "model_used": model_used,
        "reason": reason,
        "tokens_used": tokens_used,
        "retry_model": retry_model,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    entries.append(entry)

    # Write updated file
    try:
        with open(escalations_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"[escalation_tracker] Failed to write {escalations_file}: {e}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Record a model escalation with categorized reason code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python lib/impl/escalation_tracker.py \\
    --story-id US-001 --attempt 1 --model-used haiku \\
    --retry-model sonnet --stderr-file /tmp/stderr.txt

  uv run python lib/impl/escalation_tracker.py \\
    --story-id US-002 --attempt 2 --model-used sonnet \\
    --retry-model opus --reason timeout
""",
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g., US-001)")
    parser.add_argument("--attempt", type=int, required=True, help="Attempt number (1-based)")
    parser.add_argument("--model-used", required=True, help="Model that failed (e.g., claude-haiku-4-5-20251001)")
    parser.add_argument("--retry-model", required=True, help="Model to retry with (e.g., claude-sonnet-4-6)")
    parser.add_argument(
        "--reason",
        choices=list(EscalationReason.VALID),
        default=None,
        help="Reason code (auto-detect if not specified)",
    )
    parser.add_argument(
        "--stderr-file",
        default=None,
        help="Path to Ralph stderr file for auto-detection",
    )
    parser.add_argument(
        "--tokens-used",
        type=int,
        default=0,
        help="Estimated tokens used (optional)",
    )
    parser.add_argument(
        "--escalations-file",
        default=".spiral/escalations.json",
        help="Path to escalations.json (default: .spiral/escalations.json)",
    )

    args = parser.parse_args(argv)

    # Determine reason: explicit > auto-detect > default
    reason = args.reason
    if not reason and args.stderr_file and Path(args.stderr_file).exists():
        try:
            with open(args.stderr_file, encoding="utf-8") as f:
                stderr_text = f.read()
            reason = detect_reason_code(stderr_text)
        except IOError:
            reason = EscalationReason.API_ERROR
    elif not reason:
        reason = EscalationReason.API_ERROR

    # Write escalation entry
    success = write_escalation(
        story_id=args.story_id,
        attempt=args.attempt,
        model_used=args.model_used,
        reason=reason,
        retry_model=args.retry_model,
        tokens_used=args.tokens_used,
        escalations_file=args.escalations_file,
    )

    if not success:
        sys.exit(1)

    print(f"Escalation recorded: {args.story_id} (attempt {args.attempt}) → {reason}")


if __name__ == "__main__":
    main()
