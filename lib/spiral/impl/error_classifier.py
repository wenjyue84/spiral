"""
error_classifier.py — Phase I error classification engine.

Classifies error messages into 8 categories for smarter retry routing.
Also scans results.tsv to produce lib/error_patterns.jsonl with per-category
frequency counts and example snippets for observability.

Categories: timeout, oom, syntax, import, assertion, network, auth, unknown
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from enum import Enum
from pathlib import Path


class ErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    OOM = "oom"
    SYNTAX = "syntax"
    IMPORT = "import"
    ASSERTION = "assertion"
    NETWORK = "network"
    AUTH = "auth"
    UNKNOWN = "unknown"


# Suggestions per category for retry routing
_SUGGESTIONS: dict[str, str] = {
    ErrorCategory.TIMEOUT: "extend_timeout or decompose",
    ErrorCategory.OOM: "skip (OOM is unrecoverable without scope reduction)",
    ErrorCategory.SYNTAX: "same_model with syntax hint",
    ErrorCategory.IMPORT: "same_model with import hint",
    ErrorCategory.ASSERTION: "escalate_model",
    ErrorCategory.NETWORK: "same_model after network retry",
    ErrorCategory.AUTH: "skip (auth errors require manual intervention)",
    ErrorCategory.UNKNOWN: "escalate_model",
}


def classify_error(error_msg: str) -> ErrorCategory:
    """
    Classify an error message into one of 8 ErrorCategory values.

    Args:
        error_msg: raw error text (stderr, stdout, or story failure reason)

    Returns:
        ErrorCategory enum value
    """
    msg = error_msg.lower()

    # timeout — check before assertion so "timed out" wins over general "error"
    if any(p in msg for p in ("timeout", "timed out", "time limit exceeded", "deadline exceeded")):
        return ErrorCategory.TIMEOUT

    # oom — out-of-memory signals
    if any(p in msg for p in ("out of memory", "oom", "memoryerror", "heap overflow", "v8 heap")):
        return ErrorCategory.OOM

    # network — connection/HTTP errors
    if any(
        p in msg
        for p in (
            "connection refused",
            "connection error",
            "network error",
            "ssl error",
            "connectionreseterror",
            "httperror",
            "socket error",
            "name resolution",
        )
    ):
        return ErrorCategory.NETWORK

    # auth — permission/credential failures
    if any(
        p in msg
        for p in (
            "unauthorized",
            "authentication failed",
            "permission denied",
            "access denied",
            "invalid token",
            "api key",
            "forbidden",
            "401",
            "403",
        )
    ):
        return ErrorCategory.AUTH

    # import — module not found
    if any(
        p in msg
        for p in ("importerror", "modulenotfounderror", "no module named", "cannot import", "missing dependency")
    ):
        return ErrorCategory.IMPORT

    # syntax — syntax/indentation errors
    if any(p in msg for p in ("syntaxerror", "syntax error", "indentationerror", "invalid syntax", "unexpected token")):
        return ErrorCategory.SYNTAX

    # assertion — test failures
    if any(p in msg for p in ("assertionerror", "assert ", "failed", "pytest", "unittest", "test error")):
        return ErrorCategory.ASSERTION

    return ErrorCategory.UNKNOWN


def scan_results_tsv(
    results_tsv: str = "results.tsv",
    output_jsonl: str = "lib/error_patterns.jsonl",
) -> dict[str, dict[str, object]]:
    """
    Parse failure rows in results.tsv and append to lib/error_patterns.jsonl.

    Uses story_title as the error text proxy (results.tsv has no error_msg column).
    Writes one JSON line per category with frequency and up to 3 example snippets.

    Args:
        results_tsv: path to results.tsv
        output_jsonl: path to output JSON Lines file (append mode)

    Returns:
        dict mapping category → {frequency, examples, suggestion}
    """
    tsv_path = Path(results_tsv)
    if not tsv_path.exists():
        return {}

    counts: dict[str, int] = defaultdict(int)
    examples: dict[str, list[str]] = defaultdict(list)

    with tsv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            status = row.get("status", "")
            if status not in ("reject", "fail", "failed", "skip"):
                continue
            title = row.get("story_title", "").strip()
            if not title:
                continue
            cat = classify_error(title).value
            counts[cat] += 1
            if len(examples[cat]) < 3:
                examples[cat].append(title[:120])

    if not counts:
        return {}

    # Build result dict and append to JSONL
    result: dict[str, dict[str, object]] = {}
    output_path = Path(output_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("a", encoding="utf-8") as out:
        for cat, freq in sorted(counts.items(), key=lambda x: -x[1]):
            entry: dict[str, object] = {
                "error_type": cat,
                "frequency": freq,
                "examples": examples[cat],
                "suggestion": _SUGGESTIONS.get(cat, "escalate_model"),
            }
            out.write(json.dumps(entry) + "\n")
            result[cat] = entry

    return result
