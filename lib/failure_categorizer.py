#!/usr/bin/env python3
"""
lib/failure_categorizer.py — Phase I Retry Failure Categorizer (US-608).

Parses results.tsv to categorize per-story, per-retry failure types into
one of 6 named categories based on error message keyword matching.

Categories:
  test-failure         — AssertionError, pytest failures, FAILED, test error
  compilation-error    — SyntaxError, ImportError, NameError, compile error
  missing-dependency   — ModuleNotFoundError, No module named, package not found
  timeout              — timed out, TimeoutError, deadline exceeded
  token-limit          — out of memory, max_tokens, context_length, OOM
  type-error           — TypeError, AttributeError, attribute error
  other                — fallback when no pattern matches

Usage:
    from lib.failure_categorizer import categorize_message, categorize_iteration
    cat = categorize_message("AssertionError: expected True")   # "test-failure"
    results = categorize_iteration(3, Path("results.tsv"))
    # [{"story": "US-123", "retry1": "test-failure", "retry2": "token-limit"}]
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── Pattern registry ──────────────────────────────────────────────────────────
# Ordered: first match wins, most specific patterns first.

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "missing-dependency",
        re.compile(
            r"ModuleNotFoundError|No module named|package not found"
            r"|cannot find module|npm install|dependency not found",
            re.IGNORECASE,
        ),
    ),
    (
        "token-limit",
        re.compile(
            r"out of memory|max_tokens|context.?length|context.?window"
            r"|token.?limit|memory.?error|OOM|exceeds.*max|MemoryError",
            re.IGNORECASE,
        ),
    ),
    (
        "timeout",
        re.compile(
            r"timed?\s+out|TimeoutError|deadline.?exceeded|timeout.*expired"
            r"|execution.*timed|operation.*timed",
            re.IGNORECASE,
        ),
    ),
    (
        "compilation-error",
        re.compile(
            r"\bSyntaxError\b|\bImportError\b|\bNameError\b"
            r"|compile.?error|invalid.?syntax|unexpected.?token"
            r"|\bIndentationError\b",
            re.IGNORECASE,
        ),
    ),
    (
        "type-error",
        re.compile(
            r"\bTypeError\b|\bAttributeError\b|attribute.?error"
            r"|unsupported operand|not callable|has no attribute",
            re.IGNORECASE,
        ),
    ),
    (
        "test-failure",
        re.compile(
            r"\bAssertionError\b|FAILED|test.?error|pytest|assertion.?failed"
            r"|expected.*but.*got|test.*fail|fail.*test",
            re.IGNORECASE,
        ),
    ),
]


def categorize_message(text: str) -> str:
    """Return the first matching failure category for *text*, or 'other'.

    Args:
        text: Error message, log line, or story title containing failure info.

    Returns:
        One of: 'test-failure', 'compilation-error', 'missing-dependency',
                'timeout', 'token-limit', 'type-error', 'other'
    """
    for category, pattern in _PATTERNS:
        if pattern.search(text):
            return category
    return "other"


# ── results.tsv reader ────────────────────────────────────────────────────────


def _load_results(results_tsv: Path) -> list[dict[str, str]]:
    """Load results.tsv rows as list of dicts; returns [] if missing/malformed."""
    if not results_tsv.exists():
        return []
    rows: list[dict[str, str]] = []
    try:
        with open(results_tsv, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(dict(row))
    except OSError:
        pass
    return rows


# ── Per-iteration grouping ────────────────────────────────────────────────────


def categorize_iteration(
    iteration: int | None,
    results_tsv: Path | None = None,
) -> list[dict[str, str]]:
    """Parse results.tsv and return per-story retry categorization.

    For each story that has at least one failed/retried attempt in *iteration*
    (or across all iterations if iteration is None), return a dict with:
        {"story": "US-NNN", "retry1": "<category>", "retry2": "<category>", ...}

    The category is derived from the story_title column (used as a proxy for
    error message when no dedicated error column exists).

    Args:
        iteration: spiral_iter value to filter on; None means all iterations.
        results_tsv: Path to results.tsv (default: results.tsv in cwd).

    Returns:
        List of dicts, one per story, sorted by story_id.
    """
    tsv_path = results_tsv or Path("results.tsv")
    rows = _load_results(tsv_path)

    # Group failed/retried rows by story_id, preserving retry order
    # failed_rows[story_id] = list of rows in retry_num order
    failed_rows: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in rows:
        # Filter by iteration if specified
        if iteration is not None:
            row_iter_str = row.get("spiral_iter", "").strip()
            try:
                row_iter = int(row_iter_str)
            except (ValueError, TypeError):
                continue
            if row_iter != iteration:
                continue

        status = (row.get("status") or "").lower()
        if status not in ("fail", "retry", "failed", "error", "skip", "reject"):
            continue

        story_id = (row.get("story_id") or "").strip()
        if not story_id:
            continue

        failed_rows[story_id].append(row)

    # Build output records
    result: list[dict[str, str]] = []
    for story_id in sorted(failed_rows):
        record: dict[str, str] = {"story": story_id}
        # Sort attempts by retry_num, then by timestamp as tiebreak
        attempts = sorted(
            failed_rows[story_id],
            key=lambda r: (
                _safe_int(r.get("retry_num", "0")),
                r.get("timestamp", ""),
            ),
        )
        for i, attempt in enumerate(attempts, start=1):
            # Use story_title as categorization text (best available proxy)
            text = " ".join(
                filter(
                    None,
                    [
                        attempt.get("story_title", ""),
                        attempt.get("status", ""),
                    ],
                )
            )
            record[f"retry{i}"] = categorize_message(text)
        result.append(record)

    return result


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


# ── CLI entry point ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Standalone CLI: python -m lib.failure_categorizer [iteration] [--results TSV]."""
    import argparse

    parser = argparse.ArgumentParser(description="Categorize Phase I retry failures by story from results.tsv")
    parser.add_argument(
        "iteration",
        nargs="?",
        type=int,
        default=None,
        metavar="ITERATION",
        help="spiral_iter value to filter (omit for all iterations)",
    )
    parser.add_argument(
        "--results",
        default="results.tsv",
        metavar="TSV",
        help="Path to results.tsv (default: results.tsv)",
    )
    args = parser.parse_args(argv)

    result = categorize_iteration(
        iteration=args.iteration,
        results_tsv=Path(args.results),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
