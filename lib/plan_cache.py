"""plan_cache.py — Agentic Plan Cache for SPIRAL (US-353).

Caches successful story decomposition/implementation plans in .spiral/plan_cache/
indexed by a key derived from story type + estimated complexity + primary file extension.
On Phase I entry, retrieves the closest cached plan and passes it to Ralph as a
suggested implementation approach.

Based on NeurIPS 2025 APC research: keyword-based matching outperforms embedding
similarity for agentic plan retrieval.

Usage (CLI):
    python plan_cache.py store  CACHE_DIR --story-json STORY_JSON_FILE --plan-json PLAN_JSON_FILE
    python plan_cache.py lookup CACHE_DIR --story-json STORY_JSON_FILE --ttl-hours 168
    python plan_cache.py prune  CACHE_DIR --ttl-hours 168
    python plan_cache.py inject CACHE_DIR --story-json STORY_JSON_FILE --ttl-hours 168
"""
import argparse
import hashlib
import json
import os
import sys
import time
from difflib import SequenceMatcher
from typing import Any


def _primary_file_ext(story: dict[str, Any]) -> str:
    """Extract the most common file extension from filesTouch."""
    files_to_touch: list[str] = story.get("filesTouch", [])
    if not files_to_touch:
        return ""
    ext_counts: dict[str, int] = {}
    for f in files_to_touch:
        _, ext = os.path.splitext(f)
        ext = ext.lower()
        if ext:
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
    if not ext_counts:
        return ""
    return max(ext_counts, key=lambda k: ext_counts[k])


def _story_type(story: dict[str, Any]) -> str:
    """Derive a story type string from tags, source, and title keywords."""
    parts: list[str] = []
    # Source field
    source: str = story.get("_source", "")
    if source:
        parts.append(source)
    # Tags
    tags: list[str] = story.get("tags", [])
    for tag in sorted(tags):
        parts.append(tag)
    # Title keywords (lowercase, first 3 significant words)
    title: str = story.get("title", "")
    stop_words = {"a", "an", "the", "to", "for", "in", "on", "of", "and", "or", "with"}
    words = [w.lower() for w in title.split() if w.lower() not in stop_words]
    parts.extend(words[:3])
    return "|".join(parts) if parts else "unknown"


def plan_cache_key(story: dict[str, Any]) -> str:
    """Generate a cache key as sha256(story_type + complexity + primary_file_ext)."""
    story_type = _story_type(story)
    complexity: str = story.get("estimatedComplexity", "medium")
    ext = _primary_file_ext(story)
    raw = f"{story_type}|{complexity}|{ext}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _similarity_score(key_a: str, key_b: str) -> float:
    """Compute string similarity between two cache key source strings."""
    return SequenceMatcher(None, key_a, key_b).ratio()


def _key_source(story: dict[str, Any]) -> str:
    """Return the raw string used to generate the cache key (for similarity matching)."""
    story_type = _story_type(story)
    complexity: str = story.get("estimatedComplexity", "medium")
    ext = _primary_file_ext(story)
    return f"{story_type}|{complexity}|{ext}"


def _now_ts() -> float:
    return time.time()


def _is_valid(entry: dict[str, Any], ttl_hours: float) -> bool:
    """Return True if the cache entry is within TTL."""
    if ttl_hours <= 0:
        return False
    stored_ts: float = entry.get("stored_ts", 0)
    age_hours = (_now_ts() - stored_ts) / 3600
    return bool(age_hours < ttl_hours)


