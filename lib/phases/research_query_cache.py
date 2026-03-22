"""research_query_cache.py — Query+context-level dedup cache for Phase R.

Implements get_or_research() which hashes (query, context) using SHA256,
checks .spiral/research_cache.json for a cached result, and either returns
the cached entry or calls gemini_client(query) on a miss.

Cache entry format (keyed by SHA256(query + str(sorted(context.items())))):
    {
        "content":     "<research text>",
        "timestamp":   "2026-03-22T12:34:56Z",
        "source":      "gemini",
        "usage_count": 1
    }

Usage:
    from lib.phases.research_query_cache import get_or_research, ResearchResult

    def my_gemini_client(query: str) -> str:
        ...  # call the Gemini API

    result: ResearchResult = get_or_research(
        query="SPIRAL autonomous loop research",
        query_context={"focus": "testing"},
        gemini_client=my_gemini_client,
    )
    if result["cached"]:
        print("Cache hit! Skipped Gemini API call.")
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
from typing import Any, TypedDict


# Default paths (can be overridden in tests)
_DEFAULT_CACHE_FILE = os.path.join(".spiral", "research_cache.json")
_DEFAULT_RESULTS_TSV = "results.tsv"

# TSV column header (mirrors results.tsv schema)
_TSV_HEADER = [
    "timestamp",
    "spiral_iter",
    "ralph_iter",
    "story_id",
    "story_title",
    "status",
    "duration_sec",
    "model",
    "retry_num",
    "commit_sha",
    "run_id",
    "cache_hit",
    "cache_read_tokens",
    "cache_creation_tokens",
    "review_tokens",
    "wall_seconds",
    "user_cpu_s",
    "sys_cpu_s",
    "peak_rss_kb",
    "batch_id",
]


class ResearchResult(TypedDict):
    """Return value from get_or_research()."""

    content: str
    cached: bool
    query_hash: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _compute_hash(query: str, query_context: dict[str, Any]) -> str:
    """Return SHA256 hex digest of query + str(sorted context items)."""
    raw = query + str(sorted(query_context.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_cache(cache_path: str) -> dict[str, Any]:
    """Load cache JSON from *cache_path*. Return empty dict on miss/corrupt."""
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data: Any = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, Any], cache_path: str) -> None:
    """Atomically write *cache* to *cache_path*."""
    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        if os.path.exists(cache_path):
            os.remove(cache_path)
        os.rename(tmp_path, cache_path)
    except OSError:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _record_cache_hit(results_tsv: str, query_hash: str) -> None:
    """Append a cache-hit event row to *results_tsv*.

    The row sets cache_hit=true and uses the first 16 chars of query_hash
    as a human-readable story_id surrogate.  All token/timing fields are 0.
    """
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = [
        ts,               # timestamp
        "",               # spiral_iter
        "",               # ralph_iter
        query_hash[:16],  # story_id — short hash for traceability
        "research_query_cache_hit",  # story_title
        "cache_hit",      # status
        "0",              # duration_sec
        "n/a",            # model
        "0",              # retry_num
        "",               # commit_sha
        "",               # run_id
        "true",           # cache_hit  ← key field
        "0",              # cache_read_tokens
        "0",              # cache_creation_tokens
        "0",              # review_tokens
        "0",              # wall_seconds
        "0",              # user_cpu_s
        "0",              # sys_cpu_s
        "0",              # peak_rss_kb
        "",               # batch_id
    ]
    needs_header = (
        not os.path.exists(results_tsv) or os.path.getsize(results_tsv) == 0
    )
    results_dir = os.path.dirname(results_tsv)
    if results_dir:
        os.makedirs(results_dir, exist_ok=True)
    with open(results_tsv, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if needs_header:
            writer.writerow(_TSV_HEADER)
        writer.writerow(row)


# ── Public API ────────────────────────────────────────────────────────────────


def get_or_research(
    query: str,
    query_context: dict[str, Any],
    gemini_client: Any,
    *,
    cache_path: str | None = None,
    results_tsv: str | None = None,
) -> ResearchResult:
    """Return a cached research result or call *gemini_client* on a miss.

    Cache key = SHA256(query + str(sorted(query_context.items()))).
    Identical (query, context) pairs always return the same cached content
    without invoking *gemini_client* again.

    On a cache hit the entry's ``usage_count`` is incremented and a row
    with ``cache_hit=true`` is appended to *results_tsv*.

    Args:
        query:          The research query string.
        query_context:  Additional context dict (affects the cache key).
        gemini_client:  Callable ``(query: str) -> str`` — the Gemini API.
        cache_path:     Override cache file path (default: .spiral/research_cache.json).
        results_tsv:    Override results TSV path (default: results.tsv).

    Returns:
        ResearchResult with ``content``, ``cached`` flag, and ``query_hash``.
    """
    _cache_path = cache_path if cache_path is not None else _DEFAULT_CACHE_FILE
    _results_tsv = results_tsv if results_tsv is not None else _DEFAULT_RESULTS_TSV

    query_hash = _compute_hash(query, query_context)
    cache = _load_cache(_cache_path)

    if query_hash in cache:
        entry = cache[query_hash]
        if isinstance(entry, dict) and "content" in entry:
            # Cache hit — increment usage_count and record event
            entry["usage_count"] = int(entry.get("usage_count", 0)) + 1
            _save_cache(cache, _cache_path)
            _record_cache_hit(_results_tsv, query_hash)
            return ResearchResult(
                content=str(entry["content"]),
                cached=True,
                query_hash=query_hash,
            )

    # Cache miss — call the Gemini client
    content = str(gemini_client(query))

    cache[query_hash] = {
        "content": content,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "gemini",
        "usage_count": 1,
    }
    _save_cache(cache, _cache_path)

    return ResearchResult(
        content=content,
        cached=False,
        query_hash=query_hash,
    )
