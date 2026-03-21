"""research_dedup.py — Query similarity deduplication for Phase R Gemini calls.

Before Phase R calls Gemini, this module checks .spiral/research_cache.json
for semantically similar prior queries. If a cached entry's topic is similar
enough (cosine TF-IDF similarity >= SPIRAL_RESEARCH_DEDUP_THRESHOLD), it
returns the cached research result, skipping the Gemini API call entirely.

Usage (CLI):
    python lib/research_dedup.py --query QUERY [--threshold 0.85] [--cache-path .spiral/research_cache.json]

Exit codes:
    0 — cache hit found (JSON printed to stdout)
    1 — no match above threshold (cache miss)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Default threshold — configurable via SPIRAL_RESEARCH_DEDUP_THRESHOLD env var
SPIRAL_RESEARCH_DEDUP_THRESHOLD: float = float(os.environ.get("SPIRAL_RESEARCH_DEDUP_THRESHOLD", "0.85"))

_DEFAULT_CACHE_PATH = os.path.join(".spiral", "research_cache.json")


def query_similarity(q1: str, q2: str) -> float:
    """Return TF-IDF cosine similarity in [0.0, 1.0] between two query strings.

    Uses scikit-learn TfidfVectorizer to avoid any heavy model dependencies.
    Identical strings return 1.0; orthogonal (no common tokens) return 0.0.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine

    q1 = q1.strip()
    q2 = q2.strip()
    if not q1 or not q2:
        return 0.0
    if q1 == q2:
        return 1.0

    try:
        vec = TfidfVectorizer().fit_transform([q1, q2])
        sim = float(sk_cosine(vec[0], vec[1])[0][0])
        return max(0.0, min(1.0, sim))
    except ValueError:
        # TfidfVectorizer raises ValueError if vocabulary is empty after tokenising
        return 0.0


def find_cached_response(
    query: str,
    cache_path: str = _DEFAULT_CACHE_PATH,
    threshold: float | None = None,
) -> dict[str, Any] | None:
    """Return the best-matching cached research result above *threshold*, or None.

    Iterates all entries in *cache_path* (a research_cache.json file as written
    by lib/phases/research_cache.py), computes TF-IDF similarity between *query*
    and each cached topic, and returns the result dict of the best match that
    exceeds *threshold*.

    Returns None when:
    - cache file does not exist
    - cache is empty
    - no entry's similarity exceeds *threshold*
    - cache file is corrupt
    """
    if threshold is None:
        threshold = SPIRAL_RESEARCH_DEDUP_THRESHOLD

    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(cache, dict) or not cache:
        return None

    best_sim = -1.0
    best_result: dict[str, Any] | None = None

    for _key, entry in cache.items():
        if not isinstance(entry, dict):
            continue
        topic = entry.get("topic", "")
        if not isinstance(topic, str) or not topic:
            continue

        sim = query_similarity(query, topic)
        if sim > best_sim and sim >= threshold:
            result = entry.get("result")
            if isinstance(result, dict):
                best_sim = sim
                best_result = result

    return best_result


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Check research_cache.json for a semantically similar prior query")
    parser.add_argument("--query", required=True, help="The current research query")
    parser.add_argument(
        "--threshold",
        type=float,
        default=SPIRAL_RESEARCH_DEDUP_THRESHOLD,
        help="Cosine similarity threshold (default: %(default)s)",
    )
    parser.add_argument(
        "--cache-path",
        default=_DEFAULT_CACHE_PATH,
        help="Path to research_cache.json (default: %(default)s)",
    )
    args = parser.parse_args()

    result = find_cached_response(args.query, args.cache_path, args.threshold)
    if result is None:
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
