#!/usr/bin/env python3
"""
lib/impl/stuck_diagnosis.py — Phase I: Stuck Story Diagnosis (US-788)

After 3+ identical failures, classify root cause to skip futile retries:
- model-resolvable: Syntax/logic errors fixable by better model
- scope-too-large: Timeout/token limit — story too big
- missing-knowledge: Import/undefined reference errors
- external-dependency: API/network failures — skip until dependency recovers

Usage:
  python lib/impl/stuck_diagnosis.py --story-id US-XXX \
    --failures failure1.txt failure2.txt failure3.txt \
    --prd prd.json

Input failure files: Plain text error messages (one file per attempt)

Output: Updates prd.json with _stuckDiagnosis field containing:
  {
    "story_id": "US-XXX",
    "classification": "scope-too-large",
    "recommended_action": "Split story into smaller sub-stories",
    "confidence": 0.95,
    "error_overlap_percent": 87.5
  }
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spiral_io import atomic_write_json, configure_utf8_stdout, safe_read_json

configure_utf8_stdout()

STORY_PREFIX = os.environ.get("SPIRAL_STORY_PREFIX", "US")


# ── Error pattern keywords for classification ────────────────────────────────

_SCOPE_PATTERNS = [
    "timeout",
    "timed out",
    "deadline exceeded",
    "killed",
    "context deadline",
    "operation timed out",
    "token limit",
    "max_tokens",
    "context length",
    "context window",
    "input too long",
    "prompt too long",
    "too many tokens",
    "output length",
]

_EXTERNAL_PATTERNS = [
    "api error",
    "rate limit",
    "overloaded",
    "503",
    "502",
    "500",
    "connection error",
    "connection refused",
    "network error",
    "could not resolve host",
    "unreachable",
    "http error",
    "tcp reset",
    "broken pipe",
]

_MISSING_KNOWLEDGE_PATTERNS = [
    "importerror",
    "modulenotfounderror",
    "nameerror",
    "undefined reference",
    "does not exist",
    "not found",
    "no such file",
    "nosuchmodule",
    "keyerror",
    "attributeerror",
    "type error",
]

_MODEL_RESOLVABLE_PATTERNS = [
    "syntaxerror",
    "parse error",
    "json decode",
    "invalid json",
    "unexpected token",
    "malformed",
    "assertionerror",
    "assertion failed",
    "test failed",
    "passes: false",
    "acceptance criteria",
    "expected ",
    "valueerror",
    "typeerror",
]


def _compute_similarity(text1: str, text2: str) -> float:
    """Compute string similarity between two texts using SequenceMatcher."""
    if not text1 or not text2:
        return 0.0
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def detect_identical_failures(
    failures: list[str],
    overlap_threshold: float = 0.70,
) -> tuple[bool, float]:
    """
    Check if 3+ failures have >70% error message overlap.

    Args:
        failures: List of error message strings
        overlap_threshold: Similarity threshold (0.0–1.0)

    Returns:
        (is_identical: bool, avg_overlap: float)
        - is_identical: True if at least 2 pairs of failures meet threshold
        - avg_overlap: Average similarity score across all pairs
    """
    if len(failures) < 2:
        return False, 0.0

    # Compute all pairwise similarities
    similarities: list[float] = []
    for i in range(len(failures)):
        for j in range(i + 1, len(failures)):
            sim = _compute_similarity(failures[i], failures[j])
            similarities.append(sim)

    if not similarities:
        return False, 0.0

    avg_overlap = sum(similarities) / len(similarities)

    # Check if at least 50% of pairs meet threshold
    matching_pairs = sum(1 for s in similarities if s >= overlap_threshold)
    threshold_met = matching_pairs >= len(similarities) * 0.5

    return threshold_met, avg_overlap


def classify_failure(error_messages: list[str]) -> str:
    """
    Classify root cause based on error patterns.

    Classification order (first match wins):
    1. External dependency (API/network errors)
    2. Scope too large (timeout/token limit)
    3. Missing knowledge (import/reference errors)
    4. Model resolvable (syntax/logic errors)
    5. Unknown (no patterns matched)
    """
    # Merge all messages to search across all attempts
    combined_text = " ".join(m.lower() for m in error_messages if m)

    # Check patterns in priority order
    if any(p in combined_text for p in _EXTERNAL_PATTERNS):
        return "external-dependency"

    if any(p in combined_text for p in _SCOPE_PATTERNS):
        return "scope-too-large"

    if any(p in combined_text for p in _MISSING_KNOWLEDGE_PATTERNS):
        return "missing-knowledge"

    if any(p in combined_text for p in _MODEL_RESOLVABLE_PATTERNS):
        return "model-resolvable"

    return "unknown"


def get_recommended_action(classification: str) -> str:
    """Return actionable recommendation based on classification."""
    actions = {
        "external-dependency": (
            "Skip story until dependency recovers. Check service status and API keys. "
            "Retry after monitoring shows recovery."
        ),
        "scope-too-large": (
            "Split story into smaller sub-stories. "
            "Reduce filesTouch scope or increase SPIRAL_WORKER_TIMEOUT. "
            "Consider decomposing into 2-3 atomic tasks."
        ),
        "missing-knowledge": (
            "Review story context for missing domain knowledge. "
            "Add architectural notes or API references to the PRD. "
            "Inspect error logs for specific missing imports or references."
        ),
        "model-resolvable": (
            "Review PRD description for ambiguity or missing implementation details. "
            "Check test output for specific assertion failures. "
            "Consider adding example input/output to acceptance criteria."
        ),
        "unknown": (
            "Inspect .spiral/logs/ for raw error output. "
            "Manually decompose story or add additional context to PRD. "
            "Consider marking with _antiPatterns if pattern is known."
        ),
    }
    return actions.get(classification, actions["unknown"])


def diagnose(
    story_id: str,
    failures: list[str],
    overlap_threshold: float = 0.70,
) -> dict[str, Any]:
    """
    Main diagnosis function: analyze failures and return classification.

    Args:
        story_id: Story identifier (e.g. "US-123")
        failures: List of error message strings from attempts
        overlap_threshold: Similarity threshold (default 0.70)

    Returns:
        Dict with keys:
        - story_id: Story identifier
        - classification: One of {model-resolvable, scope-too-large, missing-knowledge, external-dependency, unknown}
        - recommended_action: Actionable next step
        - confidence: Confidence score (0.0–1.0)
        - error_overlap_percent: Percentage of error similarity (0.0–100.0)
        - failures_analyzed: Number of failures analyzed
    """
    if not failures or all(not f for f in failures):
        return {
            "story_id": story_id,
            "classification": "unknown",
            "recommended_action": get_recommended_action("unknown"),
            "confidence": 0.0,
            "error_overlap_percent": 0.0,
            "failures_analyzed": 0,
        }

    # Detect if failures are identical (>70% overlap)
    is_identical, avg_overlap = detect_identical_failures(failures, overlap_threshold)

    # Classify based on error patterns
    classification = classify_failure(failures)

    # Compute confidence: higher if failures are identical
    confidence = min(1.0, avg_overlap) if is_identical else 0.5

    return {
        "story_id": story_id,
        "classification": classification,
        "recommended_action": get_recommended_action(classification),
        "confidence": round(confidence, 2),
        "error_overlap_percent": round(avg_overlap * 100, 1),
        "failures_analyzed": len(failures),
    }


def update_story_with_diagnosis(
    prd_path: str,
    story_id: str,
    diagnosis: dict[str, Any],
) -> bool:
    """
    Update prd.json with _stuckDiagnosis field on the story.

    Args:
        prd_path: Path to prd.json
        story_id: Story ID to update
        diagnosis: Diagnosis dict from diagnose()

    Returns:
        True if updated successfully, False otherwise
    """
    data = safe_read_json(prd_path)
    if not data or "userStories" not in data:
        return False

    # Find and update story
    for story in data["userStories"]:
        if story.get("id") == story_id:
            story["_stuckDiagnosis"] = diagnosis
            atomic_write_json(prd_path, data, backup=True)
            return True

    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose root cause of repeated story failures.",
    )
    parser.add_argument("--story-id", required=True, help="Story ID (e.g. US-123)")
    parser.add_argument(
        "--failures",
        nargs="+",
        required=True,
        help="Failure message files (one per attempt)",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--overlap-threshold",
        type=float,
        default=0.70,
        help="Similarity threshold for identical failure detection (default: 0.70)",
    )
    args = parser.parse_args()

    # Read failure messages from files
    failure_messages: list[str] = []
    for failure_file in args.failures:
        if os.path.isfile(failure_file):
            try:
                with open(failure_file, encoding="utf-8", errors="replace") as f:
                    failure_messages.append(f.read())
            except Exception as e:
                print(f"[stuck_diagnosis] WARNING: could not read {failure_file}: {e}", file=sys.stderr)
        else:
            print(f"[stuck_diagnosis] WARNING: file not found: {failure_file}", file=sys.stderr)

    if not failure_messages:
        print("[stuck_diagnosis] ERROR: no failure messages to analyze", file=sys.stderr)
        sys.exit(1)

    # Run diagnosis
    diagnosis = diagnose(args.story_id, failure_messages, args.overlap_threshold)

    # Update prd.json
    if update_story_with_diagnosis(args.prd, args.story_id, diagnosis):
        print(f"[stuck_diagnosis] {args.story_id}: {diagnosis['classification']}")
        print(f"[stuck_diagnosis] Overlap: {diagnosis['error_overlap_percent']}%")
        print(f"[stuck_diagnosis] Confidence: {diagnosis['confidence']:.2f}")
        print(f"[stuck_diagnosis] Recommendation: {diagnosis['recommended_action']}")
        # Also output JSON for logging
        print(json.dumps(diagnosis, indent=2), file=sys.stderr)
    else:
        print(f"[stuck_diagnosis] ERROR: could not update {args.prd} for {args.story_id}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
