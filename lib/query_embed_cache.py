"""query_embed_cache.py — Semantic query cache for Phase R research.

Uses sentence-transformers/all-MiniLM-L6-v2 to compute embeddings and
cosine similarity for cache lookup. Near-duplicate research queries reuse
cached Phase R results, cutting API costs on long runs.

Storage layout in CACHE_DIR (same dir as research_cache .json files):
    <SHA256(query)>.json  — cached result + metadata (fetched_ts, query)
    <SHA256(query)>.npy   — embedding vector (float32, shape [384])

CLI:
    python query_embed_cache.py store  CACHE_DIR QUERY CONTENT_FILE
    python query_embed_cache.py lookup CACHE_DIR QUERY [--threshold 0.92] [--ttl-hours 168]
    python query_embed_cache.py prune  CACHE_DIR [--ttl-hours 168]
    python query_embed_cache.py list   CACHE_DIR [--ttl-hours 168]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

from typing import Any

import numpy as np

# Lazy model singleton — loaded on first embedding request
_MODEL: Any = None
MODEL_NAME = "all-MiniLM-L6-v2"


def _query_key(query: str) -> str:
    """Return SHA-256 hex digest of the normalised query string."""
    normalised = query.strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _get_model() -> Any:
    """Return a cached SentenceTransformer model instance (lazy load)."""
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL


def _embed(query: str) -> "np.ndarray[Any, Any]":
    """Compute a float32 embedding for *query* using the MiniLM model."""
    model = _get_model()
    vec: np.ndarray[Any, Any] = model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
    return vec.astype(np.float32)


def _cosine_sim(a: "np.ndarray[Any, Any]", b: "np.ndarray[Any, Any]") -> float:
    """Return cosine similarity in [−1, 1] between two vectors."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _now_ts() -> float:
    return time.time()


def _is_valid(entry: dict[str, Any], ttl_hours: float) -> bool:
    """Return True if the cache entry has not exceeded its TTL."""
    if ttl_hours <= 0:
        return False
    fetched_ts = entry.get("fetched_ts", 0)
    age_hours = (_now_ts() - fetched_ts) / 3600
    return bool(age_hours < ttl_hours)


# ── Public API ────────────────────────────────────────────────────────────────


def query_store(cache_dir: str, query: str, content: str) -> str:
    """Store *content* for *query*; write .json metadata and .npy embedding.

    Returns the path to the .json file.
    """
    os.makedirs(cache_dir, exist_ok=True)
    key = _query_key(query)
    json_path = os.path.join(cache_dir, f"{key}.json")
    npy_path = os.path.join(cache_dir, f"{key}.npy")

    emb = _embed(query)
    np.save(npy_path, emb)

    entry = {
        "query": query.strip(),
        "fetched_ts": _now_ts(),
        "content": content,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)

    return json_path


def query_lookup(
    cache_dir: str,
    query: str,
    threshold: float = 0.92,
    ttl_hours: float = 168,
) -> str | None:
    """Return cached content for the best-matching query, or None.

    When *threshold* >= 1.0 the function uses exact key matching (no
    embedding computation). Otherwise it computes a query embedding and
    scans all .npy files for the highest cosine-similarity match above
    *threshold*.

    Returns None when:
    - Cache dir does not exist
    - ttl_hours <= 0 (cache disabled)
    - No entry exceeds *threshold*
    - Best entry has expired
    """
    if ttl_hours <= 0:
        return None
    if not os.path.isdir(cache_dir):
        return None

    key = _query_key(query)

    # ── Exact-match shortcut when threshold=1.0 ──────────────────────────────
    if threshold >= 1.0:
        json_path = os.path.join(cache_dir, f"{key}.json")
        if not os.path.exists(json_path):
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if _is_valid(entry, ttl_hours):
                return str(entry.get("content"))
        except (json.JSONDecodeError, OSError):
            pass
        return None

    # ── Embedding-based similarity scan ──────────────────────────────────────
    query_emb = _embed(query)

    best_sim = -1.0
    best_content: str | None = None

    for fname in os.listdir(cache_dir):
        if not fname.endswith(".npy"):
            continue
        entry_key = fname[:-4]  # strip .npy
        json_path = os.path.join(cache_dir, f"{entry_key}.json")
        npy_path = os.path.join(cache_dir, fname)

        if not os.path.exists(json_path):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not _is_valid(entry, ttl_hours):
            continue

        try:
            cached_emb = np.load(npy_path).astype(np.float32)
        except (OSError, ValueError):
            continue

        sim = _cosine_sim(query_emb, cached_emb)
        if sim > best_sim:
            best_sim = sim
            best_content = str(entry.get("content", ""))

    if best_sim >= threshold and best_content is not None:
        return best_content
    return None


