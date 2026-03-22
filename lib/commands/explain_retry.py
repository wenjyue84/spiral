"""
lib/commands/explain_retry.py — Analyze retry sequence for a story_id (US-728).

Implements ``spiral explain-retry US-123``:
- Reads results.tsv for all attempts of the given story_id.
- Returns a JSON-serialisable list with fields:
    attempt (int), model (str), tokens (int), duration_sec (float),
    status (str), error_category (str)
- Generates a decomposition suggestion from ``failed_files`` column patterns.

Error categories (in priority order):
  scope_overrun      — diff guard / too many files / line limit exceeded
  token-limit        — context length / OOM errors
  timeout            — timed out / deadline exceeded
  missing-dependency — ModuleNotFoundError / package not found
  compilation-error  — SyntaxError / ImportError / NameError
  type-error         — TypeError / AttributeError
  test-failure       — AssertionError / pytest failures
  other              — unclassified
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Allow running as a standalone script
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from failure_categorizer import categorize_message  # noqa: E402
from results_tsv import parse_results_tsv  # noqa: E402

# Pattern for "scope overrun" — story too large for a single implementation
_SCOPE_OVERRUN_RE = re.compile(
    r"scope.?overrun|too.?large|too.?many.?files|diff.?guard"
    r"|exceed.*line|diff.*limit|lines.*guard|guard.*lines",
    re.IGNORECASE,
)


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _safe_float(value: str) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _sum_tokens(cache_read: str, cache_creation: str, review: str) -> int:
    """Return total tokens across all token-tracking fields."""
    return _safe_int(cache_read) + _safe_int(cache_creation) + _safe_int(review)


def _error_category(
    failure_root_cause: str,
    story_title: str,
    model: str,
    retry_num: int,
    duration_sec: float,
) -> str:
    """Derive error_category for a single attempt.

    Checks scope_overrun first (Ralph diff guard), then delegates to the
    shared categorize_message() pattern registry.
    """
    text = failure_root_cause or ""
    if _SCOPE_OVERRUN_RE.search(text):
        return "scope_overrun"
    # Heuristic: haiku on first attempt with very high duration → scope overrun
    if model == "haiku" and retry_num == 1 and duration_sec > 300:
        return "scope_overrun"
    if text:
        return str(categorize_message(text))
    return str(categorize_message(story_title))


def explain_retry_sequence(
    story_id: str,
    results_tsv_path: Path | None = None,
) -> list[dict[str, object]]:
    """Return the full retry sequence for *story_id* from results.tsv.

    Each element in the returned list is a dict with keys:
        attempt (int)       — 1-based attempt index
        model (str)         — model name (haiku / sonnet / opus / ...)
        tokens (int)        — total tokens (read + creation + review)
        duration_sec (float)— wall time of this attempt
        status (str)        — attempt status (failed / reject / pass / ...)
        error_category (str)— categorised root cause

    Returns an empty list when story_id is not found.
    """
    tsv_path = results_tsv_path or Path("results.tsv")
    records = parse_results_tsv(str(tsv_path))

    story_records = [r for r in records if r.story_id == story_id]
    if not story_records:
        return []

    # Sort deterministically: retry_num first, then timestamp as tiebreak
    story_records.sort(key=lambda r: (_safe_int(r.retry_num), r.timestamp))

    result: list[dict[str, object]] = []
    for i, rec in enumerate(story_records, start=1):
        dur = _safe_float(rec.duration_sec)
        retry = _safe_int(rec.retry_num)
        result.append(
            {
                "attempt": i,
                "model": rec.model or "unknown",
                "tokens": _sum_tokens(
                    rec.cache_read_tokens,
                    rec.cache_creation_tokens,
                    rec.review_tokens,
                ),
                "duration_sec": dur,
                "status": rec.status or "unknown",
                "error_category": _error_category(
                    failure_root_cause=rec.failure_root_cause or "",
                    story_title=rec.story_title or "",
                    model=rec.model or "",
                    retry_num=retry,
                    duration_sec=dur,
                ),
            }
        )
    return result


def suggest_decomposition(
    story_id: str,
    results_tsv_path: Path | None = None,
) -> str | None:
    """Suggest a story split based on file-level failure patterns.

    Aggregates ``failed_files`` values across all retry attempts, groups them
    by top-level directory, and returns a human-readable suggestion such as:
        'Split into 2 stories: US-123A (lib/ modules) and US-123B (tests/ modules)'

    Returns None when no failed-file data is available.
    """
    tsv_path = results_tsv_path or Path("results.tsv")
    records = parse_results_tsv(str(tsv_path))

    story_records = [r for r in records if r.story_id == story_id]
    if not story_records:
        return None

    # Collect all unique failed files across retries (order-preserving dedup)
    seen: set[str] = set()
    unique_files: list[str] = []
    for rec in story_records:
        if not rec.failed_files:
            continue
        try:
            files = json.loads(rec.failed_files)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(files, list):
            continue
        for f in files:
            s = str(f)
            if s not in seen:
                seen.add(s)
                unique_files.append(s)

    if not unique_files:
        return None

    # Group by top-level directory (first path part)
    groups: dict[str, list[str]] = {}
    for f in unique_files:
        parts = Path(f).parts
        key = parts[0] if parts else "root"
        groups.setdefault(key, []).append(f)

    group_keys = list(groups.keys())

    if len(group_keys) < 2:
        # Not enough distinct directories — split by position
        half = max(1, len(unique_files) // 2)
        group_a = unique_files[:half]
        group_b = unique_files[half:]
        if not group_b:
            return None
        label_a = ", ".join(group_a[:2])
        label_b = ", ".join(group_b[:2])
    else:
        dir_a = group_keys[0]
        dir_b = group_keys[1]
        files_a = groups[dir_a]
        files_b = groups[dir_b]
        label_a = f"{dir_a}/" if len(files_a) > 1 else files_a[0]
        label_b = f"{dir_b}/" if len(files_b) > 1 else files_b[0]

    return f"Split into 2 stories: {story_id}A ({label_a} modules) and {story_id}B ({label_b} modules)"