def plan_cache_store(cache_dir: str, story: dict[str, Any], plan: dict[str, Any]) -> str:
    """Store a successful story's plan in the cache. Returns cache file path."""
    os.makedirs(cache_dir, exist_ok=True)
    key = plan_cache_key(story)
    path = os.path.join(cache_dir, f"{key}.json")
    entry: dict[str, Any] = {
        "story_id": story.get("id", ""),
        "story_title": story.get("title", ""),
        "key_source": _key_source(story),
        "stored_ts": _now_ts(),
        "plan": plan,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    return path


def plan_cache_lookup(cache_dir: str, story: dict[str, Any], ttl_hours: float) -> dict[str, Any] | None:
    """Look up a cached plan for a story.

    First tries exact key match, then falls back to keyword-based similarity
    matching across all valid entries. Returns the plan dict or None.
    """
    if ttl_hours <= 0 or not os.path.isdir(cache_dir):
        return None

    key = plan_cache_key(story)
    exact_path = os.path.join(cache_dir, f"{key}.json")

    # Exact match
    if os.path.exists(exact_path):
        try:
            with open(exact_path, "r", encoding="utf-8") as f:
                entry: dict[str, Any] = json.load(f)
            if _is_valid(entry, ttl_hours):
                return entry
        except (json.JSONDecodeError, OSError):
            pass

    # Similarity fallback: find best match above threshold
    query_source = _key_source(story)
    best_score = 0.0
    best_entry: dict[str, Any] | None = None
    similarity_threshold = 0.6

    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                candidate: dict[str, Any] = json.load(f)
            if not _is_valid(candidate, ttl_hours):
                continue
            entry_source: str = candidate.get("key_source", "")
            score = _similarity_score(query_source, entry_source)
            if score > best_score and score >= similarity_threshold:
                best_score = score
                best_entry = candidate
        except (json.JSONDecodeError, OSError):
            pass

    return best_entry


def plan_cache_prune(cache_dir: str, ttl_hours: float) -> int:
    """Remove cache entries older than TTL. Returns count of pruned files."""
    if not os.path.isdir(cache_dir) or ttl_hours <= 0:
        return 0
    pruned = 0
    for fname in os.listdir(cache_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(cache_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry: dict[str, Any] = json.load(f)
            if not _is_valid(entry, ttl_hours):
                os.remove(fpath)
                pruned += 1
        except (json.JSONDecodeError, OSError):
            try:
                os.remove(fpath)
                pruned += 1
            except OSError:
                pass
    return pruned


def plan_cache_inject(cache_dir: str, story: dict[str, Any], ttl_hours: float) -> str:
    """Build a suggested_approach prompt block from a cached plan.

    Returns empty string if no match found or cache disabled.
    """
    entry = plan_cache_lookup(cache_dir, story, ttl_hours)
    if entry is None:
        return ""

    plan: Any = entry.get("plan", {})
    source_story: str = entry.get("story_id", "unknown")
    source_title: str = entry.get("story_title", "")

    # Format plan as readable markdown
    plan_text = json.dumps(plan, indent=2) if isinstance(plan, dict) else str(plan)

    header = (
        "## Suggested Implementation Approach (Plan Cache)\n\n"
        f"A similar story ({source_story}: {source_title}) was previously implemented successfully.\n"
        "The decomposition plan below may help guide your approach. Adapt it as needed.\n\n"
        "```json\n"
        f"{plan_text}\n"
        "```"
    )
    return header


# ── CLI ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL agentic plan cache (US-353)")
    sub = parser.add_subparsers(dest="command", required=True)

    # store
    p_store = sub.add_parser("store", help="Cache a story's implementation plan")
    p_store.add_argument("cache_dir")
    p_store.add_argument("--story-json", required=True, help="Path to story JSON file")
    p_store.add_argument("--plan-json", required=True, help="Path to plan JSON file (- for stdin)")

    # lookup
    p_lookup = sub.add_parser("lookup", help="Look up a cached plan for a story")
    p_lookup.add_argument("cache_dir")
    p_lookup.add_argument("--story-json", required=True)
    p_lookup.add_argument("--ttl-hours", type=float, default=168)

    # prune
    p_prune = sub.add_parser("prune", help="Remove expired plan cache entries")
    p_prune.add_argument("cache_dir")
    p_prune.add_argument("--ttl-hours", type=float, default=168)

    # inject
    p_inject = sub.add_parser("inject", help="Generate suggested_approach prompt from cache")
    p_inject.add_argument("cache_dir")
    p_inject.add_argument("--story-json", required=True)
    p_inject.add_argument("--ttl-hours", type=float, default=168)

    args = parser.parse_args()

    def _load_story(path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]

    if args.command == "store":
        story = _load_story(args.story_json)
        if args.plan_json == "-":
            plan: dict[str, Any] = json.load(sys.stdin)
        else:
            with open(args.plan_json, "r", encoding="utf-8") as f:
                plan = json.load(f)
        path = plan_cache_store(args.cache_dir, story, plan)
        print(path)

    elif args.command == "lookup":
        story = _load_story(args.story_json)
        result = plan_cache_lookup(args.cache_dir, story, args.ttl_hours)
        if result is None:
            print("{}")
            return 1
        print(json.dumps(result, indent=2))

    elif args.command == "prune":
        count = plan_cache_prune(args.cache_dir, args.ttl_hours)
        print(f"Pruned {count} expired plan cache entries")

    elif args.command == "inject":
        story = _load_story(args.story_json)
        context = plan_cache_inject(args.cache_dir, story, args.ttl_hours)
        if context:
            print(context)
        else:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
