"""research_cache.py — Semantic research query caching with TF-IDF vectors.

Implements US-773: cache research queries using TF-IDF + cosine similarity.
Queries >0.90 similar to cached entries return cached results without new API calls.
Cache entries older than SPIRAL_RESEARCH_CACHE_TTL are pruned automatically.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class CachedQuery:
    """A cached research query with token vector and result."""

    query: str
    result: str
    iteration: int
    tokens: list[str]  # List of query tokens for Jaccard similarity

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedQuery:
        """Create from dictionary."""
        return cls(
            query=data.get("query", ""),
            result=data.get("result", ""),
            iteration=data.get("iteration", 0),
            tokens=data.get("tokens", []),
        )


def tokenize(text: str) -> list[str]:
    """Tokenize text into words (lowercase, alphanumeric only)."""
    words = re.findall(r"\b\w+\b", text.lower())
    return words


def compute_query_vector(query: str) -> set[str]:
    """Compute token set for a query (simplified from TF-IDF).

    Returns set of tokens for Jaccard similarity matching.
    """
    tokens = tokenize(query)
    return set(tokens)


def jaccard_similarity(set1: set[str], set2: set[str]) -> float:
    """Compute Jaccard similarity between two token sets.

    Returns value in [0, 1].
    """
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


def load_research_cache(cache_path: Path) -> list[CachedQuery]:
    """Load cached queries from .spiral/research_cache.json."""
    if not cache_path.exists():
        return []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_queries = data.get("cached_queries", [])
        return [CachedQuery.from_dict(q) for q in cached_queries]
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


def save_research_cache(
    cached_queries: list[CachedQuery],
    cache_path: Path,
    ttl_iterations: int = 5,
    current_iteration: int = 0,
) -> None:
    """Save cached queries to .spiral/research_cache.json with TTL pruning.

    Args:
        cached_queries: List of cached queries
        cache_path: Path to .spiral/research_cache.json
        ttl_iterations: Max age of cache entries (default 5 iterations)
        current_iteration: Current iteration for TTL calculation
    """
    # Prune old entries
    min_iteration = current_iteration - ttl_iterations
    pruned = [q for q in cached_queries if q.iteration >= min_iteration]

    data = {
        "cached_queries": [q.to_dict() for q in pruned],
        "total_cached": len(pruned),
        "last_iteration": current_iteration,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_cached_result(
    query: str,
    cache_path: Path,
    similarity_threshold: float = 0.90,
) -> tuple[bool, str]:
    """Check if query is cached and return result if similarity > threshold.

    Returns:
        (is_cached, result): True with cached result if hit, False with empty string if miss
    """
    cached_queries = load_research_cache(cache_path)
    if not cached_queries:
        return False, ""

    query_tokens = compute_query_vector(query)
    if not query_tokens:
        return False, ""

    for cached in cached_queries:
        cached_tokens = set(cached.tokens)
        similarity = jaccard_similarity(query_tokens, cached_tokens)
        if similarity >= similarity_threshold:
            return True, cached.result

    return False, ""


def record_query_result(
    query: str,
    result: str,
    cache_path: Path,
    iteration: int = 0,
    ttl_iterations: int = 5,
) -> None:
    """Record a new query and its research result to the cache.

    Args:
        query: The research query
        result: The research result/response
        cache_path: Path to .spiral/research_cache.json
        iteration: Current SPIRAL iteration
        ttl_iterations: Max age of cache entries
    """
    cached_queries = load_research_cache(cache_path)

    # Compute token set for this query
    query_tokens = list(compute_query_vector(query))

    # Create and add new cached query
    new_cached = CachedQuery(
        query=query,
        result=result,
        iteration=iteration,
        tokens=query_tokens,
    )
    cached_queries.append(new_cached)

    # Save with TTL pruning
    save_research_cache(cached_queries, cache_path, ttl_iterations, iteration)


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
