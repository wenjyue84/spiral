"""lib/test_classifier.py — Phase T: Test failure classification with root cause hints.

Classifies test failure snippets into typed categories with remediation hints
for downstream Phase T story generation (US-1337).

Usage:
    from lib.test_classifier import classify_test_failure
    result = classify_test_failure(snippet)
    # {'type': 'import_error', 'hint': 'missing import: numpy'}

CLI usage (annotate a JSONL file of failures):
    python lib/test_classifier.py --classify _test_failures.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


def classify_test_failure(snippet: str) -> dict[str, str]:
    """Classify a test failure snippet into a typed category with a remediation hint.

    Args:
        snippet: A string containing test output (one or more lines).

    Returns:
        dict with keys:
          - 'type': one of import_error, assertion_failure, syntax_error,
                    timeout, environment_error
          - 'hint': short remediation hint for Ralph to use
    """
    # ImportError / ModuleNotFoundError
    m = re.search(r"ImportError[:\s]+(.+)|ModuleNotFoundError[:\s]+No module named '([^']+)'", snippet)
    if m:
        missing = (m.group(1) or m.group(2) or "").strip().split("\n")[0][:80]
        hint = f"missing import: {missing}" if missing else "check import paths"
        return {"type": "import_error", "hint": hint}

    # AssertionError
    if re.search(r"AssertionError", snippet):
        m2 = re.search(r"AssertionError[:\s]*(.+)", snippet)
        detail = (m2.group(1) or "").strip()[:80] if m2 else ""
        hint = f"assertion failed: {detail}" if detail else "check assertion logic"
        return {"type": "assertion_failure", "hint": hint}

    # SyntaxError / IndentationError
    if re.search(r"SyntaxError|IndentationError", snippet):
        m3 = re.search(r"(SyntaxError|IndentationError)[:\s]*(.+)", snippet)
        detail = (m3.group(2) or "").strip()[:80] if m3 else ""
        hint = f"fix syntax: {detail}" if detail else "fix syntax error"
        return {"type": "syntax_error", "hint": hint}

    # TimeoutError / TimeoutExpired
    if re.search(r"TimeoutError|TimeoutExpired|timed out", snippet, re.IGNORECASE):
        return {"type": "timeout", "hint": "test timeout — may need scope reduction or mock"}

    # EnvironmentError / OSError / FileNotFoundError / PermissionError
    if re.search(r"EnvironmentError|OSError|FileNotFoundError|PermissionError|NotADirectoryError", snippet):
        m4 = re.search(r"(EnvironmentError|OSError|FileNotFoundError|PermissionError)[:\s]*(.+)", snippet)
        detail = (m4.group(2) or "").strip()[:80] if m4 else ""
        hint = f"environment issue: {detail}" if detail else "check environment setup"
        return {"type": "environment_error", "hint": hint}

    # Default fallback
    return {"type": "assertion_failure", "hint": "check test logic and dependencies"}


def annotate_failures_jsonl(jsonl_path: str) -> list[dict[str, Any]]:
    """Read a JSONL file of test failures and annotate each with classification.

    Each line must be a JSON object with at least a 'snippet' or 'message' field.
    Writes annotated results to <jsonl_path>.classified.json.

    Returns list of annotated failure dicts.
    """
    annotated: list[dict[str, Any]] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                record: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue

            snippet = record.get("snippet") or record.get("message") or ""
            line_number = record.get("line_number") or record.get("lineno") or i + 1
            failure_id = record.get("id") or record.get("test_id") or f"failure_{i}"

            classification = classify_test_failure(snippet)
            annotated.append(
                {
                    "failure_id": failure_id,
                    "type": classification["type"],
                    "hint": classification["hint"],
                    "snippet": snippet[:500],
                    "line_number": line_number,
                }
            )

    out_path = jsonl_path.replace(".jsonl", ".json").replace(".json", "_classified.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({entry["failure_id"]: entry for entry in annotated}, f, indent=2)

    print(f"[test_classifier] Annotated {len(annotated)} failures → {out_path}")
    return annotated


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--classify":
        annotate_failures_jsonl(sys.argv[2])
    else:
        print("Usage: python lib/test_classifier.py --classify <failures.jsonl>")
        sys.exit(1)
