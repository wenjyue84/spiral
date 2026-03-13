"""research_cache.py — URL-level cache for Phase R research responses.

Caches fetched URL content in .spiral/research_cache/<md5-of-url>.json
with a configurable TTL. Eliminates redundant HTTP fetches across iterations.

Usage (CLI):
    python research_cache.py store  CACHE_DIR URL CONTENT_FILE
    python research_cache.py lookup CACHE_DIR URL --ttl-hours 24
    python research_cache.py prune  CACHE_DIR --ttl-hours 24
    python research_cache.py list   CACHE_DIR --ttl-hours 24
    python research_cache.py inject CACHE_DIR --ttl-hours 24
"""
import argparse
import hashlib
import json
import os
import sys
import time


def _cache_key(url: str) -> str:
    """Return MD5 hex digest of a normalised URL."""
    normalised = url.strip().rstrip("/")
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: str, url: str) -> str:
    return os.path.join(cache_dir, f"{_cache_key(url)}.json")


def _now_ts() -> float:
    return time.time()


def _is_valid(entry: dict, ttl_hours: float) -> bool:
    """Return True if the cache entry is within TTL."""
    if ttl_hours <= 0:
        return False  # cache disabled
    fetched_ts = entry.get("fetched_ts", 0)
    age_hours = (_now_ts() - fetched_ts) / 3600
    return age_hours < ttl_hours


def cache_store(cache_dir: str, url: str, content: str) -> str:
    """Store URL content in the cache. Returns the cache file path."""
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(cache_dir, url)
    entry = {
        "url": url.strip(),
        "fetched_ts": _now_ts(),
        "content": content,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
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
            return entry.get("content")
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


def cache_list_valid(cache_dir: str, ttl_hours: float) -> list[dict]:
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
                entries.append({
                    "url": entry.get("url", ""),
                    "fetched_ts": entry.get("fetched_ts", 0),
                    "key": fname.replace(".json", ""),
                })
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
def main():
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

    elif args.command == "inject":
        context = cache_inject_context(args.cache_dir, args.ttl_hours)
        if context:
            print(context)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
