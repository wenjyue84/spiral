"""research_cache.py — URL-level cache for Phase R research responses.

Caches fetched URL content in .spiral/research_cache/<md5-of-url>.json
with a configurable TTL. Eliminates redundant HTTP fetches across iterations.

Supports cosine-similarity lookup (US-403): when a query doesn't match any
cached URL exactly, computes sentence embeddings and returns the best match
above SPIRAL_CACHE_SIM_THRESHOLD (default 0.92).

Usage (CLI):
    python research_cache.py store      CACHE_DIR URL CONTENT_FILE
    python research_cache.py lookup     CACHE_DIR URL --ttl-hours 24
    python research_cache.py sim-lookup CACHE_DIR QUERY --ttl-hours 24 --threshold 0.92
    python research_cache.py prune      CACHE_DIR --ttl-hours 24
    python research_cache.py list       CACHE_DIR --ttl-hours 24
    python research_cache.py inject     CACHE_DIR --ttl-hours 24
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any


def _cache_key(url: str) -> str:
    """Return MD5 hex digest of a normalised URL."""
    normalised = url.strip().rstrip("/")
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: str, url: str) -> str:
    return os.path.join(cache_dir, f"{_cache_key(url)}.json")


def _now_ts() -> float:
    return time.time()


def _is_valid(entry: dict[str, Any], ttl_hours: float) -> bool:
    """Return True if the cache entry is within TTL."""
    if ttl_hours <= 0:
        return False  # cache disabled
    fetched_ts = entry.get("fetched_ts", 0)
    age_hours = (_now_ts() - fetched_ts) / 3600
    return bool(age_hours < ttl_hours)


# ── Embedding helpers (US-403) ───────────────────────────────────────────────

_model: Any = None  # lazy singleton


def _get_model() -> Any:
    """Lazy-load the MiniLM sentence-transformer model (one-time ~1s)."""
    global _model  # noqa: PLW0603
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def _compute_embedding(text: str) -> "Any":
    """Return a 1-D numpy array embedding for *text*."""
    import numpy as np

    model = _get_model()
    vec = model.encode(text, show_progress_bar=False)
    return np.asarray(vec, dtype=np.float32)


def _embedding_path(cache_dir: str, query: str) -> str:
    """Return path for the .npy embedding file keyed by SHA-256 of *query*."""
    digest = hashlib.sha256(query.strip().encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{digest}.npy")


def _cosine_similarity(a: "Any", b: "Any") -> float:
    """Cosine similarity between two 1-D numpy vectors."""
    import numpy as np

    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def cache_similarity_lookup(
    cache_dir: str,
    query: str,
    ttl_hours: float,
    threshold: float = 0.92,
) -> str | None:
    """Find the best cosine-similarity match among cached embeddings.

    Returns cached content if similarity >= *threshold*, else None.
    threshold >= 1.0 disables similarity (exact match only fallback).
    """
    import numpy as np

    if threshold >= 1.0:
        return None  # similarity disabled
    if ttl_hours <= 0:
        return None
    if not os.path.isdir(cache_dir):
        return None

    query_vec = _compute_embedding(query)

    best_sim = -1.0
    best_content: str | None = None

    for fname in os.listdir(cache_dir):
        if not fname.endswith(".npy"):
            continue
        if fname.endswith(".npy.key"):
            continue  # skip mapping files
        npy_path = os.path.join(cache_dir, fname)
        try:
            cached_vec = np.load(npy_path)
        except Exception:
            continue

        sim = _cosine_similarity(query_vec, cached_vec)
        if sim < threshold or sim <= best_sim:
            continue

        # Use .key mapping file to find the corresponding .json
        key_path = npy_path + ".key"
        json_key: str | None = None
        if os.path.exists(key_path):
            try:
                with open(key_path, "r", encoding="utf-8") as f:
                    json_key = f.read().strip()
            except OSError:
                pass

        if json_key:
            json_path = os.path.join(cache_dir, f"{json_key}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        entry = json.load(f)
                    if _is_valid(entry, ttl_hours):
                        best_sim = sim
                        best_content = entry.get("content")
                except (json.JSONDecodeError, OSError):
                    pass

    return best_content


def cache_store(cache_dir: str, url: str, content: str, *, store_embedding: bool = True) -> str:
    """Store URL content in the cache. Returns the cache file path.

    When *store_embedding* is True (default), also saves a sentence embedding
    as a .npy file alongside the JSON for cosine-similarity lookups.
    """
    import numpy as np

    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, url)
    entry = {
        "url": url.strip(),
        "fetched_ts": _now_ts(),
        "content": content,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)

    # Save embedding for similarity lookup (US-403)
    if store_embedding:
        try:
            vec = _compute_embedding(url.strip())
            npy_path = _embedding_path(cache_dir, url.strip())
            np.save(npy_path, vec)
            # Also store a mapping file so we can find JSON from .npy
            mapping_path = npy_path + ".key"
            with open(mapping_path, "w", encoding="utf-8") as f:
                f.write(_cache_key(url))
        except Exception:
            pass  # embedding is optional; don't break cache on failure

    return path


def cache_lookup(cache_dir: str, url: str, ttl_hours: float) -> str | None:
    """Return cached content if within TTL, else None."""
    if ttl_hours <= 0:
        return None  # cache disabled
    path = _cache_path(cache_dir, url)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = json.load(f)
        if _is_valid(entry, ttl_hours):
            return str(entry.get("content", ""))
    except (json.JSONDecodeError, OSError):
        pass
    return None


def cache_prune(cache_dir: str, ttl_hours: float) -> int:
    """Remove cache entries older than TTL. Returns count of pruned files."""
    if not os.path.isdir(cache_dir):
        return 0
    if ttl_hours <= 0:
        return 0  # cache disabled, don't prune
    pruned = 0
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if not _is_valid(entry, ttl_hours):
                os.remove(fpath)
                pruned += 1
        except (json.JSONDecodeError, OSError):
            # Corrupt file — remove it
            try:
                os.remove(fpath)
                pruned += 1
            except OSError:
                pass
    return pruned


def cache_list_valid(cache_dir: str, ttl_hours: float) -> list[dict[str, Any]]:
    """Return list of valid cache entries [{url, fetched_ts, key}, ...]."""
    if not os.path.isdir(cache_dir) or ttl_hours <= 0:
        return []
    entries = []
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if _is_valid(entry, ttl_hours):
                entries.append(
                    {
                        "url": entry.get("url", ""),
                        "fetched_ts": entry.get("fetched_ts", 0),
                        "key": fname.replace(".json", ""),
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass
    return entries


def cache_inject_context(cache_dir: str, ttl_hours: float) -> str:
    """Build a prompt context block with all valid cached URL content.

    Returns empty string if no valid entries or cache is disabled.
    """
    if ttl_hours <= 0:
        return ""
    if not os.path.isdir(cache_dir):
        return ""
    sections = []
    for fname in sorted(os.listdir(cache_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if _is_valid(entry, ttl_hours):
                url = entry.get("url", "unknown")
                content = entry.get("content", "")
                if content:
                    sections.append(f"### Cached: {url}\n\n{content}")
        except (json.JSONDecodeError, OSError):
            pass
    if not sections:
        return ""
    header = (
        "## Pre-Fetched URL Cache\n\n"
        "The following URLs were fetched in a previous iteration and are still valid.\n"
        "Do NOT re-fetch these URLs. Use the cached content below instead.\n\n"
    )
    return header + "\n\n---\n\n".join(sections)


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="SPIRAL research cache manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # store
    p_store = sub.add_parser("store", help="Cache a URL response")
    p_store.add_argument("cache_dir")
    p_store.add_argument("url")
    p_store.add_argument("content_file", help="File containing the response content (- for stdin)")

    # lookup
    p_lookup = sub.add_parser("lookup", help="Look up a cached URL")
    p_lookup.add_argument("cache_dir")
    p_lookup.add_argument("url")
    p_lookup.add_argument("--ttl-hours", type=float, default=24)

    # prune
    p_prune = sub.add_parser("prune", help="Remove expired cache entries")
    p_prune.add_argument("cache_dir")
    p_prune.add_argument("--ttl-hours", type=float, default=24)

    # list
    p_list = sub.add_parser("list", help="List valid cache entries")
    p_list.add_argument("cache_dir")
    p_list.add_argument("--ttl-hours", type=float, default=24)

    # sim-lookup (US-403)
    p_sim = sub.add_parser("sim-lookup", help="Similarity-based cache lookup")
    p_sim.add_argument("cache_dir")
    p_sim.add_argument("query", help="Query string to match against cached embeddings")
    p_sim.add_argument("--ttl-hours", type=float, default=24)
    p_sim.add_argument("--threshold", type=float, default=0.92)

    # inject
    p_inject = sub.add_parser("inject", help="Generate prompt injection with cached content")
    p_inject.add_argument("cache_dir")
    p_inject.add_argument("--ttl-hours", type=float, default=24)

    args = parser.parse_args()

    if args.command == "store":
        if args.content_file == "-":
            content = sys.stdin.read()
        else:
            with open(args.content_file, "r", encoding="utf-8") as f:
                content = f.read()
        path = cache_store(args.cache_dir, args.url, content)
        print(path)

    elif args.command == "lookup":
        result = cache_lookup(args.cache_dir, args.url, args.ttl_hours)
        if result is None:
            sys.exit(1)
        print(result)

    elif args.command == "prune":
        count = cache_prune(args.cache_dir, args.ttl_hours)
        print(f"Pruned {count} expired entries")

    elif args.command == "list":
        entries = cache_list_valid(args.cache_dir, args.ttl_hours)
        print(json.dumps(entries, indent=2))

    elif args.command == "sim-lookup":
        result = cache_similarity_lookup(args.cache_dir, args.query, args.ttl_hours, args.threshold)
        if result is None:
            sys.exit(1)
        print(result)

    elif args.command == "inject":
        context = cache_inject_context(args.cache_dir, args.ttl_hours)
        if context:
            print(context)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
