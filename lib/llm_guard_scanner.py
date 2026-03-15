#!/usr/bin/env python3
"""SPIRAL — llm_guard_scanner.py

Wraps the LLM Guard PromptInjection input scanner to scan Phase R web-fetched
content for indirect prompt injection before it is assembled into LLM prompts.

Acceptance criteria (US-198):
  - Scan threshold configurable via SPIRAL_INJECTION_THRESHOLD (default 0.8)
  - Content exceeding threshold is replaced with a sanitized placeholder
  - Scan result (score, threshold, truncated) is returned as JSON for JSONL logging
  - Graceful fallback if llm-guard is not installed: warns and returns original text

Usage (library):
    from llm_guard_scanner import scan_content, ScanResult

    result = scan_content("web-fetched text", threshold=0.8)
    if result.truncated:
        print(f"Injection detected (score={result.score:.3f}) — content sanitized")

Usage (CLI — called from spiral.sh):
    python lib/llm_guard_scanner.py --threshold 0.8 --source "gemini_research" < content.txt
    # Returns JSON line: {"score": 0.95, "threshold": 0.8, "truncated": true, "text": "...", "source": "gemini_research"}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

# ── Constants ──────────────────────────────────────────────────────────────────

_PLACEHOLDER = (
    "[SPIRAL: web-fetched content was flagged as potential prompt injection "
    "and has been removed for safety. Threshold: {threshold:.2f}, Score: {score:.3f}]"
)

_DEFAULT_THRESHOLD = 0.8

# ── Data Types ─────────────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    """Result of scanning a single text block for prompt injection."""

    text: str           # sanitized text (original if not truncated)
    score: float        # injection risk score 0.0–1.0 (higher = more suspicious)
    threshold: float    # threshold used for this scan
    truncated: bool     # True if content was replaced with placeholder
    source: str         # label for the content source (e.g. "gemini_research")
    duration_ms: int    # wall-clock time for the scan in milliseconds

    def as_event_fields(self) -> dict:
        """Return fields suitable for embedding in a JSONL event."""
        return {
            "source": self.source,
            "score": round(self.score, 4),
            "threshold": self.threshold,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
        }


# ── Scanner implementation ─────────────────────────────────────────────────────

_scanner_cache: Optional[Any] = None   # lazy singleton; None = uninitialised
_guard_available: Optional[bool] = None   # None = not yet checked


def _load_scanner() -> Optional[Any]:
    """Lazy-load the LLM Guard PromptInjection scanner; returns None if unavailable."""
    global _scanner_cache, _guard_available

    if _guard_available is False:
        return None
    if _guard_available is True:
        return _scanner_cache

    try:
        from llm_guard.input_scanners import PromptInjection
        from llm_guard.input_scanners.prompt_injection import MatchType

        _scanner_cache = PromptInjection(match_type=MatchType.FULL)
        _guard_available = True
        return _scanner_cache
    except ImportError:
        _guard_available = False
        print(
            "  [llm-guard] WARNING: llm-guard not installed — "
            "skipping PromptInjection scan. Install with: uv add llm-guard",
            file=sys.stderr,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _guard_available = False
        print(
            f"  [llm-guard] WARNING: failed to initialise scanner ({exc}) — "
            "skipping PromptInjection scan",
            file=sys.stderr,
        )
        return None


def scan_content(
    text: str,
    threshold: Optional[float] = None,
    source: str = "unknown",
) -> ScanResult:
    """Scan *text* for prompt injection using LLM Guard.

    Args:
        text:      The web-fetched content to scan.
        threshold: Injection score above which content is sanitized.
                   Defaults to SPIRAL_INJECTION_THRESHOLD env var or 0.8.
        source:    Label describing where this content came from.

    Returns:
        ScanResult with sanitized text and scan metadata.
    """
    if threshold is None:
        threshold = float(os.environ.get("SPIRAL_INJECTION_THRESHOLD", _DEFAULT_THRESHOLD))

    # Clamp threshold to valid range
    threshold = max(0.0, min(1.0, threshold))

    t0 = time.monotonic()
    scanner = _load_scanner()

    if scanner is None:
        # llm-guard unavailable — pass through without scanning
        duration_ms = int((time.monotonic() - t0) * 1000)
        return ScanResult(
            text=text,
            score=0.0,
            threshold=threshold,
            truncated=False,
            source=source,
            duration_ms=duration_ms,
        )

    try:
        # LLM Guard scanner returns (sanitized_text, is_valid, risk_score)
        # is_valid=True means content is safe (below threshold)
        sanitized, is_valid, risk_score = scanner.scan("", text)
        duration_ms = int((time.monotonic() - t0) * 1000)

        score = float(risk_score) if risk_score is not None else 0.0
        truncated = not is_valid or score >= threshold

        if truncated:
            output_text = _PLACEHOLDER.format(threshold=threshold, score=score)
        else:
            output_text = text

        return ScanResult(
            text=output_text,
            score=score,
            threshold=threshold,
            truncated=truncated,
            source=source,
            duration_ms=duration_ms,
        )

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - t0) * 1000)
        print(
            f"  [llm-guard] WARNING: scan failed ({exc}) — passing content through",
            file=sys.stderr,
        )
        return ScanResult(
            text=text,
            score=0.0,
            threshold=threshold,
            truncated=False,
            source=source,
            duration_ms=duration_ms,
        )


# ── CLI entry point ────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scan stdin text for prompt injection via LLM Guard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Injection risk threshold 0.0–1.0 (default: SPIRAL_INJECTION_THRESHOLD "
            "env var or 0.8). Content scoring >= threshold is replaced with a placeholder."
        ),
    )
    p.add_argument(
        "--source",
        default="unknown",
        help="Label for the content source, included in JSON output (default: unknown).",
    )
    p.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format: 'json' emits a JSONL-compatible object; 'text' emits sanitized text only.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    text = sys.stdin.read()
    result = scan_content(text, threshold=args.threshold, source=args.source)

    if args.output == "text":
        sys.stdout.write(result.text)
    else:
        payload = {
            "score": round(result.score, 4),
            "threshold": result.threshold,
            "truncated": result.truncated,
            "source": result.source,
            "duration_ms": result.duration_ms,
            "text": result.text,
        }
        print(json.dumps(payload))

    return 0


if __name__ == "__main__":
    sys.exit(main())