def query_prune(cache_dir: str, ttl_hours: float) -> int:
    """Remove expired .json and paired .npy files. Returns count of pruned pairs."""
    if not os.path.isdir(cache_dir):
        return 0
    if ttl_hours <= 0:
        return 0

    pruned = 0
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        json_path = os.path.join(cache_dir, fname)
        key = fname[:-5]  # strip .json
        npy_path = os.path.join(cache_dir, f"{key}.npy")

        remove = False
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if not _is_valid(entry, ttl_hours):
                remove = True
        except (json.JSONDecodeError, OSError):
            remove = True

        if remove:
            try:
                os.remove(json_path)
            except OSError:
                pass
            try:
                os.remove(npy_path)
            except OSError:
                pass
            pruned += 1

    return pruned


def query_list_valid(cache_dir: str, ttl_hours: float) -> list[dict[str, Any]]:
    """Return list of valid query cache entries [{query, fetched_ts, key}, ...]."""
    if not os.path.isdir(cache_dir) or ttl_hours <= 0:
        return []

    entries = []
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        json_path = os.path.join(cache_dir, fname)
        key = fname[:-5]
        # Only consider entries that also have a paired .npy
        npy_path = os.path.join(cache_dir, f"{key}.npy")
        if not os.path.exists(npy_path):
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if _is_valid(entry, ttl_hours):
                entries.append(
                    {
                        "query": entry.get("query", ""),
                        "fetched_ts": entry.get("fetched_ts", 0),
                        "key": key,
                    }
                )
        except (json.JSONDecodeError, OSError):
            pass

    return entries


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="SPIRAL query embedding cache manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # store
    p_store = sub.add_parser("store", help="Cache a query result")
    p_store.add_argument("cache_dir")
    p_store.add_argument("query")
    p_store.add_argument("content_file", help="File with content to cache (- for stdin)")

    # lookup
    p_lookup = sub.add_parser("lookup", help="Look up a cached query by similarity")
    p_lookup.add_argument("cache_dir")
    p_lookup.add_argument("query")
    p_lookup.add_argument("--threshold", type=float, default=0.92)
    p_lookup.add_argument("--ttl-hours", type=float, default=168)

    # prune
    p_prune = sub.add_parser("prune", help="Remove expired query cache entries")
    p_prune.add_argument("cache_dir")
    p_prune.add_argument("--ttl-hours", type=float, default=168)

    # list
    p_list = sub.add_parser("list", help="List valid query cache entries")
    p_list.add_argument("cache_dir")
    p_list.add_argument("--ttl-hours", type=float, default=168)

    args = parser.parse_args()

    if args.command == "store":
        if args.content_file == "-":
            content = sys.stdin.read()
        else:
            with open(args.content_file, "r", encoding="utf-8") as f:
                content = f.read()
        path = query_store(args.cache_dir, args.query, content)
        print(path)

    elif args.command == "lookup":
        result = query_lookup(args.cache_dir, args.query, args.threshold, args.ttl_hours)
        if result is None:
            sys.exit(1)
        print(result)

    elif args.command == "prune":
        count = query_prune(args.cache_dir, args.ttl_hours)
        print(f"Pruned {count} expired query cache entries")

    elif args.command == "list":
        entries = query_list_valid(args.cache_dir, args.ttl_hours)
        print(json.dumps(entries, indent=2))


if __name__ == "__main__":
    main()
